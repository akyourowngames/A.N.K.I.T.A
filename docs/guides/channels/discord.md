# Discord

Create an application at the [Discord developer portal](https://discord.com/developers/applications).
Under Bot, create/reset its bot token and enable **Message Content Intent**.
Copy the Application ID from General Information. Bot token and Application ID
must belong to the same application; Ankita checks the identity.

Use the portal's OAuth2 URL generator with the **bot** scope. Grant View Channels,
Send Messages, Send Messages in Threads, Read Message History, Add Reactions and
Attach Files. Invite it to your private test server. Administrator permission
is not needed. This connector uses Gateway messages and component buttons, not
slash commands or a public interaction endpoint.

In Ankita **Settings → Channels → Discord**:

1. Enter the token and Application ID and select a teammate.
2. Turn Discord Developer Mode on to copy IDs. Add an allowed channel ID, an
   allowed user ID, or `server:SERVER_ID`. A server grant admits that server's
   members; keep the default mention rule unless that is intended.
3. Open a private DM with the bot. Set its conversation ID as Owner private
   conversation and your user ID as Owner user ID. Add the private conversation
   to Allowed channel IDs if you also want to send tasks there.
4. Test, enable and save. Mention the bot in an allowed server channel.

Environment fallback: `DISCORD_ENABLED`, `DISCORD_BOT_TOKEN`,
`DISCORD_APPLICATION_ID`, `DISCORD_ALLOWED_CHANNEL_IDS`, `DISCORD_ALLOW_FROM`,
`DISCORD_OWNER_DM_ID`, `DISCORD_OWNER_USER_ID`. Shared behavior/pairing controls
are saved through Settings.

Replies stay in the originating channel or thread and use message references.
Typing, reactions, edits, generated-image uploads and owner approval buttons are
supported. Text `y` / `a` / `n` also works in the owner DM; `/cancel` stops owned
work. Generated text never enables role/everyone/user pings. Attachments from
users are not downloaded or imported. Voice-channel calling and audio streaming
are not part of this connector.

Gateway reconnects resume the last accepted sequence when possible; inbound
replays are deduped by the shared core. Missing heartbeat ACKs reconnect. Fatal
auth/intent/shard errors stop with an actionable error instead of retrying
forever. This is one local shard; large bots needing sharding are outside its
scope. Check the Message Content setting if Discord reports a disallowed intent.

Official details: [Gateway and privileged intents](https://github.com/discord/discord-api-docs/blob/main/developers/events/gateway.mdx),
[message references, safe mentions and multipart files](https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx).
See [shared recovery](../channels.md#recovery) and the
[evidence matrix](../../verification/multi-channel-communication.md).

Real-account acceptance still requires a private test server: one request,
owner button and text approval, an image, `/cancel` during work, and reconnect
without a repeated reply. Local native-socket checks cover that transport path
without claiming the application's permissions have been accepted by Discord.
