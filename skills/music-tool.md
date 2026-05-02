# Music Tool

Use this when sir asks to play, queue, pause, resume, skip, stop, or check music.

Behavior:

- Prefer the dedicated `music` tool over terminal commands for music playback.
- Use `play` with the requested song, artist, playlist/search text, or URL.
- Use `queue` when sir asks to add something after the current track.
- Use `pause`, `resume`, `next`, `stop`, `status`, or `clear` for playback controls.
- Do not hardcode songs, artists, sources, or player paths. Let yt-dlp resolve the request and let the configured player backend handle playback.
- If playback cannot start, report the setup issue plainly, such as missing `yt-dlp`, `mpv`, `ffplay`, or a blocked source.
