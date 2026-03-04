"""Fix the _build_prior_context_block function in orchestrator.py"""

with open("agents/orchestrator.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the line with "ASSEMBLY LINE: If ContentAgent has no file/url artifacts"
for i, line in enumerate(lines):
    if "ASSEMBLY LINE: If ContentAgent has no file/url artifacts" in line:
        # Replace the next 6 lines
        lines[i] = "    # ASSEMBLY LINE: If ContentAgent has file artifacts (already saved by content_ops),\n"
        lines[i+1] = "    # do NOT embed CONTENT: block. FileAgent should just open the existing file.\n"
        lines[i+2] = "    # Only embed CONTENT: if ContentAgent returned text without saving it.\n"
        lines[i+3] = '    if agent_name == "ContentAgent" and not artifacts["files"] and reply.strip():\n'
        lines[i+4] = '        # Check if reply contains "already_saved" signal\n'
        lines[i+5] = '        if "already_saved" not in reply.lower():\n'
        lines[i+6] = '            import os as _os\n'
        # Insert new lines
        lines.insert(i+7, '            desktop = str(_os.path.join(_os.path.expanduser("~"), "Desktop"))\n')
        lines.insert(i+8, '            lines.append(f"SAVE_TO: {desktop}")   # GPS Lock hint — FileAgent reads this\n')
        lines.insert(i+9, '            lines.append(f"CONTENT:\\n{reply.strip()}\\n:END_CONTENT")\n')
        
        # Remove the old lines that are now replaced
        del lines[i+10:i+12]
        
        with open("agents/orchestrator.py", "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"✅ Fixed _build_prior_context_block at line {i+1}")
        break
else:
    print("❌ Could not find the ASSEMBLY LINE section")
