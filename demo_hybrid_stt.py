"""
Hybrid STT Demo - Live demonstration of the Vosk + Whisper system.

This demo shows:
1. Passive listening with Vosk (stores to context)
2. Trigger detection and Whisper verification
3. Mode switching (ACTIVE, STANDBY, OFF)

Usage:
    python demo_hybrid_stt.py

Controls:
    - Say "Ankita active" to start recording context
    - Say "Ankita standby" to pause and clear context
    - Say "Ankita stop" to exit
    - Say "Ankita answer" to trigger a response
    
Press Ctrl+C to quit.
"""

import os
import sys
import time
import signal

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ankita.context import Mode, TriggerCommand, get_context_manager


# ANSI colors for pretty output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_status(mode, context_count: int):
    """Print current status."""
    # Handle both Mode enum and string
    mode_str = mode.value if hasattr(mode, 'value') else str(mode)
    
    mode_colors = {
        'off': Colors.RED,
        'standby': Colors.YELLOW,
        'active': Colors.GREEN,
        'responding': Colors.CYAN,
    }
    
    color = mode_colors.get(mode_str, '')
    print(f"\r{color}[{mode_str.upper()}]{Colors.ENDC} Context: {context_count} entries", end='')
    sys.stdout.flush()


def on_trigger(command: TriggerCommand, text: str):
    """Handle trigger commands."""
    print()
    print(f"{Colors.BOLD}{Colors.CYAN}🎯 TRIGGER: {command.value}{Colors.ENDC}")
    print(f"   Text: {text}")
    
    if command == TriggerCommand.ANSWER:
        context = manager.get_context()
        print(f"\n{Colors.GREEN}📝 Context for answer:{Colors.ENDC}")
        print(context)
        print()
        # Here you would call your LLM to generate a response


def on_mode_change(mode: Mode):
    """Handle mode changes."""
    print()
    print(f"{Colors.BOLD}🔄 Mode changed to: {mode.value}{Colors.ENDC}")


def main():
    global manager
    
    print()
    print(f"{Colors.BOLD}{Colors.HEADER}=" * 60)
    print("HYBRID STT DEMO - Vosk (passive) + Whisper (commands)")
    print("=" * 60 + Colors.ENDC)
    print()
    print("This demo shows the hybrid STT architecture in action:")
    print(f"  {Colors.GREEN}• Vosk{Colors.ENDC}: Passive listening (zero hallucination)")
    print(f"  {Colors.CYAN}• Whisper{Colors.ENDC}: Command verification (high accuracy)")
    print()
    print("Voice commands:")
    print(f"  {Colors.YELLOW}\"Ankita active\"{Colors.ENDC}  - Start recording context")
    print(f"  {Colors.YELLOW}\"Ankita standby\"{Colors.ENDC} - Pause and clear context")
    print(f"  {Colors.YELLOW}\"Ankita answer\"{Colors.ENDC}  - Trigger a response")
    print(f"  {Colors.YELLOW}\"Ankita stop\"{Colors.ENDC}    - Exit")
    print()
    print("Press Ctrl+C to quit.")
    print()
    
    # Initialize
    manager = get_context_manager()
    manager.set_answer_callback(lambda ctx: on_trigger(TriggerCommand.ANSWER, ctx))
    manager.set_mode_callback(on_mode_change)
    
    # Set up trigger callback
    from ankita.context.passive_listener import get_passive_listener
    listener = get_passive_listener()
    listener.set_trigger_callback(on_trigger)
    
    # Start
    print(f"{Colors.BOLD}Starting hybrid STT listener...{Colors.ENDC}")
    manager.start()
    
    print()
    print(f"{Colors.GREEN}✅ Listening! Speak to test.{Colors.ENDC}")
    print()
    
    # Handle Ctrl+C
    running = True
    
    def signal_handler(sig, frame):
        nonlocal running
        running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Main loop
    try:
        while running and listener.mode != Mode.OFF:
            status = manager.get_status()
            print_status(status["mode"], status["context_entries"])
            
            # Check for context updates
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        pass
    
    finally:
        print()
        print(f"\n{Colors.YELLOW}Shutting down...{Colors.ENDC}")
        manager.stop()
        
        print()
        print(f"{Colors.BOLD}Final context:{Colors.ENDC}")
        print(manager.get_context())
        print()
        print(f"{Colors.GREEN}Demo complete!{Colors.ENDC}")


if __name__ == "__main__":
    main()
