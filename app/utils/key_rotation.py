"""
KEY ROTATION UTILITY
====================

PURPOSE:
  Provides round-robin rotation for multiple Groq API keys to distribute load
  and avoid rate limits. When multiple keys are configured, requests cycle
  through them automatically.

USAGE:
  brain_idx, chat_idx = get_next_key_pair(total_keys, need_brain=True)
  # brain_idx: Key index for brain/classification service
  # chat_idx: Key index for chat/response generation
"""

import threading

_rotation_lock = threading.Lock()
_current_index = 0


def get_next_key_pair(total_keys: int, need_brain: bool = False) -> tuple:
    """
    Get the next key index pair for brain and chat services.
    
    Args:
        total_keys: Total number of API keys available
        need_brain: Whether brain service is needed (returns separate index)
        
    Returns:
        Tuple of (brain_index, chat_index)
        - If need_brain=True: Returns (index, next_index) for separate services
        - If need_brain=False: Returns (None, index) - no brain service
    """
    global _current_index
    
    if total_keys <= 0:
        return (None, 0)
    
    with _rotation_lock:
        if need_brain and total_keys >= 2:
            # Use separate keys for brain and chat
            brain_idx = _current_index % total_keys
            chat_idx = (brain_idx + 1) % total_keys
            _current_index = (chat_idx + 1) % total_keys
            return (brain_idx, chat_idx)
        else:
            # Single key or no brain needed
            idx = _current_index % total_keys
            _current_index = (idx + 1) % total_keys
            return (None if not need_brain else idx, idx)
