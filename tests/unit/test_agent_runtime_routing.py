import unittest

from agent_runtime import _is_copout


class AgentRuntimeRoutingTests(unittest.TestCase):
    def test_short_normal_reply_is_not_treated_as_copout(self) -> None:
        self.assertFalse(_is_copout("Hey, what's up?"))
        self.assertFalse(_is_copout("All good."))

    def test_actual_refusal_is_treated_as_copout(self) -> None:
        self.assertTrue(_is_copout("I can't do that."))
        self.assertTrue(_is_copout(""))


if __name__ == "__main__":
    unittest.main()
