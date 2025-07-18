# fancli.py – TR198A Ceiling‑Fan control via Broadlink RM‑series
"""
A **single‑file** module that can be used either:

1. As a *command‑line* utility – generate new remote IDs, pair them to a fan, or
   send operational commands (speed, direction, lights, etc.).
2. As a *Python library* reusable from Home Assistant (or any other) code.

The file purposely keeps *zero* external imports except for the optional
``broadlink`` package.  All timings, bit‑packing logic and RF‑packet building
come straight from the vendor reverse‑engineering you already verified, so the
behaviour is identical to the two standalone scripts you provided – just
consolidated and lightly refactored.

Usage (CLI)
===========
::

    # Generate a brand‑new handset ID (13‑bit random number)
    $ python fancli.py gen‑id
    0x15a9

    # Build & print the 10× pairing packet for that ID
    $ python fancli.py pair 0x15a9
    26c9b2... (hex)

    # Send a speed‑5, forward‑rotation command (requires --host)
    $ python fancli.py cmd 0x15a9 --speed 5 --direction forward \
                       --host 192.168.1.42

Library example
===============
```python
from fancli import build_payload, build_rf_packet, send_packet, Dir

packet = build_rf_packet(
    build_payload(0x15A9, speed=3, direction="forward"),
)
send_packet(packet, host="192.168.1.42")
```
"""
from __future__ import annotations

import argparse
import random
import sys
import textwrap
from typing import Iterable, List, Optional, Sequence, Union, Literal

try:
    import broadlink  # type: ignore
except ImportError:  # noqa: D401 – broadlink is optional until you actually send
    broadlink = None  # type: ignore

# ────────────────────────────── 1.  Command codec  ────────────────────────────

Dir = Literal["forward", "reverse"]
DimDir = Optional[Literal["up", "down"]]
Breeze = Optional[Literal[1, 2, 3]]  # natural‑wind modes
Timer = Optional[Literal[2, 4, 8]]   # hours


def _dir_bits(direction: Dir) -> int:  # bits 5‑4
    return 0b10 if direction.startswith("f") else 0b01


def _speed_bits(speed: int | None, breeze: Breeze) -> int:  # bits 9‑6
    if breeze:
        return {1: 0b1011, 2: 0b1111, 3: 0b1101}[breeze]
    if speed is None:
        return 0
    if speed < 0 or speed > 10:
        raise ValueError("speed out of range 0‑10")
    return speed


def _low_bits(light: bool, dim: DimDir, timer: Timer) -> int:  # bits 3‑0
    b3 = 1 if timer else 0
    b2 = 1 if (timer == 8 or (not timer and light)) else 0
    b1 = 1 if (timer == 2 or (not timer and dim)) else 0
    b0 = 1 if (dim == "down") else 0
    return (b3 << 3) | (b2 << 2) | (b1 << 1) | b0


def build_payload(
    tx_id: int,
    *,
    speed: int | None = None,
    direction: Dir = "reverse",
    light_toggle: bool = False,
    dim: DimDir = None,
    timer: Timer = None,
    breeze: Breeze = None,
) -> int:
    """Return the *23‑bit* payload (no sync, no trailing zeros)."""
    if not 0 <= tx_id <= 0x1FFF:
        raise ValueError("tx_id must fit in 13 bits (0‑0x1FFF)")

    payload = (tx_id << 10)
    payload |= (_speed_bits(speed, breeze) << 6)
    payload |= (_dir_bits(direction) << 4)
    payload |= _low_bits(light_toggle, dim, timer)

    return payload & 0x7FFFFF  # force to 23 bits


def build_pairing_payload(tx_id: int) -> int:
    """Return the 23‑bit pairing payload."""
    if not 0 <= tx_id <= 0x1FFF:
        raise ValueError("tx_id must fit in 13 bits (0‑0x1FFF)")
    pairing_bits = 0b1111000000  # per reverse‑engineering notes
    return (tx_id << 10) | pairing_bits


