import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ankita')))

from brain import planner
from executor import executor

class TestArchitecture(unittest.TestCase):
    
    def test_planner_build_step(self):
        step = planner._build_step("some.action", {"arg1": "val1"}, retry=3, timeout=5.0)
        self.assertEqual(step["action"], "some.action")
        self.assertEqual(step["args"], {"arg1": "val1"})
        self.assertEqual(step["retry"], 3)
        self.assertEqual(step["timeout"], 5.0)

    def test_planner_plan_structure(self):
        # Mock intent result
        intent_result = {"intent": "youtube.play", "entities": {"query": "test song"}}
        
        # This relies on real tools_meta.json, which is fine for integration test
        plan = planner.plan(intent_result)
        
        self.assertEqual(plan["chain_id"], "youtube.play")
        self.assertTrue(len(plan["steps"]) >= 2)
        
        # Check args merging
        # youtube.play step should have args_from query
        # Based on tools_meta.json: { "tool": "youtube.play", "args_from": "query" }
        # Note: planner might output 'action' or 'tool' depending on impl, but our _build_step uses 'action'
        play_step = [s for s in plan["steps"] if s["action"] == "youtube.play"][0]
        self.assertEqual(play_step["args"]["query"], "test song")

    @patch("executor.executor.importlib.import_module")
    def test_executor_execution(self, mock_import):
        # Setup mock tool
        mock_module = MagicMock()
        mock_module.run.return_value = {"status": "success", "data": "ok"}
        mock_import.return_value = mock_module
        
        # Plan with one step
        plan = {
            "chain_id": "test.chain",
            "steps": [
                {"action": "notepad.open", "args": {"foo": "bar"}, "retry": 2, "timeout": 1.0}
            ]
        }
        
        result = executor.execute(plan)
        
        # Verify result structure
        self.assertEqual(result["status"], "success")
        self.assertIn("chain_result", result)
        self.assertEqual(result["chain_result"]["chain_id"], "test.chain")
        self.assertEqual(result["chain_result"]["total_steps"], 1)
        
        # Verify tool called
        # notepad.open maps to tools.notepad.open in tools.json
        mock_import.assert_called_with("tools.notepad.open")
        mock_module.run.assert_called_with(foo="bar")

    @patch("executor.executor.importlib.import_module")
    @patch("time.sleep") # speed up tests
    def test_executor_retry(self, mock_sleep, mock_import):
        # Setup mock tool that fails once then succeeds
        mock_module = MagicMock()
        mock_module.run.side_effect = [Exception("Fail 1"), {"status": "success"}]
        mock_import.return_value = mock_module
        
        plan = {
            "chain_id": "retry.test",
            "steps": [
                {"action": "notepad.open", "retry": 2}
            ]
        }
        
        result = executor.execute(plan)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(mock_module.run.call_count, 2)

if __name__ == '__main__':
    unittest.main()
