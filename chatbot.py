#!/usr/bin/env python3
"""
Simple chatbot using GitHub Copilot with web authentication and smart memory
"""

import json
import time
import sys
import os
import importlib
import requests
from dotenv import load_dotenv
from copilot_auth import CopilotAuth
from memory_system import MemorySystem
from tools.tool_registry import ToolRegistry
from retry_config import RetryConfig
from skills.skill_system import SkillSystem

# Load environment variables
load_dotenv()


class CopilotChatbot:
    """Simple chatbot interface for GitHub Copilot with memory and tools"""
    
    API_URL = 'https://api.githubcopilot.com/chat/completions'
    
    def __init__(self):
        self.auth = CopilotAuth()
        self.conversation_history = []
        self.memory = MemorySystem()
        self.tool_registry = ToolRegistry()
        self.retry_config = RetryConfig()
        self.skill_system = SkillSystem()
    
    def setup(self):
        """Setup authentication and personality"""
        # Check personality configuration
        self._check_personality()
        
        if self.auth.load_token():
            print("✅ Loaded existing credentials")
            if self.test_connection():
                # Show available skills on startup
                skills = self.skill_system.list_skills()
                if skills:
                    print(f"🎯 Loaded {len(skills)} skills")
                return True
            else:
                print("⚠️  Token expired, re-authenticating...")
        
        return self.auth.authenticate() and self.test_connection()
    
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
        try:
            response = requests.get(
                'https://api.githubcopilot.com/models',
                headers=self.auth.get_headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ Connection successful!")
                print(f"🔧 Loaded {len(self.tool_registry.get_tool_names())} tools")
                return True
            else:
                print(f"❌ Connection failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
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
                                "enum": ["name", "preference", "location", "project", "fact"],
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
                    "description": "Search through stored memories and conversation history for specific information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for in memory"
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
            content = arguments.get("content", "")
            
            # Map category to preference format
            if category == "name":
                formatted = f"User's name: {content}"
            elif category == "preference":
                formatted = f"Preference: {content}"
            elif category == "location":
                formatted = f"Location: {content}"
            elif category == "project":
                formatted = f"Project: {content}"
            else:
                formatted = content
            
            # Save to preferences
            self.memory._append_to_preferences([(category, formatted)])
            return f"✓ Saved to preferences: {formatted}"
        
        elif tool_name == "add_to_long_term_memory":
            category = arguments.get("category", "Important Facts")
            content = arguments.get("content", "")
            
            # Save to long-term memory
            self.memory.add_to_memory(category, content)
            return f"✓ Added to long-term memory ({category}): {content}"
        
        elif tool_name == "search_memory":
            query = arguments.get("query", "")
            results = self.memory.search_memory(query)
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
    
    def chat(self, user_message):
        """Send a message and get response with function calling"""
        # Log user message
        self.memory.log_conversation('user', user_message)
        
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
        
        # Prepare messages with memory context and skills
        messages = []
        system_content_parts = ["You are a helpful AI assistant with persistent memory and skills."]
        
        # Add knowledge gap handling (OpenClaw-style)
        system_content_parts.append(
            "\nKNOWLEDGE GAPS:\n"
            "- If you don't know something or lack current information, use 'search_web' tool FIRST\n"
            "- Never say 'I don't know' without attempting to search\n"
            "- Search for: current events, recent updates, unfamiliar terms, specific facts\n"
            "- After searching, synthesize the information in your response"
        )
        
        # Add memory system instructions
        system_content_parts.append(
            "\nMEMORY SYSTEM:\n"
            "- Use 'remember_preference' for personal info (name, likes, location, etc.)\n"
            "- Use 'add_to_long_term_memory' for important facts, decisions, or context that should persist\n"
            "- When user shares something important, ALWAYS call the appropriate memory function"
        )
        
        # Add skills summary (compact list)
        if skills_summary:
            system_content_parts.append(f"\n{skills_summary}")
            system_content_parts.append(
                "\nWhen a skill is activated, follow its instructions precisely. "
                "Skills combine multiple tools into workflows."
            )
        
        # Add active skill instructions (full details only when triggered)
        if active_skill_instructions:
            system_content_parts.append(active_skill_instructions)
        
        # Add memory context
        if memory_context:
            system_content_parts.append(f"\nHere's what you currently know about the user:\n{memory_context}")
        
        messages.append({
            'role': 'system',
            'content': '\n'.join(system_content_parts)
        })
        messages.extend(self.conversation_history)
        
        # Prepare request with function calling
        payload = {
            'model': 'gpt-4o',
            'messages': messages,
            'tools': self.get_all_tools(),
            'tool_choice': 'auto',
            'temperature': 0.7,
            'max_tokens': 2000
        }
        
        try:
            response = requests.post(
                self.API_URL,
                headers=self.auth.get_headers(),
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
                
                # Build complete message history for second request
                # Include system message + all conversation history
                complete_messages = []
                if memory_context:
                    complete_messages.append({
                        'role': 'system',
                        'content': (
                            f"You are a helpful AI assistant with persistent memory.\n\n"
                            f"KNOWLEDGE GAPS:\n"
                            f"- If you don't know something or lack current information, use 'search_web' tool FIRST\n"
                            f"- Never say 'I don't know' without attempting to search\n"
                            f"- Search for: current events, recent updates, unfamiliar terms, specific facts\n"
                            f"- After searching, synthesize the information in your response\n\n"
                            f"MEMORY SYSTEM:\n"
                            f"- Use 'remember_preference' for personal info (name, likes, location, etc.)\n"
                            f"- Use 'add_to_long_term_memory' for important facts, decisions, or context that should persist\n"
                            f"- When user shares something important, ALWAYS call the appropriate memory function\n\n"
                            f"Here's what you currently know about the user:\n{memory_context}"
                        )
                    })
                complete_messages.extend(self.conversation_history)
                
                # Get final response after tool execution
                final_payload = {
                    'model': 'gpt-4o',
                    'messages': complete_messages,
                    'tools': self.get_all_tools(),
                    'temperature': 0.7,
                    'max_tokens': 2000
                }
                
                final_response = requests.post(
                    self.API_URL,
                    headers=self.auth.get_headers(),
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
            from copilot_auth import CopilotAuth
            from memory_system import MemorySystem
            from tools.tool_registry import ToolRegistry
            from retry_config import RetryConfig
            from skills.skill_system import SkillSystem
            
            # Keep conversation history but reload everything else
            old_history = self.conversation_history
            old_auth_token = self.auth.access_token if hasattr(self.auth, 'access_token') else None
            
            self.auth = CopilotAuth()
            if old_auth_token:
                self.auth.access_token = old_auth_token
            
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
        print("🤖 GitHub Copilot Chatbot with Memory")
        print("=" * 60)
        print("\nCommands:")
        print("  /clear   - Clear conversation history")
        print("  /reload  - Hot reload all modules")
        print("  /memory  - Show memory stats")
        print("  /search  - Search memory")
        print("  /skills  - List available skills")
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
                    elif user_input == '/help':
                        print("\nCommands:")
                        print("  /clear   - Clear conversation history")
                        print("  /reload  - Hot reload all modules")
                        print("  /memory  - Show memory stats")
                        print("  /search  - Search memory")
                        print("  /skills  - List available skills")
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


if __name__ == '__main__':
    bot = CopilotChatbot()
    
    if bot.setup():
        bot.run()
    else:
        print("❌ Authentication failed")