# ────────────────────────────── 2.  RF packet builder  ─────────────────────────
TICK_US = 32.84  # Broadlink time‑unit

# handset defaults – can be overridden on build_rf_packet()
HEADER_RF_433 = b"\xB2"
MARK0_US, SPACE0_US = 394, 755  # logical 0 (12u, 23u)
MARK1_US, SPACE1_US = 755, 394  # logical 1 (23u, 12u)
LEAD_IN_US = 1_336_916
INITIAL_GAP_US = 92_805  # fan‑specific tiny gap
FIRST_PREAMBLE_US: Sequence[int] = (
    MARK1_US,
    SPACE1_US,
    MARK1_US,
)
PREAMBLE_US: Sequence[int] = (
    MARK1_US,
    SPACE1_US,
    MARK0_US,
    SPACE0_US,
    MARK0_US,
    SPACE0_US,
)
INTER_GAP_US: Sequence[int] = (11_822, SPACE1_US)
TRAILER_US = 49_260
REPEATS = 5
RADIO_REPEATS = 0xC0  # Broadlink repeat field for radio packets


# — helpers ————————————————————————————————————————————————————————
_bits = str  # alias just for readability


def _ceil_tick(us: float) -> int:
    return int(round(us / TICK_US))


def _normalise_to_bits(src: Union[str, bytes, bytearray, Sequence[int]]) -> _bits:
    if isinstance(src, str):
        s = src.strip().lower().replace("0x", "")
        return s if set(s) <= {"0", "1"} else bin(int(s, 16))[2:]
    if isinstance(src, (bytes, bytearray)):
        iterable: Iterable[int] = src
    else:
        iterable = src
    return "".join(f"{b:08b}" for b in iterable)


def _bits_to_pulses(bits: _bits, mark0: int, space0: int, mark1: int, space1: int) -> List[int]:
    pulses: List[int] = []
    for bit in bits:
        pulses += (mark0, space0) if bit == "0" else (mark1, space1)
    return pulses


def _encode(pulses_us: Sequence[int], repeat: int) -> bytearray:
    buf = bytearray(b"\x26\x00\x00\x00")  # IR placeholder; will patch below
    for us in pulses_us:
        t = _ceil_tick(us)
        if t >= 256:
            buf += b"\x00" + t.to_bytes(2, "big")
        else:
            buf.append(t)
    buf[2:4] = (len(buf) - 4).to_bytes(2, "little")  # length
    buf[0] = HEADER_RF_433[0]  # flip to RF
    buf[1] = repeat & 0xFF     # Broadlink repeat field
    return buf


def build_rf_packet(
    payload_bits: Union[str, bytes, bytearray, Sequence[int]],
    *,
    pair: bool = False,
    repeats: int = REPEATS,
    radio_repeats: int = RADIO_REPEATS,
    lead_in_us: int = LEAD_IN_US,
    initial_gap_us: int = INITIAL_GAP_US,
    inter_gap_us: Sequence[int] = INTER_GAP_US,
    trailer_us: int = TRAILER_US,
    mark0_us: int = MARK0_US,
    space0_us: int = SPACE0_US,
    mark1_us: int = MARK1_US,
    space1_us: int = SPACE1_US,
    first_preamble_us: Sequence[int] = FIRST_PREAMBLE_US,
    preamble_us: Sequence[int] = PREAMBLE_US,
) -> bytes:
    """Convert a *bitstring* into a Broadlink RF packet ready for send_data()."""
    bits = _normalise_to_bits(payload_bits)
    frame = _bits_to_pulses(bits, mark0_us, space0_us, mark1_us, space1_us)

    pulses: List[int] = [lead_in_us]
    if initial_gap_us:
        pulses.append(initial_gap_us)
    pulses += list(first_preamble_us) + frame

    for _ in range(repeats - 1):
        pulses += list(inter_gap_us) + list(preamble_us) + frame

    if not pair:
        pulses.append(trailer_us)

    repeat_flag = 0xC9 if pair else radio_repeats  # Broadlink‑specific byte
    return bytes(_encode(pulses, repeat_flag))


