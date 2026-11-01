# Chat channels (source build)

Talk to Ankita from Telegram, Discord or Slack while your computer and Ankita are
running. Connections stay on your computer. No extra SDK, public inbound port or
hosted relay is required for these three channels.

Open **Settings → Channels**, choose a channel, enter its keys and select a
teammate. Add allowed people or conversations before turning the connection on.
**Test connection** checks the account and credentials without saving the form;
**Save changes** saves and reconnects only that channel. Saving keeps existing
keys unless you replace them or explicitly choose Remove.

Channel work currently needs an API provider selected in Settings. ChatGPT
Browser is a browser-only conversation, so channel startup shows an explicit
setup message instead of trying to construct an API agent. Provider/model
changes wait for channel work, then refresh channel agents without losing their
saved conversations. This also prevents requests going to a previously selected
provider after a settings change.

| Channel | Setup | Connection |
| --- | --- | --- |
| Telegram | [Create a private bot](channels/telegram.md) | Outbound long polling |
| Discord | [Create and invite a bot](channels/discord.md) | Outbound Gateway socket |
| Slack | [Install a Socket Mode app](channels/slack.md) | Outbound Socket Mode |
| Other services | [Bridge/relay decision and adapter contract](channels/bridges.md) | Documented extension path; no extra connector is shipped |

## People and permissions

An empty access list permits nobody. **Allowed conversations** admits people in
those conversations; **Allowed people or servers/workspaces** accepts raw user
IDs, `user:ID`, or `server:ID`. These are alternatives, not an intersection.
Group messages still need a bot mention by default. Choose Open only for a
conversation whose members you intend to authorize. Bot, webhook and system
messages never run the agent.

Set the **Owner private conversation** and **Owner user ID** for approvals.
Approval buttons and `y` / `a` / `n` replies are accepted only from that owner in
their private conversation. Group replies cannot grant permission. Without a
valid owner destination, a tool needing permission is denied. Existing local
auto-approve settings still apply. Keep auto-approve off for channels shared with
people who should not change your computer.

Optional pairing codes are issued locally from Advanced controls or `/channels
pair <channel> <sender-id>`. Enable pairing and save first. The code binds one
sender on one channel, expires after two minutes and is consumed by one attempt.
The sender sends `/pair CODE`; it adds that sender to the access list. A pairing
code does not make them the approval owner.

## Messages, work and files

Each conversation has a queue; separate conversations can work together within
the shared four-turn host limit. A control reply or `/cancel` bypasses the work
queue. Cancellation stops that conversation's owned turn, denies its approvals
and prevents queued work from starting. It does not undo completed actions.

Discord, Slack and Telegram groups have separate saved histories. Telegram
private chats retain the earlier desktop teammate route for compatibility; if
several allowed Telegram DMs select the same teammate they share that history
and take turns on it. They do not take ownership of an already-running desktop
turn or its approvals.

Progress sends actual tool names at a bounded pace, never raw tool arguments or
model reasoning. Files follow the final reply. Automatic artifacts currently
cover up to five generated/downloaded images inside the workspace, not every
file the agent writes. Incoming files are not imported into a workspace. Telegram
retains its existing voice-note recognition and optional spoken replies; the
desktop Sarvam/Baseten voice panel is a separate feature.

Channel turns cannot use saved desktop browser credentials or the foreground
file picker. A channel still runs real tools in the chosen workspace, so only
authorize people you trust with that scope.

## Terminal and unattended use

In an interactive terminal session:

```text
/channels
/channels test discord
/channels connect discord
/channels status
/channels disconnect discord
/channels doctor
```

Do not paste keys into slash commands. Use Settings or your ignored local config
file; supported environment names are in [`.env.example`](../../.env.example).
Terminal connections use the terminal's current agent/model; they do not start
scheduled routines. `node chat.mjs --daemon` hosts enabled channels alongside
existing schedules. The terminal and desktop share the same channel settings.

Keep exactly one Ankita host per bot connection. Delivery receipts prevent
duplicate accepted work across hosts, but two simultaneous pollers/socket
consumers can still fight over platform delivery or connection limits. Closing
the host or sleeping the PC stops availability; this is not an always-on cloud
bot. Source use needs a Node runtime with native WebSocket support for Discord
and Slack; the app's bundled runtime already supplies it.

## Recovery

Settings migrate from v1 to v2 on first load, retaining an exact `.v1.bak` copy.
Corrupt settings are preserved and saves are blocked until repaired. Keys stay
on disk in the local profile; settings sent to the renderer contain only
has-key flags. POSIX files are owner-only; Windows uses the user's profile ACLs.

The sibling `channel-deliveries.json` stores inbound IDs and outbound receipts.
Explicit rate-limit rejections wait for the platform delay. A missing receipt,
timeout after a write or interrupted send becomes **unknown**, so Ankita does not
blindly send it again. Check the conversation, then issue a fresh request if
needed. A lost inbound claim after a crash is similarly not automatically rerun:
ask again after inspecting what already happened. This favors avoiding duplicate
actions over promising exactly-once execution.

Dead targets stay paused until a successful connection test. Doctor also reports
unreadable/full receipts or an existing writer lock. Close all hosts before
repairing or removing a stale lock; never delete receipts merely to hide an
uncertain send. Archive a full ledger only while all hosts are stopped, after
accepting that old platform replays will no longer have dedupe evidence.

Run `node scripts/verify-channels.mjs` for safe local transport checks. Current
coverage and real-account acceptance gaps are recorded in the
[verification matrix](../verification/multi-channel-communication.md).
