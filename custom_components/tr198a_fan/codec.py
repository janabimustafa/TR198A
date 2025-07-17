"""
Pure-python packet builder that returns **base64** packets ready for
homeassistant.remote.send_command(entity_id=…, command=[base64_str]).
No broadlink dependency.
"""
from __future__ import annotations
import base64
from typing import Optional, Sequence, Literal, Union, Iterable, List

Dir     = Literal["forward", "reverse"]
DimDir  = Optional[Literal["up", "down"]]
Breeze  = Optional[Literal[1, 2, 3]]
Timer   = Optional[Literal[2, 4, 8]]

# ───────── timing constants (identical to fancli) ──────────
TICK_US        = 32.84
HEADER_RF_433  = b"\xB2"
MARK0_US, SPACE0_US = 394, 755
MARK1_US, SPACE1_US = 755, 394
LEAD_IN_US          = 1_336_916
INITIAL_GAP_US      = 92_805
FIRST_PREAMBLE_US   = (MARK1_US, SPACE1_US, MARK1_US)
PREAMBLE_US         = (MARK1_US, SPACE1_US, MARK0_US, SPACE0_US,
                       MARK0_US, SPACE0_US)
INTER_GAP_US        = (11_822, SPACE1_US)
TRAILER_US          = 397
REPEATS             = 5
RADIO_REPEATS       = 0xC0

# ───────── bit helpers ──────────
def _dir_bits(direction: Dir) -> int:
    return 0b10 if direction.startswith("f") else 0b01

def _speed_bits(speed: int | None, breeze: Breeze) -> int:
    if breeze:
        return {1: 0b1101, 2: 0b1111, 3: 0b1110}[breeze]
    if speed is None:
        return 0
    if not 0 <= speed <= 10:
        raise ValueError("speed out of range 0-10")
    return speed

def _low_bits(light: bool, dim: DimDir, timer: Timer) -> int:
    b3 = 1 if timer else 0
    b2 = 1 if (timer == 8 or (not timer and light)) else 0
    b1 = 1 if (timer == 2 or (not timer and dim)) else 0
    b0 = 1 if (dim == "down") else 0
    return (b3 << 3) | (b2 << 2) | (b1 << 1) | b0

# ───────── public helpers ──────────
def build_payload(
    handset_id: int,
    *,
    speed: int | None = None,
    direction: Dir = "reverse",
    light_toggle: bool = False,
    dim: DimDir = None,
    timer: Timer = None,
    breeze: Breeze = None,
) -> str:
    """Return 23-bit payload as **bitstring**."""
    if not 0 <= handset_id <= 0x1FFF:
        raise ValueError("handset_id must fit in 13 bits")
    p = (handset_id << 10)
    p |= (_speed_bits(speed, breeze) << 6)
    p |= (_dir_bits(direction) << 4)
    p |= _low_bits(light_toggle, dim, timer)
    return f"{p & 0x7FFFFF:023b}"

def build_pairing_payload(handset_id: int) -> str:
    return f"{((handset_id << 10) | 0b1111000000) & 0x7FFFFF:023b}"

# ───────── low-level RF encoding ──────────
def _ceil_tick(us: float) -> int:
    from math import ceil
    return int(round(us / TICK_US))

def _bits_to_pulses(bits: str,
                    m0:int, s0:int, m1:int, s1:int) -> List[int]:
    out = []
    for b in bits:
        out += (m0, s0) if b == "0" else (m1, s1)
    return out

def _encode(pulses: Sequence[int], repeat_byte: int) -> bytes:
    buf = bytearray(b"\x26\x00\x00\x00")     # IR placeholder
    for us in pulses:
        t = _ceil_tick(us)
        if t >= 256:
            buf += b"\x00" + t.to_bytes(2, "big")
        else:
            buf.append(t)
    buf[2:4] = (len(buf)-4).to_bytes(2, "little")
    buf[0] = HEADER_RF_433[0]
    buf[1] = repeat_byte & 0xFF
    return bytes(buf)

def build_rf_packet(bits: str, *,
                    pair: bool = False,
                    repeats: int = REPEATS,
                    radio_repeats: int = RADIO_REPEATS,
                    trailer_us: int = TRAILER_US) -> bytes:
    frame = _bits_to_pulses(bits, MARK0_US, SPACE0_US, MARK1_US, SPACE1_US)
    pulses = [LEAD_IN_US, INITIAL_GAP_US, *FIRST_PREAMBLE_US, *frame]
    for _ in range(repeats-1):
        pulses += [*INTER_GAP_US, *PREAMBLE_US, *frame]
    if not pair:
        pulses.append(trailer_us)
    return _encode(pulses, 0xC9 if pair else radio_repeats)

# ───────── top-level helpers HA will call ──────────
def build_base64_command(packet: bytes) -> str:
    return 'b64:' + base64.b64encode(packet).decode()

def build_operational_command(
    handset_id: int,
    *,
    speed: int | None = None,
    direction: Dir = "reverse",
    light_toggle: bool = False,
    dim: DimDir = None,
    timer: Timer = None,
    breeze: Breeze = None,
    radio_repeats: int = RADIO_REPEATS,
    trailer_us: int = TRAILER_US,
) -> str:
    """Build a base64-encoded RF packet for an operational command."""
    bits = build_payload(
        handset_id,
        speed=speed,
        direction=direction,
        light_toggle=light_toggle,
        dim=dim,
        timer=timer,
        breeze=breeze,
    )
    pkt = build_rf_packet(
        bits,
        radio_repeats=radio_repeats,
        trailer_us=trailer_us,
    )
    return build_base64_command(pkt)

def build_pair_command(handset_id: int) -> str:
    bits = build_pairing_payload(handset_id)
    pkt  = build_rf_packet(bits, pair=True, repeats=10)
    return build_base64_command(pkt)