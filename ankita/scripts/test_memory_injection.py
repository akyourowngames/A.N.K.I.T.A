import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import llm_client as L

print('--- casual / should be minimal ---')
print(L.build_context("so what's your plan"))
print('\n--- explicit history / should include memories ---')
print(L.build_context("what did I do yesterday?"))
print('\n--- explicit replay (do it again) should resolve pronoun) ---')
print(L.build_context("do it again"))
