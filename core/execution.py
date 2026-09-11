"""Cooperative cancellation and observable execution, shared by channel adapters."""
import threading
import time


class ExecutionCancelled(RuntimeError):
    pass


class ExecutionTimedOut(ExecutionCancelled):
    pass


class ExecutionControl:
    def __init__(self, on_event=None, timeout=300, approve=None):
        self.cancelled = threading.Event()
        self.deadline = time.monotonic() + max(1, timeout)
        self.on_event = on_event
        self.approve = approve
        self.step = 0
        self.access = lambda name: 'approval'

    def cancel(self):
        self.cancelled.set()

    def check(self):
        if self.cancelled.is_set():
            raise ExecutionCancelled('Run cancelled. Completed actions remain recorded.')
        if time.monotonic() >= self.deadline:
            raise ExecutionTimedOut('Run timed out. Completed actions remain recorded.')

    def emit(self, kind, **data):
        if self.on_event:
            self.on_event(kind, data)

    def wait(self, seconds):
        self.cancelled.wait(min(seconds, max(0, self.deadline - time.monotonic())))
        self.check()

    def request_approval(self, name, args):
        self.check()
        if self.approve and not self.approve(name, args, self):
            raise ExecutionCancelled('Action was not approved. No further tools were run.')
        self.check()
