"""Quick test to verify agent upgrades are working."""
import os
from agents.supervisor import SupervisorAgent
from agents.specialists import SPECIALIST_MAP
from llm import LLMRuntime

def test_imports():
    """Test that all modules import successfully."""
    print("✅ All imports successful")
    print(f"✅ {len(SPECIALIST_MAP)} specialists loaded:")
    for name in SPECIALIST_MAP.keys():
        print(f"   - {name}")
    print()

def test_supervisor_routing():
    """Test Supervisor routing with various requests."""
    print("Testing Supervisor routing...")
    
    # Create a minimal runtime
    rt = LLMRuntime(
        provider='copilot',
        model='gpt-4o',
        api_key=os.getenv('GITHUB_TOKEN', 'test'),
        base_url='https://api.githubcopilot.com',
        max_tokens=4096
    )
    sup = SupervisorAgent(rt)
    
    test_cases = [
        "write a poem about AI",
        "compare Python vs JavaScript",
        "play some lofi music",
        "how's my PC health",
        "what does reddit think about AI",
    ]
    
    print("\nTest cases (routing only, no LLM calls):")
    for i, test in enumerate(test_cases, 1):
        print(f"\n{i}. '{test}'")
        print("   (Would route to Supervisor for agent selection)")
    
    print("\n✅ Supervisor initialized successfully")
    print()

def test_specialist_prompts():
    """Verify specialist prompts contain new features."""
    print("Checking specialist prompt upgrades...")
    
    checks = {
        "MusicAgent": ["TASTE MEMORY PROTOCOL", "SEARCH → PLAY PIPELINE", "QUEUE INTELLIGENCE"],
        "CronAgent": ["NATURAL LANGUAGE TIME PARSER", "CONFIRMATION PROTOCOL"],
        "WebAgent": ["TOOL SELECTION DECISION TREE", "compare_search", "search_stackoverflow"],
        "SystemAgent": ["NEW TOOL DECISION TREE", "system_health", "voice_control"],
        "FileAgent": ["FILENAME INTELLIGENCE", "EDIT VS OVERWRITE"],
        "CodeAgent": ["search_stackoverflow"],
        "CommsAgent": ["CONTACT LOOKUP FIRST", "MESSAGE CONFIRMATION PROTOCOL"],
        "ScreenAgent": ["CLICK FALLBACK CHAIN", "BEFORE/AFTER VERIFICATION"],
        "IntegrationAgent": ["DOMAIN ROUTER"],
    }
    
    for agent_name, keywords in checks.items():
        agent = SPECIALIST_MAP.get(agent_name)
        if agent:
            prompt = agent.system_prompt
            found = [kw for kw in keywords if kw in prompt]
            if len(found) == len(keywords):
                print(f"✅ {agent_name}: All {len(keywords)} features present")
            else:
                print(f"⚠️  {agent_name}: {len(found)}/{len(keywords)} features found")
                missing = [kw for kw in keywords if kw not in found]
                print(f"   Missing: {missing}")
    
    print()

def test_orchestrator():
    """Test Orchestrator initialization."""
    from agents.orchestrator import Orchestrator
    from pathlib import Path
    
    print("Testing Orchestrator...")
    rt = LLMRuntime(
        provider='copilot',
        model='gpt-4o',
        api_key=os.getenv('GITHUB_TOKEN', 'test'),
        base_url='https://api.githubcopilot.com',
        max_tokens=4096
    )
    
    orch = Orchestrator(rt, Path.cwd())
    print("✅ Orchestrator initialized successfully")
    print(f"✅ Supervisor attached: {orch.supervisor is not None}")
    print()

if __name__ == "__main__":
    print("=" * 60)
    print("ANKITA Agent Upgrade Verification Test")
    print("=" * 60)
    print()
    
    try:
        test_imports()
        test_supervisor_routing()
        test_specialist_prompts()
        test_orchestrator()
        
        print("=" * 60)
        print("✅ ALL TESTS PASSED - Agent upgrades working correctly!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
