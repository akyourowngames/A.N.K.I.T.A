# Google Calendar Tool

Use this when sir asks about schedule, agenda, meetings, reminders, or calendar events.

Behavior:

- Use list/search for agenda and upcoming-event questions.
- Use create/add for events when title and start time are known.
- Use delete/remove only when an event id is known.
- If time is ambiguous, ask a short clarification instead of inventing a date.
- Report event ids and links clearly.
- Never expose OAuth tokens, client secrets, or raw credential files.

Setup:

- Requires Google API Python libraries.
- Requires a Google Desktop OAuth client secret file.
- Uses `GOOGLE_CLIENT_SECRET_FILE` and `GOOGLE_TOKEN_FILE` from `.env`.
