#!/usr/bin/env python3
"""
Simple chatbot using GitHub Copilot with web authentication and smart memory
"""

import json
import time
import sys
import os
import importlib
from pathlib import Path
from typing import Dict, List
import requests
from dotenv import load_dotenv
from llm_provider import build_provider_from_env
from memory_system import MemorySystem
from tools.tool_registry import ToolRegistry
from retry_config import RetryConfig
from skills.skill_system import SkillSystem

# Load environment variables
load_dotenv()

# Windows PowerShell often defaults to cp1252, which breaks the emoji-heavy UI.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class CopilotChatbot:
    """Simple chatbot interface for selectable LLM providers with memory and tools"""
    
    def __init__(self):
        self.provider = build_provider_from_env()
        self.conversation_history = []
        self.memory = MemorySystem()
        self.tool_registry = ToolRegistry()
        self.retry_config = RetryConfig()
        self.skill_system = SkillSystem()
        self.last_setup_error = ""
    
    def setup(self):
        """Setup authentication and personality"""
        self.last_setup_error = ""

        try:
            # Check personality configuration
            self._check_personality()
            self._maybe_start_browser_bridge()
            
            if self.provider.load_token():
                print(f"✅ Loaded existing {self.provider.provider_name} credentials")
                if self.test_connection():
                    # Show available skills on startup
                    skills = self.skill_system.list_skills()
                    if skills:
                        print(f"🎯 Loaded {len(skills)} skills")
                    return True
                else:
                    print(f"⚠️  {self.provider.provider_name} credentials failed, re-authenticating...")
            
            authenticated = self.provider.authenticate()
            if not authenticated:
                self.last_setup_error = f"{self.provider.provider_name} login did not complete successfully"
                return False

            return self.test_connection()
        except Exception as e:
            self.last_setup_error = str(e)
            print(f"❌ Setup error: {e}")
            return False

    def _maybe_start_browser_bridge(self):
        """Start the localhost browser bridge when configured."""
        autostart = os.getenv("BROWSER_BRIDGE_AUTOSTART", "").strip().lower() in {"1", "true", "yes", "on"}
        if not autostart:
            return

        try:
            from browser_bridge import BrowserBridgeManager

            manager = BrowserBridgeManager.ensure_running()
            print(f"🌐 Browser bridge ready at http://{manager.host}:{manager.port}")
        except Exception as exc:
            print(f"⚠️  Browser bridge did not start: {exc}")
    
    def _check_personality(self):
        """Check if personality is configured, run setup if not"""
        from pathlib import Path
        soul_file = Path("memory/SOUL.md")
        
        if not soul_file.exists() or "Configuration Status: Complete" not in soul_file.read_text(encoding='utf-8'):
            print("\n🌟 First time setup detected!")
            print("Let's configure ANKITA's personality...\n")
            
            from personality_setup import PersonalitySetup
            setup = PersonalitySetup()
            setup.run_setup()
    
    def test_connection(self):
        """Test if the token works"""
        ok, message = self.provider.test_connection()
        if ok:
            self.last_setup_error = ""
            print(f"✅ {message}")
            print(f"🔧 Provider: {self.provider.provider_name} | Model: {self.provider.model}")
            print(f"🔧 Loaded {len(self.tool_registry.get_tool_names())} tools")
            return True
        self.last_setup_error = message
        print(f"❌ {message}")
        return False
    
    def get_memory_tools(self):
        """Define memory tools for function calling"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "remember_preference",
                    "description": "Store user's personal information and preferences (name, likes/dislikes, location, etc.) to preferences file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["name", "age", "gender", "preference", "location", "project", "communication", "fact"],
                                "description": "Category of information being stored"
                            },
                            "content": {
                                "type": "string",
                                "description": "The information to remember"
                            }
                        },
                        "required": ["category", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "add_to_long_term_memory",
                    "description": "Store important facts, decisions, or context to long-term memory (MEMORY.md). Use this for significant information that should be remembered long-term.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["Important Facts", "Ongoing Projects", "Decisions & Patterns", "Goals", "Notes"],
                                "description": "Which section to add this to in long-term memory"
                            },
                            "content": {
                                "type": "string",
                                "description": "The information to store in long-term memory"
                            }
                        },
                        "required": ["category", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_memory",
                    "description": "Search through stored persistent memory for specific information. Conversation logs are excluded unless explicitly requested.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for in memory"
                            },
                            "include_logs": {
                                "type": "boolean",
                                "description": "Whether to also search recent conversation logs",
                                "default": False
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_skill",
                    "description": "Create a new custom skill (workflow that combines multiple tools). Use this when user wants to automate a task or create a custom workflow.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "Name of the skill (lowercase with hyphens, e.g., 'weather-check')"
                            },
                            "description": {
                                "type": "string",
                                "description": "One-line description of what the skill does"
                            },
                            "trigger": {
                                "type": "string",
                                "description": "Comma-separated keywords that trigger this skill (e.g., 'weather, forecast, temperature')"
                            },
                            "steps": {
                                "type": "string",
                                "description": "Step-by-step instructions for executing this skill (numbered list)"
                            },
                            "rules": {
                                "type": "string",
                                "description": "Rules and constraints for this skill (optional)"
                            },
                            "location": {
                                "type": "string",
                                "enum": ["workspace", "user", "bundled"],
                                "description": "Where to save the skill (workspace=project-specific, user=personal, bundled=default)"
                            }
                        },
                        "required": ["skill_name", "description", "trigger", "steps"]
                    }
                }
            }
        ]
    
    def get_all_tools(self):
        """Get all available tools (memory + system tools)"""
        tools = self.get_memory_tools()
        tools.extend(self.tool_registry.get_all_schemas())
        return tools
    
    def execute_tool_with_retry(self, tool_name: str, arguments: dict) -> tuple[str, bool]:
        """
        Execute a tool with retry logic (OpenClaw-style)
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
        
        Returns:
            Tuple of (result, success)
        """
        for attempt in range(self.retry_config.MAX_RETRIES + 1):
            try:
                # Execute the tool
                result = self.execute_tool(tool_name, arguments)
                
                # Check if result indicates an error
                if result.startswith("Error:"):
                    raise Exception(result)
                
                # Success!
                if attempt > 0:
                    print(f"  ✓ Tool succeeded on attempt {attempt + 1}")
                return (result, True)
            
            except Exception as e:
                # Check if we should retry
                if attempt < self.retry_config.MAX_RETRIES and self.retry_config.should_retry(attempt, e):
                    delay = self.retry_config.calculate_delay(attempt)
                    print(f"  ⚠️  Tool failed (attempt {attempt + 1}/{self.retry_config.MAX_RETRIES + 1}): {str(e)}")
                    print(f"  ⏳ Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    # Max retries reached or non-retryable error
                    error_msg = f"Tool execution failed after {attempt + 1} attempts: {str(e)}"
                    print(f"  ❌ {error_msg}")
                    return (error_msg, False)
        
        return ("Max retries exceeded", False)
    
    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool (memory or system tool)"""
        # Memory tools
        if tool_name == "remember_preference":
            category = arguments.get("category", "fact")
            content = str(arguments.get("content", "")).strip()
            if not content:
                return "Error: content is required for remember_preference"
            
            # Map category to preference format
            if category == "name":
                formatted = f"User's name: {content}"
            elif category == "age":
                formatted = f"Age: {content}"
            elif category == "gender":
                formatted = f"Gender: {content}"
            elif category == "preference":
                formatted = f"Preference: {content}"
            elif category == "location":
                formatted = f"Location: {content}"
            elif category == "project":
                formatted = f"Project: {content}"
            elif category == "communication":
                formatted = f"Communication preference: {content}"
            else:
                formatted = content
            
            # Save to preferences
            self.memory._append_to_preferences([(category, formatted)])
            return f"✓ Saved to preferences: {formatted}"
        
        elif tool_name == "add_to_long_term_memory":
            category = arguments.get("category", "Important Facts")
            content = str(arguments.get("content", "")).strip()
            if not content:
                return "Error: content is required for add_to_long_term_memory"
            
            # Save to long-term memory
            success = self.memory.add_to_memory(category, content)
            if not success:
                return "Error: long-term memory content cannot be empty"
            return f"✓ Added to long-term memory ({category}): {content}"
        
        elif tool_name == "search_memory":
            query = arguments.get("query", "")
            include_logs = bool(arguments.get("include_logs", False))
            results = self.memory.search_memory(query, include_logs=include_logs)
            if results:
                return "\n".join(results[:5])
            return "No results found"
        
        elif tool_name == "create_skill":
            skill_name = arguments.get("skill_name", "")
            description = arguments.get("description", "")
            trigger = arguments.get("trigger", "")
            steps = arguments.get("steps", "")
            rules = arguments.get("rules", "")
            location = arguments.get("location", "workspace")
            
            success = self.skill_system.create_skill(
                skill_name, description, trigger, steps, rules, location
            )
            
            if success:
                return f"✓ Created skill '{skill_name}' in {location} skills. Trigger keywords: {trigger}"
            else:
                return f"✗ Failed to create skill '{skill_name}'"
        
        # System tools from registry
        else:
            return self.tool_registry.execute_tool(tool_name, arguments)

    def _build_system_content(self, memory_context: str, skills_summary: str,
                              active_skill_instructions: str,
                              runtime_mode_instructions: str = "") -> str:
        """Build the shared ANKITA system prompt used across providers."""
        system_content_parts = [
            "You are ANKITA, the user's local assistant inside this workspace.",
            "Do not present yourself as Codex, ChatGPT, or a generic AI assistant unless the user explicitly asks about the underlying provider.",
            "Act like ANKITA: capable, proactive, natural, and action-oriented.",
            "Follow the configured personality in memory/SOUL.md when it is present.",
            "When a user asks for an action, prefer doing it with ANKITA's local tools instead of only describing steps."
        ]

        system_content_parts.append(
            "\nCAPABILITIES:\n"
            "- Memory tools: remember_preference, add_to_long_term_memory, search_memory, create_skill\n"
            "- Local system tools: execute_terminal_command, file_operation, gui_control, window_clipboard\n"
            "- Browser automation: browser_automation for sessions, DOM steps, extraction, screenshots, and uploads\n"
            "- Web tools: search_web, fetch_webpage\n"
            "- If the user asks what you can access, answer with these ANKITA capabilities, not generic platform claims"
        )

        system_content_parts.append(
            "\nACTION POLICY:\n"
            "- If the user asks to open an app, run a command, inspect files, search the web, or control windows, do it first when possible\n"
            "- Use browser_automation for website and browser DOM tasks; use gui_control/window_clipboard only for browser chrome, native dialogs, or desktop fallbacks\n"
            "- For browser workflows, stop as soon as the requested checkpoint or page state is reached and report the result instead of idling or over-exploring\n"
            "- Do not say you lack tools if ANKITA already has the needed capability\n"
            "- Do not tell the user to do the obvious next step themselves when ANKITA can do it"
        )

        system_content_parts.append(
            "\nKNOWLEDGE GAPS:\n"
            "- If you don't know something or lack current information, use 'search_web' tool FIRST\n"
            "- Never say 'I don't know' without attempting to search\n"
            "- Search for: current events, recent updates, unfamiliar terms, specific facts\n"
            "- After searching, synthesize the information in your response"
        )

        system_content_parts.append(
            "\nMEMORY SYSTEM:\n"
            "- Use 'remember_preference' for personal info (name, likes, location, etc.)\n"
            "- Use 'add_to_long_term_memory' for important facts, decisions, or context that should persist\n"
            "- When user shares something important, ALWAYS call the appropriate memory function\n"
            "- If asked whether something was saved, verify against persisted memory, not just chat history"
        )

        if skills_summary:
            system_content_parts.append(f"\n{skills_summary}")
            system_content_parts.append(
                "\nWhen a skill is activated, follow its instructions precisely. "
                "Skills combine multiple tools into workflows."
            )

        if active_skill_instructions:
            system_content_parts.append(active_skill_instructions)

        if runtime_mode_instructions:
            system_content_parts.append(runtime_mode_instructions)

        if memory_context:
            system_content_parts.append(f"\nHere's what you currently know about the user:\n{memory_context}")

        return "\n".join(system_content_parts)

    def _get_runtime_mode_instructions(self, user_message: str) -> str:
        """Inject high-priority behavior modes inferred from the latest user turn."""
        lowered = (user_message or "").lower()
        testing_markers = [
            "for testing",
            "testing",
            "test flow",
            "test mode",
            "dummy",
            "fake",
            "random",
            "simulate",
            "simulation",
            "dry run",
        ]

        if any(marker in lowered for marker in testing_markers):
            return (
                "\nTEST / SIMULATION MODE:\n"
                "- The user has indicated this task may use dummy, random, simulated, or test data.\n"
                "- You may generate realistic placeholder details when needed to keep the workflow moving.\n"
                "- Prefer doing the test flow instead of stopping for non-essential confirmations.\n"
                "- Never submit payment, finalize a purchase, or perform irreversible external actions with invented details.\n"
                "- If a real action cannot be completed safely, do the booking-ready or form-fill simulation and clearly state what was simulated."
            )

        return ""

    def _build_codex_cli_tool_guide(self) -> str:
        """Tell the Codex CLI path how to reach ANKITA's local Python tools."""
        return (
            "CODEX CLI TOOL BRIDGE:\n"
            "- To use ANKITA's local tools, run: python ankita_codex_bridge.py <tool_name> '<json arguments>'\n"
            "- Available tool names: remember_preference, add_to_long_term_memory, search_memory, create_skill, "
            "execute_terminal_command, search_web, fetch_webpage, file_operation, gui_control, window_clipboard, browser_automation\n"
            "- Example: python ankita_codex_bridge.py execute_terminal_command '{\"command\":\"notepad\"}'\n"
            "- Example: python ankita_codex_bridge.py window_clipboard '{\"action\":\"switch_to_window\",\"process\":\"notepad\"}'\n"
            "- Example: python ankita_codex_bridge.py browser_automation '{\"action\":\"start_session\",\"browser\":\"edge\",\"url\":\"https://example.com\"}'\n"
            "- Example: python ankita_codex_bridge.py search_web '{\"query\":\"latest OpenAI news\"}'\n"
            "- If the user's request needs an action, run the bridge command first and then answer with the outcome.\n"
            "- Do not merely describe the bridge command unless the user specifically asks how it works."
        )

    def _build_codex_cli_prompt(self, system_content: str) -> str:
        """Build the Codex CLI prompt with ANKITA context, memory, and tool guidance."""
        transcript_lines = []
        for message in self.conversation_history[-10:]:
            role = str(message.get("role", "")).strip().lower()
            content = str(message.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            transcript_lines.append(f"{role.title()}: {content}")

        parts = [
            system_content,
            "",
            self._build_codex_cli_tool_guide(),
            "",
            "RECENT CONVERSATION:",
            "\n".join(transcript_lines) if transcript_lines else "No prior conversation.",
            "",
            "Respond as ANKITA. Use ANKITA's local tools when the latest user request requires action.",
        ]

        return "\n".join(parts).strip()
    
    def chat(self, user_message):
        """Send a message and get response with function calling"""
        # Log user message
        self.memory.log_conversation('user', user_message)

        # Persist obvious user preferences before the model responds so memory claims are real.
        self.memory.extract_and_save_preferences(user_message, "")
        
        # Add user message to history
        self.conversation_history.append({
            'role': 'user',
            'content': user_message
        })
        
        # Get memory context for system message
        memory_context = self.memory.get_memory_context()
        
        # Get skills summary (hot-reload on every prompt - OpenClaw style)
        skills_summary = self.skill_system.get_skills_summary()
        
        # Check if user message matches a skill trigger
        skill_match = self.skill_system.match_skill(user_message)
        active_skill_instructions = ""
        if skill_match:
            skill_name, skill_instructions = skill_match
            active_skill_instructions = f"\n\n🎯 ACTIVE SKILL: {skill_name}\n{skill_instructions}"
            print(f"\n🎯 Activated skill: {skill_name}")

        runtime_mode_instructions = self._get_runtime_mode_instructions(user_message)
        
        system_content = self._build_system_content(
            memory_context=memory_context,
            skills_summary=skills_summary,
            active_skill_instructions=active_skill_instructions,
            runtime_mode_instructions=runtime_mode_instructions
        )

        # Prepare messages with memory context and skills
        messages = []
        messages.append({
            'role': 'system',
            'content': system_content
        })
        messages.extend(self.conversation_history)

        if self.provider.provider_name == 'codex_cli':
            try:
                prompt = self._build_codex_cli_prompt(system_content)
                content = self.provider.run_cli_prompt(prompt, cwd=str(Path.cwd()))
            except Exception as e:
                return f"Error: {str(e)}"

            self.memory.log_conversation('assistant', content)
            self.conversation_history.append({
                'role': 'assistant',
                'content': content
            })
            return content
        
        # Prepare request with function calling
        payload = {
            'model': self.provider.model,
            'messages': messages,
            'tools': self.get_all_tools(),
            'tool_choice': 'auto',
            'temperature': 0.7,
            'max_tokens': 2000
        }
        
        try:
            response = requests.post(
                self.provider.api_url,
                headers=self.provider.get_headers(),
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                return f"Error: API returned status {response.status_code}\n{response.text}"
            
            data = response.json()
            assistant_message = data['choices'][0]['message']
            
            # Check if tool calls were made
            tool_calls = assistant_message.get('tool_calls', [])
            
            if tool_calls:
                # CRITICAL: Add the full assistant message (with tool_calls) to history first
                self.conversation_history.append({
                    'role': 'assistant',
                    'content': assistant_message.get('content'),
                    'tool_calls': tool_calls
                })
                
                # Execute each tool call with retry logic
                for tool_call in tool_calls:
                    tool_name = tool_call['function']['name']
                    arguments = json.loads(tool_call['function']['arguments'])
                    
                    print(f"\n🔧 Executing tool: {tool_name}")
                    
                    # Execute with retry (OpenClaw-style: tool MUST succeed before responding)
                    result, success = self.execute_tool_with_retry(tool_name, arguments)
                    
                    # Add tool result to conversation
                    self.conversation_history.append({
                        'role': 'tool',
                        'tool_call_id': tool_call['id'],
                        'name': tool_name,
                        'content': result
                    })
                
                updated_memory_context = self.memory.get_memory_context()
                updated_skills_summary = self.skill_system.get_skills_summary()
                updated_system_content = self._build_system_content(
                    memory_context=updated_memory_context,
                    skills_summary=updated_skills_summary,
                    active_skill_instructions=active_skill_instructions,
                    runtime_mode_instructions=runtime_mode_instructions
                )

                # Build complete message history for second request
                # Include system message + all conversation history
                complete_messages = []
                if updated_system_content:
                    complete_messages.append({
                        'role': 'system',
                        'content': updated_system_content
                    })
                complete_messages.extend(self.conversation_history)
                
                # Get final response after tool execution
                final_payload = {
                    'model': self.provider.model,
                    'messages': complete_messages,
                    'tools': self.get_all_tools(),
                    'temperature': 0.7,
                    'max_tokens': 2000
                }
                
                final_response = requests.post(
                    self.provider.api_url,
                    headers=self.provider.get_headers(),
                    json=final_payload,
                    timeout=30
                )
                
                if final_response.status_code == 200:
                    final_data = final_response.json()
                    final_message = final_data['choices'][0]['message']['content']
                    
                    # Log and add to history
                    self.memory.log_conversation('assistant', final_message)
                    self.conversation_history.append({
                        'role': 'assistant',
                        'content': final_message
                    })
                    return final_message
                else:
                    error_text = final_response.text
                    return f"Error getting final response: {final_response.status_code}\n{error_text}"
            
            # No tool calls, just return the message
            content = assistant_message.get('content', '')
            self.memory.log_conversation('assistant', content)
            self.conversation_history.append({
                'role': 'assistant',
                'content': content
            })
            return content
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    def reload_modules(self):
        """Hot reload all modules without restarting"""
        print("\n🔄 Reloading modules...")
        
        try:
            # Reload environment variables
            from dotenv import load_dotenv
            load_dotenv(override=True)
            print("  ✓ Reloaded environment variables")
            
            # List of modules to reload
            modules_to_reload = [
                'copilot_auth',
                'llm_provider',
                'memory_system',
                'retry_config',
                'tools.tool_registry',
                'tools.terminal_tool',
                'tools.web_search_tool',
                'tools.web_fetch_tool',
                'tools.file_operations_tool',
                'tools.gui_automation_tool',
                'tools.window_clipboard_tool'
            ]
            
            # Reload each module
            for module_name in modules_to_reload:
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                    print(f"  ✓ Reloaded {module_name}")
            
            # Reinitialize components with reloaded modules
            from llm_provider import build_provider_from_env
            from memory_system import MemorySystem
            from tools.tool_registry import ToolRegistry
            from retry_config import RetryConfig
            from skills.skill_system import SkillSystem
            
            # Keep conversation history but reload everything else
            old_history = self.conversation_history
            
            self.provider = build_provider_from_env()
            self.memory = MemorySystem()
            self.tool_registry = ToolRegistry()
            self.retry_config = RetryConfig()
            self.skill_system = SkillSystem()
            self.conversation_history = old_history
            
            print(f"✅ Reload complete! {len(self.tool_registry.get_tool_names())} tools loaded\n")
            return True
        
        except Exception as e:
            print(f"❌ Reload failed: {e}\n")
            return False
    
    def run(self):
        """Run interactive chat loop"""
        print("\n" + "=" * 60)
        print("🤖 ANKITA Chatbot with Memory")
        print("=" * 60)
        print("\nCommands:")
        print("  /clear   - Clear conversation history")
        print("  /reload  - Hot reload all modules")
        print("  /memory  - Show memory stats")
        print("  /search  - Search memory")
        print("  /skills  - List available skills")
        print("  /thinking - Show or set Codex thinking level")
        print("  /quit    - Exit chatbot")
        print("  /help    - Show this help")
        print("\n" + "=" * 60 + "\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.startswith('/'):
                    if user_input == '/quit':
                        print("\n👋 Goodbye!")
                        break
                    elif user_input == '/clear':
                        self.clear_history()
                        continue
                    elif user_input == '/reload':
                        self.reload_modules()
                        continue
                    elif user_input == '/memory':
                        self._show_memory_stats()
                        continue
                    elif user_input.startswith('/search '):
                        query = user_input[8:].strip()
                        self._search_memory(query)
                        continue
                    elif user_input == '/skills':
                        self._show_skills()
                        continue
                    elif user_input == '/thinking' or user_input.startswith('/thinking '):
                        self._handle_thinking_command(user_input)
                        continue
                    elif user_input == '/help':
                        print("\nCommands:")
                        print("  /clear   - Clear conversation history")
                        print("  /reload  - Hot reload all modules")
                        print("  /memory  - Show memory stats")
                        print("  /search  - Search memory")
                        print("  /skills  - List available skills")
                        print("  /thinking - Show or set Codex thinking level")
                        print("  /quit    - Exit chatbot")
                        print("  /help    - Show this help\n")
                        continue
                    else:
                        print(f"Unknown command: {user_input}\n")
                        continue
                
                # Get response
                print("\n🤖 Assistant: ", end='', flush=True)
                response = self.chat(user_input)
                print(response + "\n")
            
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}\n")
    
    def _show_memory_stats(self):
        """Show memory system statistics"""
        print("\n📊 Memory Statistics:")
        print(f"  Memory directory: {self.memory.memory_dir}")
        
        # Count daily logs
        daily_logs = list(self.memory.daily_dir.glob("*.jsonl"))
        print(f"  Daily logs: {len(daily_logs)} files")
        
        # Show today's log size
        today_log = self.memory.get_today_log_file()
        if today_log.exists():
            with open(today_log, 'r') as f:
                lines = len(f.readlines())
            print(f"  Today's messages: {lines}")
        
        # Show memory files
        print(f"  Long-term memory: {self.memory.memory_file.exists()}")
        print(f"  Preferences: {self.memory.preferences_file.exists()}")
        print()
    
    def _search_memory(self, query: str):
        """Search memory and display results"""
        if not query:
            print("❌ Please provide a search query\n")
            return
        
        print(f"\n🔍 Searching for: {query}")
        results = self.memory.search_memory(query)
        
        if results:
            print(f"Found {len(results)} results:\n")
            for i, result in enumerate(results, 1):
                print(f"{i}. {result}")
        else:
            print("No results found")
        print()
    
    def _show_skills(self):
        """Show available skills"""
        skills = self.skill_system.list_skills()
        
        if not skills:
            print("\n📋 No skills available yet. Create one with 'create a skill for...'")
            return
        
        print(f"\n📋 Available Skills ({len(skills)}):\n")
        for skill in skills:
            print(f"  🎯 {skill['name']}")
            print(f"     {skill['description']}")
            print(f"     Triggers: {skill.get('trigger', 'N/A')}")
            print(f"     Source: {skill['source']}")
            print()
        print()

    def _persist_env_setting(self, key: str, value: str) -> None:
        """Persist a simple key=value pair in the local .env file."""
        env_path = Path(".env")
        line = f"{key}={value}"

        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            updated = False
            for index, existing in enumerate(lines):
                if existing.startswith(f"{key}="):
                    lines[index] = line
                    updated = True
                    break
            if not updated:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(line)
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            env_path.write_text(line + "\n", encoding="utf-8")

    def _handle_thinking_command(self, user_input: str) -> None:
        """Show or update the Codex reasoning effort."""
        current_level = self.provider.get_reasoning_effort()
        if current_level is None:
            print("\n❌ Thinking level is only available for the Codex CLI provider.\n")
            return

        parts = user_input.split(maxsplit=1)
        if len(parts) == 1:
            print(f"\n🧠 Thinking level: {current_level}")
            print("   Available levels: low, medium, high, xhigh\n")
            return

        requested_level = parts[1].strip().lower()
        if not self.provider.set_reasoning_effort(requested_level):
            print("\n❌ Invalid thinking level. Use: low, medium, high, xhigh\n")
            return

        os.environ["CODEX_REASONING_EFFORT"] = requested_level
        self._persist_env_setting("CODEX_REASONING_EFFORT", requested_level)
        print(f"\n🧠 Thinking level set to: {requested_level}\n")


if __name__ == '__main__':
    bot = CopilotChatbot()
    
    if bot.setup():
        bot.run()
    else:
        print(f"❌ {bot.last_setup_error or 'Authentication failed'}")
