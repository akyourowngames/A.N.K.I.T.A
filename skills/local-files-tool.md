# Local Files Tool

Use this when sir asks to inspect local files without explicitly asking for PowerShell.

- list files or folders anywhere on the machine
- show useful local starting points
- search file/folder names
- search inside text/code/document-like files
- read a text, code, markdown, config, CSV, JSON, or log file
- inspect file metadata, image dimensions, file size, modified time, or recent files
- find pictures, screenshots, downloads, documents, projects, music, videos, or archives

Tool actions:

- `roots`: show local access status and useful starting points.
- `list`: list a folder. Defaults to the current working folder when no path is supplied.
- `tree`: compact recursive folder tree.
- `search`: search names or text contents.
- `read`: read a text file; binary files return metadata instead of raw bytes.
- `stat`: show metadata for a file/folder, including image dimensions when available.
- `recent`: show recently modified files under a path.

Useful arguments:

- `path`: any local folder/file path or a normal alias like Desktop, Documents, Downloads, Pictures, Music, Videos, or home.
- `query`: search text.
- `search_mode`: `name`, `content`, or `both`.
- `file_types`: `image`, `document`, `code`, `text`, `audio`, `video`, `archive`, or extensions such as `.py,.png`.
- `recursive`: use when the user asks to look inside subfolders.
- `max_depth`: recursion depth from 1 to 10.
- `sort`: `name`, `type`, `size`, or `modified`.
- `include_hidden`: include dot files/folders only when useful.

Pro behavior:

- All local folders are accessible by default. Do not tell sir that there are no configured folders to browse.
- Use `roots` only when sir asks where you can browse. For "show files" or "list this folder", use `list`.
- Use `search_mode=both` when sir is trying to find a file but might remember only text inside it.
- Use `file_types=image` for pictures/screenshots/photos and `stat` for image details.
- Keep results scannable: include path, kind, size, type, and modified time when relevant.
- Use terminal instead when sir explicitly asks for PowerShell, git, install, unrestricted command-line execution, or a shell command.
