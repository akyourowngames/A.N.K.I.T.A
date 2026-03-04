#!/usr/bin/env python3
"""
Apply remaining fixes to ANKITA orchestrator.py
Fixes: ContextAgent wiring + Dual Routing implementation
"""

import re

# Read the file
with open("agents/orchestrator.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix 1: Add ContextAgent call and dual routing to run() method
# Find the run method and insert the new code

old_pattern = r'''(    def run\(self, user_text: str, messages: List\[Dict\[str, Any\]\]\) -> str:
        """
        Full orchestration pipeline:
          Supervisor.*?\[Fan-Out specialist\(s\)\].*?Synthesizer.*?reply
        """
        # 1\. Supervisor routes the request
        # Generate an interaction ID for FeedbackEngine tracking
        _interaction_id: Optional\[str\] = None
        try:
            from tools\.feedback_engine import get_instance as _get_fb
            _fb_eng = _get_fb\(\)
            if _fb_eng is not None:
                _interaction_id = _fb_eng\.new_interaction\(\)
        except Exception:
            pass

        # Extract clean history for supervisor routing context
        supervisor_history = _extract_clean_history\(messages, max_turns=4\)
        routing = self\.supervisor\.route\(user_text, history=supervisor_history\)
        agent_names: List\[str\] = routing\["agents"\]
        parallel: bool = routing\["parallel"\]
        reasoning: str = routing\.get\("reasoning", ""\))'''

new_code = '''    def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:
        """
        Full orchestration pipeline:
          ContextAgent -> Supervisor -> [Fan-Out specialist(s)] -> Synthesizer -> reply
        """
        # 0. CONTEXT AGENT: Extract context from conversation history BEFORE routing
        context_block = None
        try:
            context_result = self.context_agent.extract(user_text, messages)
            if context_result and context_result.get("context_block"):
                context_block = context_result["context_block"]
                print(f"[ContextAgent] Extracted context: {context_block[:100]}...", flush=True)
        except Exception as ctx_err:
            print(f"[ContextAgent] Failed to extract context: {ctx_err}", flush=True)
        
        # 1. Supervisor routes the request
        # Generate an interaction ID for FeedbackEngine tracking
        _interaction_id: Optional[str] = None
        try:
            from tools.feedback_engine import get_instance as _get_fb
            _fb_eng = _get_fb()
            if _fb_eng is not None:
                _interaction_id = _fb_eng.new_interaction()
        except Exception:
            pass

        # Extract clean history for supervisor routing context
        supervisor_history = _extract_clean_history(messages, max_turns=4)
        
        # Inject context block into supervisor routing if available
        routing_text = user_text
        if context_block:
            routing_text = f"{context_block}\\n\\nUser request: {user_text}"
        
        routing = self.supervisor.route(routing_text, history=supervisor_history)
        agent_names: List[str] = routing["agents"]
        parallel: bool = routing["parallel"]
        reasoning: str = routing.get("reasoning", "")
        confidence: float = routing.get("confidence", 1.0)  # UPGRADE 13: Read confidence score
        
        # DUAL ROUTING PROTOCOL: If confidence < 0.65, run both primary and fallback
        if confidence < 0.65 and len(agent_names) == 1:
            primary = agent_names[0]
            fallback_map = {
                "FileAgent": "TerminalAgent",
                "WebAgent": "GeneralAgent",
                "SystemAgent": "TerminalAgent",
                "CodeAgent": "TerminalAgent",
                "MusicAgent": "GeneralAgent",
            }
            if primary in fallback_map:
                fallback_agent = fallback_map[primary]
                agent_names.append(fallback_agent)
                print(f"[DualRouting] Low confidence ({confidence:.2f}) - adding fallback: {fallback_agent}", flush=True)'''

# Apply the fix
content_new = re.sub(old_pattern, new_code, content, flags=re.DOTALL)

if content_new == content:
    print("❌ Pattern not found - trying simpler approach...")
    # Fallback: find and replace just the key lines
    lines = content.split('\n')
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Find the run method
        if 'def run(self, user_text: str, messages: List[Dict[str, Any]]) -> str:' in line:
            new_lines.append(line)
            i += 1
            # Add docstring
            while i < len(lines) and '"""' in lines[i]:
                # Update docstring
                if 'Supervisor' in lines[i] and 'Fan-Out' in lines[i]:
                    new_lines.append('          ContextAgent -> Supervisor -> [Fan-Out specialist(s)] -> Synthesizer -> reply')
                else:
                    new_lines.append(lines[i])
                i += 1
                if lines[i-1].strip().endswith('"""'):
                    break
            
            # Insert ContextAgent code
            new_lines.append('        # 0. CONTEXT AGENT: Extract context from conversation history BEFORE routing')
            new_lines.append('        context_block = None')
            new_lines.append('        try:')
            new_lines.append('            context_result = self.context_agent.extract(user_text, messages)')
            new_lines.append('            if context_result and context_result.get("context_block"):')
            new_lines.append('                context_block = context_result["context_block"]')
            new_lines.append('                print(f"[ContextAgent] Extracted context: {context_block[:100]}...", flush=True)')
            new_lines.append('        except Exception as ctx_err:')
            new_lines.append('            print(f"[ContextAgent] Failed to extract context: {ctx_err}", flush=True)')
            new_lines.append('        ')
            continue
        
        # Find supervisor routing section
        if 'supervisor_history = _extract_clean_history(messages, max_turns=4)' in line:
            new_lines.append(line)
            i += 1
            # Add context injection
            new_lines.append('        ')
            new_lines.append('        # Inject context block into supervisor routing if available')
            new_lines.append('        routing_text = user_text')
            new_lines.append('        if context_block:')
            new_lines.append('            routing_text = f"{context_block}\\n\\nUser request: {user_text}"')
            new_lines.append('        ')
            # Skip old routing line
            while i < len(lines) and 'routing = self.supervisor.route' not in lines[i]:
                new_lines.append(lines[i])
                i += 1
            # Add new routing line
            new_lines.append('        routing = self.supervisor.route(routing_text, history=supervisor_history)')
            i += 1
            continue
        
        # Find reasoning line and add confidence + dual routing
        if 'reasoning: str = routing.get("reasoning", "")' in line:
            new_lines.append(line)
            new_lines.append('        confidence: float = routing.get("confidence", 1.0)  # UPGRADE 13: Read confidence score')
            new_lines.append('        ')
            new_lines.append('        # DUAL ROUTING PROTOCOL: If confidence < 0.65, run both primary and fallback')
            new_lines.append('        if confidence < 0.65 and len(agent_names) == 1:')
            new_lines.append('            primary = agent_names[0]')
            new_lines.append('            fallback_map = {')
            new_lines.append('                "FileAgent": "TerminalAgent",')
            new_lines.append('                "WebAgent": "GeneralAgent",')
            new_lines.append('                "SystemAgent": "TerminalAgent",')
            new_lines.append('                "CodeAgent": "TerminalAgent",')
            new_lines.append('                "MusicAgent": "GeneralAgent",')
            new_lines.append('            }')
            new_lines.append('            if primary in fallback_map:')
            new_lines.append('                fallback_agent = fallback_map[primary]')
            new_lines.append('                agent_names.append(fallback_agent)')
            new_lines.append('                print(f"[DualRouting] Low confidence ({confidence:.2f}) - adding fallback: {fallback_agent}", flush=True)')
            i += 1
            continue
        
        new_lines.append(line)
        i += 1
    
    content_new = '\n'.join(new_lines)

# Write the fixed file
with open("agents/orchestrator.py", "w", encoding="utf-8") as f:
    f.write(content_new)

print("✅ Applied fixes to agents/orchestrator.py")
print("   - ContextAgent wiring")
print("   - Dual routing implementation")
