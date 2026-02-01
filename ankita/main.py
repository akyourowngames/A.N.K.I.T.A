from brain.intent_model import classify
from brain.planner import plan
from executor.executor import execute

while True:
    try:
        text = input("You: ")
        if text.lower() in ["exit", "quit", "bye"]:
            break
        
        intent_result = classify(text)
        execution_plan = plan(intent_result)
        execute(execution_plan)
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"Error: {e}")
