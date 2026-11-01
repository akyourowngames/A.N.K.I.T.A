# Slack

Create a Slack app **from a manifest** in a workspace where you can install apps.
Use this JSON; it enables Socket Mode, DMs, channel mentions, files and approval
buttons without a public request URL:

```json
{
  "display_information": { "name": "Ankita", "description": "Your local teammate" },
  "features": {
    "bot_user": { "display_name": "Ankita", "always_online": false },
    "app_home": { "messages_tab_enabled": true, "messages_tab_read_only_enabled": false }
  },
  "oauth_config": {
    "scopes": {
      "bot": ["app_mentions:read", "chat:write", "reactions:write", "files:write", "im:history", "channels:history", "groups:history", "mpim:history"]
    }
  },
  "settings": {
    "socket_mode_enabled": true,
    "interactivity": { "is_enabled": true },
    "event_subscriptions": { "bot_events": ["app_mention", "message.im", "message.channels", "message.groups", "message.mpim"] },
    "org_deploy_enabled": false,
    "token_rotation_enabled": false
  }
}
```

These scopes allow receiving messages in conversations the bot joins; you can
omit group/history subscriptions and their matching scopes for a DM/mention-only
installation. Broader message subscriptions are needed for Open/allowlist group
mode and plain `/cancel` without a mention. Reinstall after changing scopes.

Generate an **app-level** `xapp` token with `connections:write` in Basic
Information. Install the app and copy its **bot** `xoxb` token from OAuth &
Permissions. These are different keys: the app key opens the socket; the bot key
sends messages. Invite the bot to any channel you want it to use.

In Ankita **Settings → Channels → Slack**, enter both tokens and choose a
teammate. Add conversation IDs, user IDs, or `server:WORKSPACE_ID`. Empty access
lists permit nobody, even when Slack has delivered the event. Groups require a
mention by default. Set your private bot DM ID (beginning with `D`) and user ID
as the owner destination/identity, then test, enable and save.

Environment fallback: `SLACK_ENABLED`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`,
`SLACK_ALLOWED_CHANNEL_IDS`, `SLACK_ALLOW_FROM`, `SLACK_OWNER_DM_ID`,
`SLACK_OWNER_USER_ID`. Explicit saved values win. Tokens stay on your computer;
the renderer receives has-key flags and blank replacement fields.

Replies use the parent thread timestamp. Work reactions, edits, owner buttons
and generated-image uploads are supported. Slack has no typing capability here,
so Ankita never makes a fake typing request. Use owner-DM `y` / `a` / `n` as a
button fallback. Bot/webhook/system messages are ignored. Ordinary incoming
attachments and voice calls are not imported or supported.

Uploads use Slack's current three-step external upload API, not the retired
`files.upload` method or the SDK-only `files.uploadV2` helper: obtain a signed
ticket, upload bytes without bot credentials, then complete/share it. Tickets
are restricted to Slack's file origin and redirects are refused.

Socket envelopes are acknowledged only after the shared core accepts/denies
them. A repeated envelope cannot rerun an accepted request. Refreshes obtain a
new socket URL; `link_disabled` stops until Socket Mode is re-enabled. Unknown
write outcomes are not blindly retried.

Official references: [Socket Mode and app manifest](https://docs.slack.dev/apis/events-api/using-socket-mode/),
[DM subscriptions](https://docs.slack.dev/surfaces/app-home/),
[upload ticket](https://docs.slack.dev/reference/methods/files.getUploadURLExternal/),
[upload completion](https://docs.slack.dev/reference/methods/files.completeUploadExternal/).
See [shared recovery](../channels.md#recovery) and the
[evidence matrix](../../verification/multi-channel-communication.md).

A real workspace install was not performed during this build. Final acceptance
needs an approved test workspace/DM: one request, owner button/text approval, a
file, cancellation and a socket refresh without a repeated agent turn.
