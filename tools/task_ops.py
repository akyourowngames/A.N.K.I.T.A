"""
Task management operations for A.N.K.I.T.A.
Persistent to-do list with priorities, deadlines, and status tracking.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# Task storage location
TASK_FILE = Path.home() / ".ankita" / "tasks.json"


def task_op(
    action: str,
    title: Optional[str] = None,
    priority: str = "medium",
    deadline: Optional[str] = None,
    tags: Optional[List[str]] = None,
    status: str = "pending",
    task_id: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Task management operations.
    
    Actions:
    - add: Create a new task
    - list: Show all tasks (optionally filtered by status/priority)
    - update: Modify an existing task
    - complete: Mark task as done
    - delete: Remove a task
    - overdue: Show tasks past their deadline
    - summary: Get task statistics
    
    Args:
        action: The operation to perform
        title: Task description
        priority: low, medium, high, urgent
        deadline: Deadline in natural format (e.g., "Friday", "2024-12-25", "in 3 days")
        tags: List of tags for categorization
        status: pending, in_progress, done, cancelled
        task_id: Task ID for update/complete/delete operations
    
    Returns:
        Dict with status and result data
    """
    try:
        if action == "add":
            return _add_task(title, priority, deadline, tags, status)
        elif action == "list":
            return _list_tasks(status, priority)
        elif action == "update":
            return _update_task(task_id, title, priority, deadline, tags, status)
        elif action == "complete":
            return _complete_task(task_id or title)
        elif action == "delete":
            return _delete_task(task_id or title)
        elif action == "overdue":
            return _get_overdue_tasks()
        elif action == "summary":
            return _get_summary()
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}
    
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _load_tasks() -> List[Dict[str, Any]]:
    """Load tasks from storage."""
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if not TASK_FILE.exists():
        return []
    
    try:
        with open(TASK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def _save_tasks(tasks: List[Dict[str, Any]]) -> None:
    """Save tasks to storage."""
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)


