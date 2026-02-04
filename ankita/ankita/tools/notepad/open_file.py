import subprocess

def run(filename="", **kwargs):
    if filename:
        subprocess.Popen(["notepad.exe", filename])
    else:
        # Open blank notepad if no filename
        subprocess.Popen(["notepad.exe"])
    return {"status": "success"}
