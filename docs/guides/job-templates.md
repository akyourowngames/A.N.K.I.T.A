# Ready-made scheduled tasks

`node chat.mjs jobs templates` lists the starter library without writing files.
Choose a template and customize its schedule:

```sh
node chat.mjs jobs enable morning-brief --cron "daily at 08:30"
node chat.mjs jobs enable news-brief --topic "game development" --cron "weekdays at 16:00"
node chat.mjs jobs enable weekly-review --channel log
node chat.mjs jobs enable page-digest --url "YOUR_PAGE_URL" --cron "daily at 18:00"
```

The templates create real routines in the existing state store. `--state-file`
selects an explicit store for scripts/testing.
An existing scheduler must be running (CLI: `node chat.mjs --daemon`, or desktop).
`notify` uses your existing notification settings (including Telegram when
configured); `log` keeps the result in the daemon log or local desktop receipt
without sending a notification or teammate message, including delivery retries.
Failed and missed log-only runs remain local too; approval requests retain the
existing permission flow. The native failure-notification sink is stubbed in tests:
`TEMPLATE_FAILURE_LIVE failedNotifications=0 missedNotifications=0 nativeSink=fixture`.
The starter times are local times; cron uses the configured timezone.
Normal scheduler ownership and approval rules apply.

These templates ask for reading and summaries, with interaction and login disabled
in their task metadata. They do not implement a tab closer or download mover.
Topics and page URLs are supplied by you, rather than fixed external services.
Unknown templates, missing required input, invalid schedules and unsupported
channels fail before any state write.

Verification: six regressions passed, including real CLI listing with no state
write and CLI enabling followed by reloading the persisted routine. Future cloud
answers and actual notification delivery depend on your configured provider and
are not claimed by the local creation check. A real daemon/store round trip with
a fixture worker reports `configuredTimezone=UTC attempts=3 successfulDigests=2
previousSuccessSurvivesFailure=true`; desktop execution and retry report
`initialDeliveries=0 retryDeliveries=0 retainedResult=true` for a log-only task.
Page digests persist the last successful summary (bounded by the existing job
summary limit) across reload and failed reads; they still require fresh observations.
