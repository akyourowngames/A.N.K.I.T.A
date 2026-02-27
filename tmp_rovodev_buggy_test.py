"""Buggy test script for God Mode FileAgent demo."""

import math

def add_numbers(a, b):
    return a + b  # Fixed: corrected to addition

def greet(name):
    print("Hello " + name + "!")  # correct
def calculate_area(radius):
    return pi * radius ** 2  # Fixed: corrected area formula
    return pi * radius  # BUG: should be pi * radius ** 2

if __name__ == "__main__":
    result = add_numbers(10, 5)
    assert result == 15, f"add_numbers failed: got {result}, expected 15"

    greet("ANKITA")

    area = calculate_area(7)
    assert round(area, 2) == 153.94, f"calculate_area failed: got {round(area, 2)}, expected 153.94"

    print("All tests passed!")
