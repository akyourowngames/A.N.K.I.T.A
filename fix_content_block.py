"""Fix the _build_prior_context_block function in orchestrator.py"""

with open("agents/orchestrator.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find and replace the ASSEMBLY LINE section
old_text = '''    # ASSEMBLY LINE: If ContentAgent has no file/url artifacts, embed the raw content
    # so FileAgent can read it from context and save it to disk.
    if agent_name == "ContentAgent" and not artifacts["files"] and reply.strip():
        import os as _os
        desktop = str(_os.path.join(_os.path.expanduser("~"), "Desktop"))
        lines.append(f"SAVE_TO: {desktop}")   # GPS Lock hint — FileAgent reads this
        lines.append(f"CONTENT:\\n{reply.strip()}\\n:END_CONTENT")'''

new_text = '''    # ASSEMBLY LINE: If ContentAgent has file artifacts (already saved by content_ops),
    # do NOT embed CONTENT: block. FileAgent should just open the existing file.
    # Only embed CONTENT: if ContentAgent returned text without saving it.
    if agent_name == "ContentAgent" and not artifacts["files"] and reply.strip():
        # Check if reply contains "already_saved" signal
        if "already_saved" not in reply.lower():
            import os as _os
            desktop = str(_os.path.join(_os.path.expanduser("~"), "Desktop"))
            lines.append(f"SAVE_TO: {desktop}")   # GPS Lock hint — FileAgent reads this
            lines.append(f"CONTENT:\\n{reply.strip()}\\n:END_CONTENT")'''

if old_text in content:
    content = content.replace(old_text, new_text)
    with open("agents/orchestrator.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ Fixed _build_prior_context_block in orchestrator.py")
else:
    print("❌ Could not find the text to replace")
    print("Searching for partial match...")
    if "ASSEMBLY LINE: If ContentAgent has no file/url artifacts" in content:
        print("Found partial match - text exists but format is different")
