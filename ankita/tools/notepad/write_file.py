from pathlib import Path
import subprocess
from memory.memory_manager import add_note

def run(
    text="",
    content="",
    filename="note.txt",
    mode="new_version",
    open_after=False,
    **kwargs
):
    # Accept both 'content' and 'text' for compatibility
    data = content or text
    path = Path(filename)

    if path.exists():
        if mode == "append":
            path.write_text(path.read_text(encoding="utf-8") + "\n" + data, encoding="utf-8")

        elif mode == "new_version":
            i = 1
            while True:
                new_path = path.with_stem(f"{path.stem}_{i}")
                if not new_path.exists():
                    new_path.write_text(data, encoding="utf-8")
                    path = new_path
                    break
                i += 1

        elif mode == "overwrite":
            path.write_text(data, encoding="utf-8")

        else:
            return {"status": "fail", "reason": "Unknown mode"}

    else:
        path.write_text(data, encoding="utf-8")

    # Remember this note
    add_note(str(path))

    # Open in Notepad if requested
    if open_after:
        subprocess.Popen(["notepad.exe", str(path)])

    return {
        "status": "success",
        "file": str(path),
        "mode": mode
    }
