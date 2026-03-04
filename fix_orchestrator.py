"""Fix orchestrator.py by inserting PlannerAgent detection."""
with open("agents/orchestrator.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the line with "return self._run_general(user_text, messages)"
insert_after = None
for i, line in enumerate(lines):
    if "return self._run_general(user_text, messages)" in line and i < 800:
        insert_after = i
        break

if insert_after is None:
    print("Could not find insertion point")
    exit(1)

# Insert the new lines after the found line
new_lines = [
    "\n",
    "        # PLANNER AGENT: intercept and execute planned tasks\n",
    "        if agent_names == [\"PlannerAgent\"]:\n",
    "            return self._run_planned_task(user_text, messages)\n",
]

lines = lines[:insert_after+1] + new_lines + lines[insert_after+1:]

with open("agents/orchestrator.py", "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"✅ Inserted PlannerAgent detection after line {insert_after+1}")
