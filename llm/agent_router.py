"""
Per-agent model routing system.

Allows specific agents (like CodeAgent) to use different models based on task complexity,
enabling cost-effective routing: fast models for simple tasks, reasoning models for complex tasks.
"""
import os
from dataclasses import replace
from typing import Optional

from .client import LLMRuntime, build_runtime_from_env


def _parse_bool_env(key: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    val = os.getenv(key, "").strip().lower()
    if val in ("true", "1", "yes", "on", "enabled"):
        return True
    if val in ("false", "0", "no", "off", "disabled"):
        return False
    return default


def get_agent_runtime(
    agent_name: str,
    base_runtime: LLMRuntime,
    task_complexity: Optional[str] = None,
) -> LLMRuntime:
    """
    Get specialized runtime for a specific agent based on task complexity.
    
    Args:
        agent_name: Name of the agent (e.g., "CodeAgent")
        base_runtime: Default runtime from environment
        task_complexity: Optional hint: "simple", "medium", "complex"
        
    Returns:
        LLMRuntime configured for this agent + task complexity, or base_runtime if routing disabled
        
    Example:
        # In .env:
        # CODEAGENT_ENABLE_ROUTING=true
        # CODEAGENT_MODEL_SIMPLE=llama-3.1-8b-instant
        # CODEAGENT_MODEL_COMPLEX=o1-preview
        
        runtime = get_agent_runtime("CodeAgent", base_runtime, "complex")
        # Returns runtime with model=o1-preview
    """
    # Only CodeAgent supports routing for now
    if agent_name != "CodeAgent":
        return base_runtime
    
    # Check if routing is enabled
    routing_enabled = _parse_bool_env("CODEAGENT_ENABLE_ROUTING", default=False)
    if not routing_enabled:
        return base_runtime
    
    # Determine which model to use based on complexity
    model_override = None
    
    if task_complexity == "simple":
        model_override = os.getenv("CODEAGENT_MODEL_SIMPLE", "").strip()
    elif task_complexity == "complex":
        model_override = os.getenv("CODEAGENT_MODEL_COMPLEX", "").strip()
    # "medium" or None falls through to base_runtime
    
    if not model_override:
        return base_runtime
    
    # Build new runtime with overridden model
    # Keep same provider, API key, base URL — only change model
    return replace(base_runtime, model=model_override)


def detect_task_complexity(task: str, agent_name: str = "") -> str:
    """
    Detect task complexity from task description.
    
    Args:
        task: The task string sent to the agent
        agent_name: Name of the agent (for agent-specific heuristics)
        
    Returns:
        "simple", "medium", or "complex"
        
    Heuristics for CodeAgent:
        - Simple: read, check syntax, run single command, list files
        - Complex: scaffold, refactor, review, multi-file, architecture, 3+ files mentioned
        - Medium: everything else
    """
    if agent_name != "CodeAgent":
        return "medium"
    
    task_lower = task.lower()
    
    # Simple task indicators
    simple_keywords = [
        "read file", "check syntax", "list files", "show me",
        "what's in", "display", "print", "run command",
    ]
    if any(kw in task_lower for kw in simple_keywords):
        # But not if it's part of a larger multi-step task
        if not any(word in task_lower for word in ["then", "after", "and also", "scaffold", "refactor"]):
            return "simple"
    
    # Complex task indicators
    complex_keywords = [
        "scaffold", "refactor", "architecture", "review code",
        "multi-file", "across files", "entire codebase",
        "explain the codebase", "design", "restructure",
    ]
    if any(kw in task_lower for kw in complex_keywords):
        return "complex"
    
    # Count file mentions (3+ files = complex)
    file_extensions = [".py", ".js", ".ts", ".go", ".java", ".cpp", ".c", ".rs", ".rb"]
    file_mention_count = sum(task_lower.count(ext) for ext in file_extensions)
    if file_mention_count >= 3:
        return "complex"
    
    # Default to medium
    return "medium"
