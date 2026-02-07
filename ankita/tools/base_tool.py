"""
Base Tool Template
All new tools should inherit from this base class.
"""
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Base class for all Ankita tools."""
    
    def __init__(self):
        """Initialize the tool."""
        self.name = self.__class__.__name__
        self.category = "general"
    
    @abstractmethod
    def execute(self, **params) -> Dict[str, Any]:
        """
        Execute the tool action.
        
        Args:
            **params: Tool-specific parameters
        
        Returns:
            dict: {
                'status': 'success' or 'error',
                'message': str description,
                'data': Any additional data
            }
        """
        pass
    
    def _success(self, message: str, data: Any = None) -> Dict[str, Any]:
        """Helper to return success response."""
        return {
            'status': 'success',
            'message': message,
            'data': data or {}
        }
    
    def _error(self, message: str, error: Optional[Exception] = None) -> Dict[str, Any]:
        """Helper to return error response."""
        return {
            'status': 'error',
            'message': message,
            'data': {'error': str(error) if error else None}
        }
    
    def validate_params(self, params: Dict[str, Any], required: list) -> tuple:
        """
        Validate required parameters.
        
        Args:
            params: Parameters dict
            required: List of required parameter names
        
        Returns:
            tuple: (is_valid, missing_params)
        """
        missing = [p for p in required if p not in params]
        return (len(missing) == 0, missing)
