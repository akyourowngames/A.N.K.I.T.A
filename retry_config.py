#!/usr/bin/env python3
"""
Retry Configuration - Exponential backoff settings for tool execution
"""

import time
import random


class RetryConfig:
    """Configuration for retry logic with exponential backoff"""
    
    # Default retry settings
    MAX_RETRIES = 3
    MIN_DELAY_MS = 1000  # 1 second
    MAX_DELAY_MS = 30000  # 30 seconds
    JITTER = 0.1  # 10% jitter to prevent thundering herd
    
    @staticmethod
    def calculate_delay(attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter
        
        Args:
            attempt: Current retry attempt (0-indexed)
        
        Returns:
            Delay in seconds
        """
        # Exponential: 1s, 3s, 10s
        base_delays = [1.0, 3.0, 10.0]
        
        if attempt >= len(base_delays):
            delay = base_delays[-1]
        else:
            delay = base_delays[attempt]
        
        # Add jitter (±10%)
        jitter_amount = delay * RetryConfig.JITTER
        jitter = random.uniform(-jitter_amount, jitter_amount)
        
        return delay + jitter
    
    @staticmethod
    def should_retry(attempt: int, error: Exception) -> bool:
        """
        Determine if we should retry based on attempt count and error type
        
        Args:
            attempt: Current attempt number (0-indexed)
            error: The exception that occurred
        
        Returns:
            True if should retry, False otherwise
        """
        if attempt >= RetryConfig.MAX_RETRIES:
            return False
        
        # Retry on transient errors
        error_str = str(error).lower()
        transient_errors = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'unavailable',
            'rate limit',
            '429',
            '503',
            '504'
        ]
        
        return any(err in error_str for err in transient_errors)
