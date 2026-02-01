import subprocess

def run(filename="", **kwargs):
    if filename:
        subprocess.Popen(["notepad.exe", filename])
    return {"status": "success"}
