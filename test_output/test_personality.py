import sys, importlib.util
spec = importlib.util.spec_from_file_location(
    'tools.personality_engine',
    'C:/Users/anime/3D Objects/A.N.K.I.T.A/tools/personality_engine.py'
)
pe = importlib.util.module_from_spec(spec)
sys.modules['tools.personality_engine'] = pe
spec.loader.exec_module(pe)

tests = [
    ('I am so stressed, nothing is working', 'stressed'),
    ('THIS IS BROKEN WTF', 'frustrated'),
    ('YES IT FINALLY WORKS!!!', 'excited'),
    ('feeling really sad today', 'sad'),
    ('im so tired, no energy', 'tired'),
    ('how does async await work exactly', 'curious'),
    ('urgent fix this asap right now', 'urgent'),
    ('hey btw no rush', 'casual'),
    ('open chrome', 'neutral'),
]

all_pass = True
for text, expected in tests:
    t = pe.SessionMoodTracker()
    s = t.update(text)
    ok = s.primary == expected
    if not ok:
        all_pass = False
    status = 'OK' if ok else 'MISMATCH'
    print(f'[{status}] "{text[:35]}" -> {s.primary} ({s.intensity:.2f}) expected={expected}')

print()
print('All tests passed!' if all_pass else 'Some tests FAILED.')