def _parse_deadline(deadline_str: str) -> Optional[str]:
    """Parse natural language deadline to ISO format."""
    if not deadline_str:
        return None
    
    deadline_str = deadline_str.lower().strip()
    now = datetime.now()
    
    # Try ISO format first
    try:
        dt = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        pass
    
    # Relative dates
    if "today" in deadline_str:
        return now.strftime("%Y-%m-%d 23:59")
    elif "tomorrow" in deadline_str:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d 23:59")
    elif "in" in deadline_str and "day" in deadline_str:
        try:
            days = int(''.join(filter(str.isdigit, deadline_str)))
            return (now + timedelta(days=days)).strftime("%Y-%m-%d 23:59")
        except:
            pass
    elif "in" in deadline_str and "hour" in deadline_str:
        try:
            hours = int(''.join(filter(str.isdigit, deadline_str)))
            return (now + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        except:
            pass
    
    # Day names
    days_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for day_name, day_num in days_map.items():
        if day_name in deadline_str:
            current_day = now.weekday()
            days_ahead = (day_num - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week
            target = now + timedelta(days=days_ahead)
            return target.strftime("%Y-%m-%d 23:59")
    
    # Try simple date formats
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"]:
        try:
            dt = datetime.strptime(deadline_str, fmt)
            return dt.strftime("%Y-%m-%d 23:59")
        except:
            continue
    
    return None


def _generate_task_id(tasks: List[Dict[str, Any]]) -> str:
    """Generate a unique task ID."""
    if not tasks:
        return "T001"
    
    max_id = max(int(t["id"][1:]) for t in tasks if t["id"].startswith("T"))
    return f"T{max_id + 1:03d}"


def _add_task(title: str, priority: str, deadline: Optional[str], tags: Optional[List[str]], status: str) -> Dict[str, Any]:
    """Add a new task."""
    if not title:
        return {"status": "error", "error": "Task title required"}
    
    tasks = _load_tasks()
    
    task = {
        "id": _generate_task_id(tasks),
        "title": title,
        "priority": priority.lower(),
        "deadline": _parse_deadline(deadline) if deadline else None,
        "tags": tags or [],
        "status": status.lower(),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "completed": None
    }
    
    tasks.append(task)
    _save_tasks(tasks)
    
    # Auto-schedule cron reminder if deadline is set
    reminder_info = None
    if task["deadline"] and os.getenv("TASK_AGENT_USE_CORN", "true").lower() == "true":
        try:
            from tools.cron_ops import cron
            # Schedule reminder 30 minutes before deadline
            deadline_dt = datetime.strptime(task["deadline"], "%Y-%m-%d %H:%M")
            reminder_dt = deadline_dt - timedelta(minutes=30)
            
            if reminder_dt > datetime.now():
                cron_result = cron(
                    action="add",
                    job={
                        "schedule": reminder_dt.strftime("%Y-%m-%d %H:%M"),
                        "task": f"Reminder: Task '{title}' is due in 30 minutes!",
                        "repeat": "once"
                    }
                )
                if cron_result.get("status") == "success":
                    reminder_info = f"Reminder scheduled for {reminder_dt.strftime('%Y-%m-%d %H:%M')}"
        except:
            pass
    
    return {
        "status": "success",
        "task": task,
        "message": f"Task {task['id']} created: {title}",
        "reminder": reminder_info
    }


def _list_tasks(status_filter: Optional[str] = None, priority_filter: Optional[str] = None) -> Dict[str, Any]:
    """List all tasks with optional filters."""
    tasks = _load_tasks()
    
    if status_filter:
        tasks = [t for t in tasks if t["status"] == status_filter.lower()]
    
    if priority_filter:
        tasks = [t for t in tasks if t["priority"] == priority_filter.lower()]
    
    # Sort by priority (urgent > high > medium > low) then by deadline
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    tasks.sort(key=lambda t: (
        priority_order.get(t["priority"], 4),
        t["deadline"] or "9999-99-99"
    ))
    
    return {
        "status": "success",
        "tasks": tasks,
        "count": len(tasks)
    }


def _update_task(task_id: str, title: Optional[str], priority: Optional[str], 
                 deadline: Optional[str], tags: Optional[List[str]], status: Optional[str]) -> Dict[str, Any]:
    """Update an existing task."""
    if not task_id:
        return {"status": "error", "error": "Task ID required"}
    
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    
    if not task:
        return {"status": "error", "error": f"Task {task_id} not found"}
    
    if title:
        task["title"] = title
    if priority:
        task["priority"] = priority.lower()
    if deadline:
        task["deadline"] = _parse_deadline(deadline)
    if tags is not None:
        task["tags"] = tags
    if status:
        task["status"] = status.lower()
        if status.lower() == "done" and not task.get("completed"):
            task["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    _save_tasks(tasks)
    
    return {
        "status": "success",
        "task": task,
        "message": f"Task {task_id} updated"
    }


def _complete_task(identifier: str) -> Dict[str, Any]:
    """Mark a task as complete."""
    if not identifier:
        return {"status": "error", "error": "Task ID or title required"}
    
    tasks = _load_tasks()
    
    # Find by ID or title
    task = next((t for t in tasks if t["id"] == identifier or t["title"].lower() == identifier.lower()), None)
    
    if not task:
        return {"status": "error", "error": f"Task not found: {identifier}"}
    
    task["status"] = "done"
    task["completed"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    _save_tasks(tasks)
    
    return {
        "status": "success",
        "task": task,
        "message": f"Task {task['id']} marked as complete: {task['title']}"
    }


def _delete_task(identifier: str) -> Dict[str, Any]:
    """Delete a task."""
    if not identifier:
        return {"status": "error", "error": "Task ID or title required"}
    
    tasks = _load_tasks()
    
    # Find by ID or title
    task = next((t for t in tasks if t["id"] == identifier or t["title"].lower() == identifier.lower()), None)
    
    if not task:
        return {"status": "error", "error": f"Task not found: {identifier}"}
    
    tasks.remove(task)
    _save_tasks(tasks)
    
    return {
        "status": "success",
        "message": f"Task {task['id']} deleted: {task['title']}"
    }


def _get_overdue_tasks() -> Dict[str, Any]:
    """Get all overdue tasks."""
    tasks = _load_tasks()
    now = datetime.now()
    
    overdue = []
    for task in tasks:
        if task["status"] in ("pending", "in_progress") and task.get("deadline"):
            try:
                deadline_dt = datetime.strptime(task["deadline"], "%Y-%m-%d %H:%M")
                if deadline_dt < now:
                    days_overdue = (now - deadline_dt).days
                    task["days_overdue"] = days_overdue
                    overdue.append(task)
            except:
                pass
    
    overdue.sort(key=lambda t: t.get("days_overdue", 0), reverse=True)
    
    return {
        "status": "success",
        "tasks": overdue,
        "count": len(overdue)
    }


def _get_summary() -> Dict[str, Any]:
    """Get task statistics."""
    tasks = _load_tasks()
    
    total = len(tasks)
    by_status = {}
    by_priority = {}
    
    for task in tasks:
        status = task["status"]
        priority = task["priority"]
        
        by_status[status] = by_status.get(status, 0) + 1
        by_priority[priority] = by_priority.get(priority, 0) + 1
    
    overdue_count = len(_get_overdue_tasks()["tasks"])
    
    return {
        "status": "success",
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "overdue": overdue_count
    }
