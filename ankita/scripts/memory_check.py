import os
import json
import sys
from pathlib import Path
# ensure project package imports work when running this script directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory import memory_manager as m

print('CONVERSATION PATH:', m.CONVO_PATH)
print('EPISODES PATH:   ', m.EPISODES_PATH)
print('PREFS PATH:      ', m.PREFS_PATH)
print('NOTES PATH:      ', m.NOTES_PATH)
print('LEGACY BAK      :', os.path.exists(m.OLD_MEMORY_PATH + '.bak'))
mem = m.load()
print('TOP-LEVEL KEYS   :', list(mem.keys()))
print('CONVERSATION LEN :', len(mem.get('conversation', [])))
print('EPISODES LEN     :', len(mem.get('episodes', [])))
print('SAMPLE PREFS     :', json.dumps(mem.get('preferences', {}), indent=2)[:400])
