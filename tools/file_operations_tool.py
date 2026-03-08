#!/usr/bin/env python3
"""
File Operations Tool - Read, write, create, delete files and directories
"""

import os
from pathlib import Path
from typing import Optional


class FileOperationsTool:
    """Comprehensive file operations for autonomous agent behavior"""
    
    @staticmethod
    def get_schema():
        """Get tool schema for function calling"""
        return {
            "type": "function",
            "function": {
                "name": "file_operation",
                "description": "Perform file operations: read, write, create, delete, list files. Use this to autonomously manage files like Jarvis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["read", "write", "append", "delete", "create_dir", "list", "exists"],
                            "description": "Operation to perform"
                        },
                        "path": {
                            "type": "string",
                            "description": "File or directory path (relative to workspace or absolute)"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write or append (REQUIRED for write/append operations)"
                        },
                        "encoding": {
                            "type": "string",
                            "description": "File encoding (default: utf-8)",
                            "default": "utf-8"
                        }
                    },
                    "required": ["operation", "path"]
                }
            }
        }
    
    @staticmethod
    def execute(arguments: dict) -> str:
        """Execute file operation"""
        operation = arguments.get("operation", "")
        path_str = arguments.get("path", "")
        content = arguments.get("content")  # Can be None
        encoding = arguments.get("encoding", "utf-8")
        
        if not operation or not path_str:
            return "Error: operation and path are required"
        
        # Validate content for operations that need it
        if operation in ["write", "append"]:
            if content is None:
                return f"Error: 'content' parameter is required for {operation} operation. Received arguments: {list(arguments.keys())}"
            if not content:
                return f"Error: content cannot be empty for {operation} operation"
        
        try:
            path = Path(path_str)
            
            if operation == "read":
                return FileOperationsTool._read_file(path, encoding)
            
            elif operation == "write":
                return FileOperationsTool._write_file(path, content, encoding)
            
            elif operation == "append":
                return FileOperationsTool._append_file(path, content, encoding)
            
            elif operation == "delete":
                return FileOperationsTool._delete_file(path)
            
            elif operation == "create_dir":
                return FileOperationsTool._create_directory(path)
            
            elif operation == "list":
                return FileOperationsTool._list_directory(path)
            
            elif operation == "exists":
                return FileOperationsTool._check_exists(path)
            
            else:
                return f"Error: Unknown operation '{operation}'"
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    @staticmethod
    def _read_file(path: Path, encoding: str) -> str:
        """Read file content"""
        if not path.exists():
            return f"Error: File not found: {path}"
        
        if not path.is_file():
            return f"Error: Path is not a file: {path}"
        
        try:
            content = path.read_text(encoding=encoding)
            return f"File: {path}\n\n{content}"
        except Exception as e:
            return f"Error reading file: {str(e)}"
    
    @staticmethod
    def _write_file(path: Path, content: str, encoding: str) -> str:
        """Write content to file (overwrites existing)"""
        try:
            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            path.write_text(content, encoding=encoding)
            
            return f"✓ Written to {path} ({len(content)} chars)"
        except Exception as e:
            return f"Error writing file: {str(e)}"
    
    @staticmethod
    def _append_file(path: Path, content: str, encoding: str) -> str:
        """Append content to file"""
        try:
            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Append to file
            with open(path, 'a', encoding=encoding) as f:
                f.write(content)
            
            return f"✓ Appended to {path} ({len(content)} chars)"
        except Exception as e:
            return f"Error appending to file: {str(e)}"
    
    @staticmethod
    def _delete_file(path: Path) -> str:
        """Delete file or directory"""
        if not path.exists():
            return f"Error: Path does not exist: {path}"
        
        try:
            if path.is_file():
                path.unlink()
                return f"✓ Deleted file: {path}"
            elif path.is_dir():
                # Only delete empty directories for safety
                if any(path.iterdir()):
                    return f"Error: Directory not empty: {path}. Use terminal command for recursive delete."
                path.rmdir()
                return f"✓ Deleted directory: {path}"
            else:
                return f"Error: Unknown path type: {path}"
        except Exception as e:
            return f"Error deleting: {str(e)}"
    
    @staticmethod
    def _create_directory(path: Path) -> str:
        """Create directory (and parents if needed)"""
        try:
            path.mkdir(parents=True, exist_ok=True)
            return f"✓ Created directory: {path}"
        except Exception as e:
            return f"Error creating directory: {str(e)}"
    
    @staticmethod
    def _list_directory(path: Path) -> str:
        """List directory contents"""
        if not path.exists():
            return f"Error: Directory not found: {path}"
        
        if not path.is_dir():
            return f"Error: Path is not a directory: {path}"
        
        try:
            items = []
            for item in sorted(path.iterdir()):
                if item.is_dir():
                    items.append(f"📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    items.append(f"📄 {item.name} ({size} bytes)")
            
            if not items:
                return f"Directory is empty: {path}"
            
            return f"Contents of {path}:\n" + "\n".join(items)
        except Exception as e:
            return f"Error listing directory: {str(e)}"
    
    @staticmethod
    def _check_exists(path: Path) -> str:
        """Check if path exists"""
        if path.exists():
            if path.is_file():
                size = path.stat().st_size
                return f"✓ File exists: {path} ({size} bytes)"
            elif path.is_dir():
                count = len(list(path.iterdir()))
                return f"✓ Directory exists: {path} ({count} items)"
            else:
                return f"✓ Path exists: {path}"
        else:
            return f"✗ Path does not exist: {path}"
