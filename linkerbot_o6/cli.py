#!/usr/bin/env python3
"""LinkerBot O6 SDK — command line interface."""
import argparse
import sys
import time

from .hand import LinkerHand, PRESETS_RAW, pct_to_raw, raw_to_pct

JOINTS = ["thumb_flex", "thumb_abd", "index", "middle", "ring", "pinky"]


def fmt(vals):
    return " ".join(f"{v:3d}" for v in vals) if vals else "n/a"


def cmd_probe(hand):
    serial = hand.get_serial()
    faults = hand.get_faults()
    temps = hand.get_temps()
    pos = hand.get_positions()
    print(f"Serial:      {serial or 'n/a'}")
    print(f"Faults:      {fmt(faults)}" + ("  (all clear)" if faults and all(v == 0 for v in faults) else ""))
    print(f"Temps (C):   {fmt(temps)}")
    print(f"Positions:   raw [{fmt(pos)}]  pct [{fmt(raw_to_pct(pos) if pos else [])}]")
    return 0 if (serial or faults) else 1


def cmd_pos(hand):
    pos = hand.get_positions()
    if not pos:
        print("No position response from hand.")
        return 1
    print(f"Joint positions ({JOINTS}):")
    for name, raw, pct in zip(JOINTS, pos, raw_to_pct(pos)):
        print(f"  {name:12s} raw={raw:3d}  pct={pct:3d}")
    return 0


def cmd_move(hand, args):
    if args.pos is not None:
        vals = [float(x) for x in args.pos.split(",")]
        if len(vals) != 6 or any(not 0 <= v <= 100 for v in vals):
            print("--pos needs exactly 6 values 0-100: thumb_flex,thumb_abd,index,middle,ring,pinky")
            return 2
        raw = pct_to_raw(vals)
    elif args.raw is not None:
        vals = [int(x) for x in args.raw.split(",")]
        if len(vals) != 6 or any(not 0 <= v <= 255 for v in vals):
            print("--raw needs exactly 6 values 0-255.")
            return 2
        raw = vals
    elif args.preset:
        raw = PRESETS_RAW[args.preset]
        print(f"Preset '{args.preset}' -> raw [{fmt(raw)}]")
    else:
        print("Nothing to do: give --pos, --raw, or --preset.")
        return 2

    print(f"Moving to raw [{fmt(raw)}]  (pct [{fmt(raw_to_pct(raw))}])")
    print(f"  speed={args.speed}  torque={'unchanged' if args.torque is None else args.torque}")
    if not args.yes:
        r = input("  Type 'y' to move the hand: ")
        if r.strip().lower() != "y":
            print("  Aborted.")
            return 1

    hand.move_raw(raw, speed=args.speed, torque=args.torque)
    if args.wait:
        time.sleep(args.wait)
    time.sleep(0.3)
    got = hand.get_positions()
    print(f"Readback:    raw [{fmt(got)}]")
    return 0


def cmd_grasp(hand, args):
    if args.release:
        print("Releasing: opening hand...")
        if not args.yes:
            r = input("  Type 'y' to open the hand: ")
            if r.strip().lower() != "y":
                print("  Aborted.")
                return 1
        hand.release(speed=args.speed)
        print("Released.")
        return 0

    pose = hand.grasp(ball_cm=args.ball, strength=args.strength, speed=args.speed)
    print(f"Grasping ball ~{args.ball} cm -> pose {pose}%  strength={args.strength}")
    print("Holding. Run with --release to let go.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="LinkerBot O6 SDK — move a LinkerHand O6 over CAN (PCAN-USB adapter). "
                    "Angles are 0-100 percent; higher = finger extends.",
        epilog="examples:\n"
               "  linkerbot-o6 probe\n"
               "  linkerbot-o6 pos\n"
               "  linkerbot-o6 move --preset fist --speed 60\n"
               "  linkerbot-o6 move --pos 80,80,80,80,80,80 --speed 40\n"
               "  linkerbot-o6 move --raw 255,179,255,255,255,255\n"
               "  linkerbot-o6 grasp --ball 6 --strength 150   (grasp a tennis ball)\n"
               "  linkerbot-o6 grasp --release                  (let go)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--side", choices=["left", "right"], default="left", help="hand CAN ID (default left=0x28)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="health check (serial, faults, temps, positions)")
    sub.add_parser("pos", help="read current joint positions")

    m = sub.add_parser("move", help="move the hand")
    m.add_argument("--pos", help="6 percent values, comma-separated (0-100)")
    m.add_argument("--raw", help="6 raw values 0-255 (hardware scale)")
    m.add_argument("--preset", choices=sorted(PRESETS_RAW), help=f"named preset: {sorted(PRESETS_RAW)}")
    m.add_argument("--speed", type=int, default=50, help="speed 0-255 (default 50, gentle)")
    m.add_argument("--torque", type=int, default=None, help="torque limit 0-255 (default unchanged)")
    m.add_argument("--wait", type=float, default=0, help="seconds to hold pose before readback")
    m.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    g = sub.add_parser("grasp", help="grasp/hold a ball-sized object")
    g.add_argument("--ball", type=float, default=6.0, help="ball diameter in cm (default 6)")
    g.add_argument("--strength", type=int, default=150, help="grip strength / torque 0-255 (default 150)")
    g.add_argument("--speed", type=int, default=40, help="closing speed 0-255 (default 40)")
    g.add_argument("--release", action="store_true", help="open the hand to release")
    g.add_argument("--yes", action="store_true", help="skip confirmation prompt")

    args = ap.parse_args(argv)

    print("Opening CAN bus (PCAN-USB @ 1 Mbit/s)...")
    try:
        hand = LinkerHand(side=args.side)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1

    try:
        if args.cmd == "probe":
            return cmd_probe(hand)
        if args.cmd == "pos":
            return cmd_pos(hand)
        if args.cmd == "move":
            return cmd_move(hand, args)
        if args.cmd == "grasp":
            return cmd_grasp(hand, args)
        return 0
    finally:
        hand.close()


if __name__ == "__main__":
    sys.exit(main())
