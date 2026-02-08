"""
Neural Trainer - Generates semantic training data for A.N.K.I.T.A intents.
Uses the LLM to expand rule-based intelligence into neural-mapping intelligence.
"""
import json
import os
import sys
from pathlib import Path

# Fix paths
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from llm.llm_client import ask_llm

_INTENTS_PATH = project_root / "brain" / "intents.json"

def generate_variations(intent, examples, count=5):
    """Ask LLM to generate 5 new natural language variations for an intent."""
    prompt = f"""You are training an AI assistant.
Current Intent: {intent}
Existing examples of how a human would say this:
{", ".join(examples[:3])}

Task: Generate {count} new, varied, and natural ways a human might say this. 
Use cool, casual, and formal language. 
Return ONLY a JSON list of strings. No extra text.
"""
    try:
        response = ask_llm(prompt)
        # Try to find JSON list in response
        if "[" in response and "]" in response:
            start = response.find("[")
            end = response.rfind("]") + 1
            new_examples = json.loads(response[start:end])
            return [str(e).strip() for e in new_examples if e]
    except Exception as e:
        print(f"Error generating for {intent}: {e}")
    return []

def run_training():
    print("--- A.N.K.I.T.A Neural Training Session ---")
    sys.stdout.flush()
    
    if not _INTENTS_PATH.exists():
        print(f"Error: {_INTENTS_PATH} not found.")
        return
        
    with open(_INTENTS_PATH, "r", encoding="utf-8") as f:
        intents_data = json.load(f)
    
    total_new = 0
    # Train top 5 intents for verification
    target_intents = list(intents_data.keys())[:5]
    
    for intent in target_intents:
        print(f"Training intent: {intent}...", end=" ", flush=True)
        examples = intents_data[intent].get("examples", [])
        new_vars = generate_variations(intent, examples)
        
        if new_vars:
            # Filter duplicates
            existing_set = set(e.lower() for e in examples)
            added = 0
            for v in new_vars:
                if v.lower() not in existing_set:
                    examples.append(v)
                    existing_set.add(v.lower())
                    added += 1
            
            intents_data[intent]["examples"] = examples
            total_new += added
            print(f"Added {added} new neural mappings.")
        else:
            print("No new mappings generated.")
        sys.stdout.flush()

    # Save updated intents
    with open(_INTENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(intents_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n--- TRAINING COMPLETE: {total_new} neural mappings locked in ---")
    sys.stdout.flush()

if __name__ == "__main__":
    run_training()
