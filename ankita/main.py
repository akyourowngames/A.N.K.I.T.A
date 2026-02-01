from ankita_core import handle_text

print("[Ankita] Ready. Type your command or 'exit' to quit.")

while True:
    try:
        text = input("You: ")
        if text.lower() in ["exit", "quit", "bye"]:
            print("[Ankita] Goodbye!")
            break
        
        handle_text(text)
    except KeyboardInterrupt:
        print("\n[Ankita] Goodbye!")
        break
    except Exception as e:
        print(f"Error: {e}")
# User says: "do it again"
recalled = resolve_pronouns(text)  # Returns last episode
handle_intent(recalled)             # Replays the action