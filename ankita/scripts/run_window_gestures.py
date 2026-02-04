import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from features.window_switch.gestures import run_gesture_mode


def main():
    print('Starting gesture runner. Press q to quit the window.')
    res = run_gesture_mode()
    print('Gesture runner result:')
    print(res)


if __name__ == '__main__':
    main()
