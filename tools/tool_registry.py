#!/usr/bin/env python3
"""
Tool Registry - Central registry for all available tools
"""

from tools.terminal_tool import TerminalTool
from tools.web_search_tool import WebSearchTool
from tools.web_fetch_tool import WebFetchTool
from tools.file_operations_tool import FileOperationsTool
from tools.gui_automation_tool import GUIAutomationTool
from tools.window_clipboard_tool import WindowClipboardTool


class ToolRegistry:
    """Manages all available tools and their execution"""
    
    def __init__(self):
        # Register all tools here
        self.tools = {
            "execute_terminal_command": TerminalTool,
            "search_web": WebSearchTool,
            "fetch_webpage": WebFetchTool,
            "file_operation": FileOperationsTool,
            "gui_control": GUIAutomationTool,
            "window_clipboard": WindowClipboardTool
        }
    
    def get_all_schemas(self):
        """Get schemas for all registered tools"""
        schemas = []
        for tool_class in self.tools.values():
            schemas.append(tool_class.get_schema())
        return schemas
    
    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Execute a tool by name
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool
        
        Returns:
            Tool execution result
        """
        if tool_name not in self.tools:
            return f"Error: Unknown tool '{tool_name}'"
        
        tool_class = self.tools[tool_name]
        return tool_class.execute(arguments)
    
    def get_tool_names(self):
        """Get list of all registered tool names"""
        return list(self.tools.keys())
