#!/usr/bin/env python3
"""Haltech ECU protocol POC.

What this script does:
- builds the protocol frames we currently understand with confidence
- prints the live-capture 0x0B selector groups
- can optionally send frames over a serial port if pyserial is installed

Current confidence map:
- 0x0B = DataRequest (selector table + checksum)
- 0x0C short probes include:
  - GetDTCs / DTC-status probe
  - EEPROMRangesChangedRequest with zeroed range/address fields
- 0x01 = ECUIDRequest
- 0x36 = ECUDescriptorsRequest

This is intentionally conservative: no guessed baud rate, no guessed framing.
You must supply the serial port and baud rate when you want to talk to hardware.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Iterable, Sequence


def u8_sum(data: bytes) -> int:
    return sum(data) & 0xFF


def parse_int(s: str) -> int:
    s = s.strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s)


def parse_int_list(values: Sequence[str]) -> list[int]:
    out: list[int] = []
    for v in values:
        if not v:
            continue
        for part in v.replace(",", " ").split():
            out.append(parse_int(part))
    return out


def hx(data: bytes) -> str:
    return data.hex().upper()


def words_from_bytes(data: bytes) -> list[int]:
    if len(data) % 2:
        raise ValueError(f"expected even number of bytes, got {len(data)}")
    return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]


def bytes_from_words(words: Iterable[int]) -> bytes:
    buf = bytearray()
    for w in words:
        if not 0 <= w <= 0xFFFF:
            raise ValueError(f"word out of range: {w!r}")
        buf.append((w >> 8) & 0xFF)
        buf.append(w & 0xFF)
    return bytes(buf)


def build_data_request(req_id: int, selector_ids: Sequence[int]) -> bytes:
    selector_bytes = bytes_from_words(selector_ids)
    body = bytes([0x0B, req_id & 0xFF, len(selector_bytes) & 0xFF]) + selector_bytes
    return body + bytes([u8_sum(body)])


def build_simple_request(cmd: int, req_id: int, body_bytes: Sequence[int]) -> bytes:
    body = bytes([cmd & 0xFF, req_id & 0xFF, *[b & 0xFF for b in body_bytes]])
    return body + bytes([u8_sum(body)])


LIVE_DATA_GROUPS = {
    0x72: [
        0x0080, 0x0081, 0x0084, 0x0085, 0x0087, 0x008A, 0x008B, 0x008C,
        0x00A4, 0x00E1, 0x00E4, 0x00E5, 0x00E6, 0x00EC, 0x00F2, 0x012F,
        0x0130, 0x0180, 0x0181, 0x0182, 0x0183, 0x0184, 0x0186, 0x0189,
        0x018A, 0x018C, 0x0195, 0x0197, 0x01AF, 0x01DF, 0x01E1, 0x01E2,
    ],
    0x73: [
        0x0201, 0x0202, 0x022B, 0x0240, 0x0241, 0x0242, 0x0280, 0x0281,
        0x0282, 0x0283, 0x0284, 0x0285, 0x0286, 0x0287, 0x0288, 0x0289,
        0x0294, 0x0295, 0x0296, 0x02E0, 0x02E1, 0x02E2, 0x02F8, 0x02F9,
        0x02FA, 0x0442, 0x0443, 0x0444, 0x0445, 0x0446, 0x0447,
    ],
    0x74: [
        0x0448, 0x0449, 0x044A, 0x044E, 0x044F, 0x0450, 0x0451, 0x0452,
        0x0453, 0x0472, 0x0473, 0x0474, 0x0475, 0x0476, 0x0477, 0x0478,
        0x0479, 0x047A, 0x047E, 0x047F, 0x0480, 0x0481, 0x0482, 0x0483,
        0x04D8, 0x04D9, 0x04DA, 0x04DB, 0x04DC, 0x04DD, 0x04DE, 0x04DF,
    ],
    0x75: [
        0x04E0, 0x04E4, 0x04E5, 0x04E6, 0x04E7, 0x04E8, 0x04E9,
        0x054B, 0x054C, 0x054D, 0x05B5, 0x05B6,
    ],
}


def print_groups() -> None:
    for req_id, ids in LIVE_DATA_GROUPS.items():
        frame = build_data_request(req_id, ids)
        print(f"0x0B req=0x{req_id:02X} count={len(ids)} bytes={len(frame)}")
        print(f"  frame: {hx(frame)}")
        print(f"  ids  : {' '.join(f'{w:04X}' for w in ids)}")


def print_examples() -> None:
    # The two confirmed 0x0C probe shapes from the live trace.
    get_dtc = build_simple_request(0x0C, 0x71, [0x01, 0x03])
    eeprom_ranges_zero = build_simple_request(0x0C, 0x76, [0x06, 0x05, 0x00, 0x00, 0x00, 0x00])
    ecu_id = build_simple_request(0x01, 0x71, [])
    ecu_desc = build_simple_request(0x36, 0x71, [])
    data_log_status = build_simple_request(0x33, 0x77, [])
    print(f"0x0C/GetDTCs probe: {hx(get_dtc)}")
    print(f"0x0C/EEPROMRangesChangedRequest(zeros): {hx(eeprom_ranges_zero)}")
    print(f"0x01/ECUIDRequest: {hx(ecu_id)}")
    print(f"0x36/ECUDescriptorsRequest: {hx(ecu_desc)}")
    print(f"0x33/DataLogStatusRequest: {hx(data_log_status)}")


def open_serial(port: str, baud: int):
    try:
        import serial  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "pyserial is not installed. Install it or use --demo/--hex-only. "
            f"Import error: {e}"
        )
    ser = serial.Serial(port=port, baudrate=baud, timeout=1)
    return ser


def read_reply(ser, max_bytes: int = 256) -> bytes:
    buf = bytearray()
    while len(buf) < max_bytes:
        chunk = ser.read(1)
        if not chunk:
            break
        buf.extend(chunk)
        # Heuristic: most responses in the live capture are short and
        # end with checksum + FF FF sync/idle bytes.
        if len(buf) >= 3 and buf[-2:] == b"\xff\xff":
            break
    return bytes(buf)


def cmd_send(args: argparse.Namespace) -> int:
    if args.kind == "data":
        if args.selectors:
            ids = parse_int_list(args.selectors)
        elif args.group is not None:
            ids = LIVE_DATA_GROUPS[args.group]
        else:
            raise SystemExit("provide --group or at least one selector id")
        frame = build_data_request(args.req_id, ids)
    elif args.kind == "raw":
        frame = bytes.fromhex(args.hex_data)
    elif args.kind == "get-dtcs":
        frame = build_simple_request(0x0C, args.req_id, [0x01, 0x03])
    elif args.kind == "eeprom-ranges":
        frame = build_simple_request(0x0C, args.req_id, [0x06, 0x05, 0x00, 0x00, 0x00, 0x00])
    elif args.kind == "data-log-status":
        frame = build_simple_request(0x33, args.req_id, [])
    else:
        raise SystemExit(f"unknown kind: {args.kind}")

    print(f"TX {hx(frame)}")
    if args.hex_only:
        return 0

    ser = open_serial(args.port, args.baud)
    try:
        ser.write(frame)
        ser.flush()
        reply = read_reply(ser)
        print(f"RX {hx(reply)}")
    finally:
        ser.close()
    return 0


def cmd_decode(args: argparse.Namespace) -> int:
    data = bytes.fromhex(args.hex_data)
    print(f"len={len(data)} hex={hx(data)}")
    if not data:
        return 0
    cmd = data[0]
    req = data[1] if len(data) > 1 else None
    print(f"cmd=0x{cmd:02X} req={('0x%02X' % req) if req is not None else 'n/a'}")
    if cmd == 0x0B and len(data) >= 4:
        n = data[2]
        payload = data[3:-1]
        print(f"0x0B payload_bytes={n} selector_words={n // 2} checksum=0x{data[-1]:02X}")
        if len(payload) == n:
            try:
                ids = words_from_bytes(payload)
                print("ids:", " ".join(f"{w:04X}" for w in ids))
            except Exception as e:
                print(f"payload decode error: {e}")
    elif cmd == 0x0C:
        print("0x0C short control/status probe")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Haltech ECU protocol POC")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("groups", help="print live-capture 0x0B selector groups")
    sub.add_parser("examples", help="print confirmed example frames")

    s = sub.add_parser("decode", help="decode a raw hex frame")
    s.add_argument("hex_data", help="hex string, spaces allowed")
    s.set_defaults(func=cmd_decode)

    s = sub.add_parser("send", help="send a frame to a serial port")
    s.add_argument("--port", required=True, help="serial port, e.g. COM4 or /dev/ttyUSB0")
    s.add_argument("--baud", type=int, required=True, help="baud rate (not yet confirmed; user supplies)")
    s.add_argument("--hex-only", action="store_true", help="build TX and stop before opening serial")
    s.add_argument("kind", choices=["data", "get-dtcs", "eeprom-ranges", "data-log-status", "raw"], help="frame type")
    s.add_argument("--group", type=lambda s: int(s, 0), help="live 0x0B group id, e.g. 0x72")
    s.add_argument("--req-id", type=lambda s: int(s, 0), default=0x71, help="request id byte")
    s.add_argument("--selectors", nargs="*", help="selector IDs for data requests, e.g. 0x80 0x81 ...")
    s.add_argument("--hex-data", help="hex payload for raw mode")
    s.set_defaults(func=cmd_send)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "groups":
        print_groups()
        return 0
    if args.cmd == "examples":
        print_examples()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
