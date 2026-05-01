# Local Files Tool

Use this when sir asks to inspect normal local files without explicitly asking for PowerShell.

- show allowed folders
- list files in an allowed folder
- search file and folder names
- read a text file

Behavior:

- Stay inside `LOCAL_FILE_ALLOWED_PATHS`.
- If `LOCAL_FILE_ALLOWED_PATHS` is empty, use normal user folders like Desktop, Documents, Downloads, Music, Pictures, and Videos.
- Use terminal instead when sir explicitly asks for a terminal, PowerShell, git, install, unrestricted filesystem, or command-line action.
- Report denied paths plainly instead of trying another route.
