"""Suite hermeticity: core.config load_dotenv() pulls the developer's own
.env into every test process. Behavior flags from a personal .env (e.g.
ZUMBA_NO_USER_MD=1) must not change what the suite asserts — scrub them
here. Tests that need a flag set it explicitly via monkeypatch.
"""

import os

import pytest

_SCRUBBED_FLAGS = ("ZUMBA_NO_USER_MD",)


@pytest.fixture(autouse=True)
def _scrub_personal_behavior_flags(monkeypatch):
    for name in _SCRUBBED_FLAGS:
        monkeypatch.delenv(name, raising=False)
