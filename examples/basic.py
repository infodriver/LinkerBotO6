#!/usr/bin/env python3
"""Minimal LinkerBot O6 SDK example: connect, health-check, move, grasp."""
import sys

from linkerbot_o6.hand import LinkerHand, pct_to_raw


def main():
    hand = LinkerHand(side="left")  # CAN ID 0x28; use side="right" for 0x27
    try:
        print("Serial:", hand.get_serial())
        print("Faults:", hand.get_faults(), "(all zero = healthy)")
        print("Temps (C):", hand.get_temps())

        # open the hand, then make a gentle fist
        hand.move_raw(pct_to_raw([100] * 6), speed=60)
        input("Hand open. Press Enter to make a fist...")
        hand.preset("fist", speed=60)
        input("Fist. Press Enter to open again...")
        hand.preset("open", speed=60)

        # two-stage ball grasp (fingers close, then thumb wraps over)
        hand.grasp(ball_cm=6.0, strength=150)
        input("Holding a (pretend) ball. Press Enter to release...")
        hand.release()
    finally:
        hand.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
