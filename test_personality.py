#!/usr/bin/env python3
"""Quick test for JARVIS personality fixes."""
import sys
sys.path.insert(0, r"c:\Users\anime\3D Objects\New folder\A.N.K.I.T.A\ankita")

from ankita_core import handle_text

test_inputs = ['hi', 'hello', 'how are you', 'nothing', 'bye']

for p in test_inputs:
    print(f'You: {p}')
    r = handle_text(p)
    # handle_text already prints 'Ankita: {response}'