def build_pair_packet(bits: Union[str, bytes, bytearray, Sequence[int]], *, repeats: int = 10) -> bytes:  # noqa: D401
    """Shortcut for a *pairing* packet (ten repeats, special gap)."""
    return build_rf_packet(bits, pair=True, repeats=repeats)


# ────────────────────────────── 3.  Device helper  ────────────────────────────

def send_packet(packet: bytes, *, host: str, timeout: int = 10) -> None:  # noqa: D401
    """Send *packet* to an RM‑pro device.  Requires the *broadlink* package."""
    if broadlink is None:
        raise RuntimeError("broadlink python package not installed – pip install broadlink")
    dev = broadlink.hello(host)
    dev.auth()
    dev.send_data(packet)


# ────────────────────────────── 4.  Human helpers  ────────────────────────────

def bits23(n: int) -> str:
    return f"{n:023b}"


def hex23(n: int) -> str:
    return hex(n)


# ────────────────────────────── 5.  CLI  ──────────────────────────────────────

def _add_common_cmd_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("tx_id", type=lambda s: int(s, 0), help="13‑bit handset ID (e.g. 0x15A9)")
    p.add_argument("--host", help="Broadlink RM‑pro IP address")
    p.add_argument("--send", action="store_true", help="Actually transmit via RM‑pro")


def cli(argv: Sequence[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="fancli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """
            TR198A ceiling‑fan control utility.

            You can **generate IDs**, **pair** them with a fan, or **send commands**.
            If --send is omitted the packet is printed so you can use it elsewhere.
            """
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gen-id", help="Generate a new random 13‑bit handset ID")

    pr = sub.add_parser("pair", help="Send / show the pairing packet")
    _add_common_cmd_args(pr)

    cmd = sub.add_parser("cmd", help="Send / show an operational command")
    _add_common_cmd_args(cmd)
    cmd.add_argument("--speed", type=int, choices=range(0, 11), metavar="0‑10")
    cmd.add_argument("--direction", choices=["forward", "reverse"], default="reverse")
    cmd.add_argument("--light", action="store_true", help="Toggle light")
    cmd.add_argument("--dim", choices=["up", "down"])
    cmd.add_argument("--dim-steps", type=int, default=1, choices=range(1, 11), metavar="N",
                      help="Number of dim steps to send (requires --dim)")
    cmd.add_argument("--timer", type=int, choices=[2, 4, 8], metavar="HOURS")
    cmd.add_argument("--breeze", type=int, choices=[1, 2, 3])

    args = parser.parse_args(argv)

    if args.cmd == "gen-id":
        tx_id = random.randint(0, 0x1FFF)
        print(hex(tx_id))
        return

    tx_id: int = args.tx_id

    if args.cmd == "pair":
        payload = bits23(build_pairing_payload(tx_id))
        packet = build_pair_packet(payload)

    else:
        if args.dim_steps>1 and not args.dim:
            parser.error("--dim-steps requires --dim")
        radio_repeats = RADIO_REPEATS
        trailer_us = TRAILER_US
        if args.dim and args.dim_steps:
            #scale radio repeates from 0xC9 to 0xEF based on dim_steps
            radio_repeats = 0xC9 + (args.dim_steps - 1) * 4
            trailer_us = 394
        payload = bits23(
            build_payload(
                tx_id,
                speed=args.speed,
                direction=args.direction,
                light_toggle=args.light,
                dim=args.dim,
                timer=args.timer,
                breeze=args.breeze,
            )
        )
        packet = build_rf_packet(payload, radio_repeats=radio_repeats, trailer_us=trailer_us)

    if args.send:
        if not args.host:
            parser.error("--send requires --host")
        send_packet(packet, host=args.host)
        print("Packet sent.")
    else:
        print("Bitstream:", payload)
        print("Broadlink packet ({} bytes):".format(len(packet)))
        print(packet.hex())



if __name__ == "__main__":
    cli()
