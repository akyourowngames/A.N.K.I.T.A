"""Fix the ContentAgent escalation entry"""

with open("agents/orchestrator.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the ContentAgent escalation entry
for i, line in enumerate(lines):
    if '"ContentAgent": ("GeneralAgent",' in line:
        # Replace the next 2 lines
        lines[i+1] = '                     "ContentAgent timed out or failed. Write a shorter, concise version of the requested content. "\n'
        lines[i+2] = '                     "Quality matters more than length here — produce something complete and usable. "\n'
        # Insert new lines
        lines.insert(i+3, '                     "IMPORTANT: After writing, call write_file to save it to Desktop as a .md file. "\n')
        lines.insert(i+4, '                     "Use a sensible filename based on the topic. "\n')
        lines.insert(i+5, '                     "Then call launch_app to open it. "\n')
        lines.insert(i+6, '                     "Do NOT just return text — save it."),\n')
        # Remove the old closing line
        del lines[i+7]
        
        with open("agents/orchestrator.py", "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"✅ Fixed ContentAgent escalation at line {i+1}")
        break
else:
    print("❌ Could not find ContentAgent escalation entry")
