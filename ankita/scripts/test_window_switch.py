import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.window_switch import handle_window_switch

def run(q):
    print('Query:', q)
    res = handle_window_switch(q)
    print('Result:', res)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('query', nargs='?', default='notepad')
    args = p.parse_args()
    run(args.query)
