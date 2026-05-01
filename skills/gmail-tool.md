# Gmail Tool

Use this when sir asks about Gmail, inbox, email search, reading messages, drafting, or sending email.

Behavior:

- Use Gmail search/list for inbox queries.
- Use Gmail read only when a message id is known or returned by search.
- Prefer creating a draft for important/ambiguous email content unless sir clearly asks to send.
- For sending, require recipient, subject, and body.
- Report message ids and draft ids clearly.
- Never expose OAuth tokens, client secrets, or raw credential files.

Setup:

- Requires Google API Python libraries.
- Requires a Google Desktop OAuth client secret file.
- Uses `GOOGLE_CLIENT_SECRET_FILE` and `GOOGLE_TOKEN_FILE` from `.env`.
