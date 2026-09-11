"""Cancellable Telegram runs with durable evidence and rate-limited live progress.

Polling never waits for a model/tool. A chat's next run waits for the previous
worker to settle, including after cancellation: Python cannot kill a tool thread.
"""
import asyncio
import logging
import time
import json
import secrets
import threading
from core import run_store
from core.execution import ExecutionControl, ExecutionCancelled, ExecutionTimedOut

log = logging.getLogger('zumba.telegram.execution')


def actor_id(payload):
    msg = payload.get('message') or payload.get('edited_message') or {}
    return int((msg.get('from') or {}).get('id') or (msg.get('chat') or {}).get('id') or 0)


class TelegramExecution:
    def __init__(self, api):
        self.api = api
        self.active = {}
        self.approvals = {}
        self._approval_lock = threading.Lock()

    def resolve_approval(self, data, chat_id, actor):
        action, _, token = data.partition(':')
        with self._approval_lock:
            pending = self.approvals.get(token)
            if not pending:
                return 'This approval has expired or was already used.'
            if pending['chat_id'] != chat_id or pending['actor'] != actor:
                return 'Only the task owner can approve this action.'
            try:
                pending['control'].check()
            except ExecutionCancelled:
                return 'This run is no longer accepting approvals.'
            if time.monotonic() >= pending['deadline']:
                return 'This approval has expired.'
            run_store.record(pending['run_id'], 'approval_decision', {'approved': action == 'approve', 'actor': actor})
            self.approvals.pop(token)
            pending['allowed'] = action == 'approve'
            pending['event'].set()
        return 'Approved for this call only.' if action == 'approve' else 'Denied. No action will start.'

    def _approve(self, run, loop, name, args, control):
        if control.access(name) in ('read', 'local'):
            return True
        details = json.dumps(args, ensure_ascii=False, indent=2)
        if len(details) > 2800:
            control.emit('stage', stage='Action too large to review safely in Telegram; approval denied')
            return False
        token = secrets.token_hex(12)
        pending = {'chat_id': int(run['chat_id']), 'actor': actor_id(run['payload']), 'run_id': run['id'],
                   'control': control, 'deadline': min(control.deadline, time.monotonic() + 90),
                   'event': threading.Event(), 'allowed': False}
        with self._approval_lock:
            self.approvals[token] = pending
        message_id = None
        try:
            control.emit('approval_requested', name=name, args=args)
            control.emit('stage', stage='Waiting for your approval · ' + name)
            buttons = {'inline_keyboard': [[{'text': 'Approve once', 'callback_data': 'approve:' + token},
                                           {'text': 'Deny', 'callback_data': 'deny:' + token}]]}
            future = asyncio.run_coroutine_threadsafe(self.api.send_message(int(run['chat_id']),
                f'Approval needed · {name}\n\n{details}\n\nOne call only. Expires in 90 seconds.', reply_markup=buttons), loop)
            try:
                message_id = future.result(timeout=min(30, max(.1, control.deadline - time.monotonic())))
            except Exception:
                future.cancel()
                return False
            while not pending['event'].wait(.1):
                control.check()
                if time.monotonic() >= pending['deadline']:
                    return False
            control.check()
            return pending['allowed']
        finally:
            with self._approval_lock:
                self.approvals.pop(token, None)
            if message_id and not loop.is_closed():
                async def settle():
                    try:
                        await self.api.edit_message(int(run['chat_id']), message_id,
                            ('Approved once' if pending['allowed'] else 'Not approved / expired') + ' · ' + name,
                            reply_markup={'inline_keyboard': []})
                    except Exception:
                        pass
                asyncio.run_coroutine_threadsafe(settle(), loop)

    def cancel(self, run, actor):
        if actor_id(run['payload']) != actor:
            return 'Only the task owner can cancel this run.'
        if run['status'] not in ('queued', 'running'):
            return 'This run has already ended.'
        control = self.active.get(run['id'])
        if control:
            control.cancel()
        reply = ('Cancelled. No further steps will start. An action already in flight may still finish; '
                 'its outcome must be checked before retrying. Use /status for the saved result.')
        run_store.record(run['id'], 'cancel_requested', {'actor': actor})
        run_store.finish(run['id'], 'cancelled', reply)
        return reply

    async def execute(self, run, session, text):
        from core.chat_pipeline import aanswer
        run_id, chat_id = run['id'], int(run['chat_id'])
        persisted = run_store.get(run_id)
        if persisted['status'] != 'running':
            return persisted
        loop = asyncio.get_running_loop()
        started_at = time.monotonic()
        first_token = False
        state = {'stage': 'Recalling context', 'text': '', 'version': 0}

        def update(kind, data):
            if kind == 'token':
                state['text'] = (state['text'] + data.get('token', ''))[-2800:]
            elif kind == 'tool_start':
                state['stage'] = f"Step {data.get('id', '?')} · {data['name']}"
                state['text'] = ''
            elif kind == 'tool_end':
                state['stage'] = ('Tool failed' if data.get('failed') else 'Tool finished') + ' · ' + data['name']
            elif kind == 'stage':
                state['stage'] = data['stage']
                state['text'] = ''
            elif kind == 'retry':
                state['stage'] = f"Provider retry {data.get('attempt')}"
                state['text'] = ''
            state['version'] += 1

        def event(kind, data):
            nonlocal first_token
            # Journal before side effects; do not incur a database write per token.
            if kind != 'token':
                run_store.record(run_id, kind, data)
            elif not first_token:
                first_token = True
                run_store.record(run_id, 'first_token', {'elapsed_ms': round((time.monotonic() - started_at) * 1000)})
            if not loop.is_closed():
                loop.call_soon_threadsafe(update, kind, data)

        control = ExecutionControl(on_event=event, timeout=300,
            approve=lambda name, args, ctl: self._approve(run, loop, name, args, ctl))
        self.active[run_id] = control
        message_id = None
        buttons = {'inline_keyboard': [[{'text': 'Stop task', 'callback_data': 'cancel:' + run_id}]]}
        async def acknowledge():
            nonlocal message_id
            try:
                message_id = await self.api.send_message(chat_id, 'Starting · ' + run_id + '\n/status · /cancel', reply_markup=buttons)
            except Exception:
                log.warning('Progress delivery failed for run %s', run_id)

        async def progress():
            version = -1
            while True:
                await asyncio.sleep(1.2)
                if not message_id or state['version'] == version or control.cancelled.is_set():
                    continue
                version = state['version']
                preview = state['stage'] + '\n' + run_id
                if state['text']:
                    preview += '\n\nDraft — not yet final:\n' + state['text']
                try:
                    await self.api.edit_message(chat_id, message_id, preview, reply_markup=buttons)
                except Exception as exc:
                    # Edits are idempotent. Honor Telegram flood control without
                    # blocking intake or repeating a send with an unknown outcome.
                    await asyncio.sleep(max(1.2, min(60, getattr(exc, 'retry_after', 0) or 0)))

        acknowledgement = asyncio.create_task(acknowledge())
        updater = asyncio.create_task(progress())
        worker = asyncio.create_task(aanswer(session, text, control=control))
        try:
            reply = await asyncio.wait_for(asyncio.shield(worker), timeout=max(.1, control.deadline - time.monotonic()))
            control.check()
            run_store.finish(run_id, 'completed', reply or '(empty response)')
        except ExecutionTimedOut:
            run_store.finish(run_id, 'timed_out', 'Task timed out. Completed steps are saved; no automatic replay.')
        except ExecutionCancelled:
            run_store.finish(run_id, 'cancelled', 'Cancelled. Completed steps are saved. An in-flight action may still finish.')
        except asyncio.TimeoutError:
            control.cancel()
            run_store.finish(run_id, 'timed_out', 'Task timed out. An in-flight action may still finish; check /status before retrying.')
        except asyncio.CancelledError:
            control.cancel()
            run_store.finish(run_id, 'interrupted', 'Zumba stopped during this run. No action has been replayed; check completed steps before retrying.')
            raise
        except Exception as exc:
            run_store.finish(run_id, 'failed', 'Task failed. Completed tool results are saved; use /status.', error=f'{type(exc).__name__}: {exc}')
        finally:
            updater.cancel()
            await asyncio.gather(updater, return_exceptions=True)
            if not acknowledgement.done():
                acknowledgement.cancel()
            await asyncio.gather(acknowledgement, return_exceptions=True)
            # Persisted terminal state wins over a late success from a cancelled worker.
            result = run_store.get(run_id)
            if message_id:
                try:
                    await self.api.edit_message(chat_id, message_id, f"{result['stage']} · {run_id}\n/status for saved steps", reply_markup={'inline_keyboard': []})
                except Exception:
                    pass
            if result['status'] != 'interrupted':
                try:
                    await self.api.send_message(chat_id, result['reply'])
                    run_store.delivered(run_id)
                except Exception:
                    # Retain the outcome; never replay execution to repair delivery.
                    log.warning('Final delivery uncertain for run %s; outcome retained', run_id)
            if not worker.done():
                try:
                    await asyncio.shield(worker)
                except (Exception, asyncio.CancelledError):
                    pass
            self.active.pop(run_id, None)
        return run_store.get(run_id)
