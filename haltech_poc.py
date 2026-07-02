#!/usr/bin/env python3
"""Haltech ECU protocol POC.

What this script does:
- builds the protocol frames we currently understand with confidence
- prints the live-capture 0x0B selector groups
- can optionally send frames over a serial port if pyserial is installed
- can run a live polling loop against the ECU on this machine

Current confidence map:
- 0x0B = DataRequest (selector table + checksum)
- 0x0C short probes include:
  - GetDTCs / DTC-status probe
  - EEPROMRangesChangedRequest with zeroed range/address fields
- 0x01 = ECUIDRequest
- 0x33 = DataLogStatusRequest
- 0x36 = ECUDescriptorsRequest

This is intentionally conservative: no guessed baud rate, no guessed framing.
You must supply the serial port and baud rate when you want to talk to hardware.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class LiveGroup:
    req_id: int
    selectors: tuple[int, ...]


@dataclass(frozen=True)
class CaptureEvent:
    kind: str
    req_id: int
    selectors: tuple[int, ...] = ()
    values: tuple[int, ...] = ()
    source: str = ""


LIVE_GROUPS: tuple[LiveGroup, ...] = (
    LiveGroup(0x72, (
        0x0080, 0x0081, 0x0084, 0x0085, 0x0087, 0x008A, 0x008B, 0x008C,
        0x00A4, 0x00E1, 0x00E4, 0x00E5, 0x00E6, 0x00EC, 0x00F2, 0x012F,
        0x0130, 0x0180, 0x0181, 0x0182, 0x0183, 0x0184, 0x0186, 0x0189,
        0x018A, 0x018C, 0x0195, 0x0197, 0x01AF, 0x01DF, 0x01E1, 0x01E2,
    )),
    LiveGroup(0x73, (
        0x0201, 0x0202, 0x022B, 0x0240, 0x0241, 0x0242, 0x0280, 0x0281,
        0x0282, 0x0283, 0x0284, 0x0285, 0x0286, 0x0287, 0x0288, 0x0289,
        0x0294, 0x0295, 0x0296, 0x02E0, 0x02E1, 0x02E2, 0x02F8, 0x02F9,
        0x02FA, 0x0442, 0x0443, 0x0444, 0x0445, 0x0446, 0x0447,
    )),
    LiveGroup(0x74, (
        0x0448, 0x0449, 0x044A, 0x044E, 0x044F, 0x0450, 0x0451, 0x0452,
        0x0453, 0x0472, 0x0473, 0x0474, 0x0475, 0x0476, 0x0477, 0x0478,
        0x0479, 0x047A, 0x047E, 0x047F, 0x0480, 0x0481, 0x0482, 0x0483,
        0x04D8, 0x04D9, 0x04DA, 0x04DB, 0x04DC, 0x04DD, 0x04DE, 0x04DF,
    )),
    LiveGroup(0x75, (
        0x04E0, 0x04E4, 0x04E5, 0x04E6, 0x04E7, 0x04E8, 0x04E9,
        0x054B, 0x054C, 0x054D, 0x05B5, 0x05B6,
    )),
)

LIVE_DATA_GROUPS = {g.req_id: list(g.selectors) for g in LIVE_GROUPS}


def selector_label(selector_id: int, labels: dict[int, str] | None = None) -> str:
    if labels and selector_id in labels:
        return labels[selector_id]
    return f"selector_0x{selector_id:04X}"


def pair_selectors_with_values(selectors: Sequence[int], payload: bytes) -> list[tuple[int, int]]:
    values = words_from_bytes(payload)
    if len(values) != len(selectors):
        raise ValueError(f"selector/value count mismatch: {len(selectors)} selectors vs {len(values)} values")
    return list(zip(selectors, values))


def format_selector_values(
    selectors: Sequence[int],
    payload: bytes,
    labels: dict[int, str] | None = None,
    *,
    nonzero_only: bool = False,
) -> str:
    parts: list[str] = []
    for selector_id, value in pair_selectors_with_values(selectors, payload):
        if nonzero_only and value == 0:
            continue
        parts.append(f"{selector_label(selector_id, labels)}=0x{value:04X}")
    return " ".join(parts) if parts else "(all zero)"


def build_data_request(req_id: int, selector_ids: Sequence[int]) -> bytes:
    selector_bytes = bytes_from_words(selector_ids)
    body = bytes([0x0B, req_id & 0xFF, len(selector_bytes) & 0xFF]) + selector_bytes
    return body + bytes([u8_sum(body)])


def build_simple_request(cmd: int, req_id: int, body_bytes: Sequence[int]) -> bytes:
    body = bytes([cmd & 0xFF, req_id & 0xFF, *[b & 0xFF for b in body_bytes]])
    return body + bytes([u8_sum(body)])


def print_groups() -> None:
    for req_id, ids in LIVE_DATA_GROUPS.items():
        frame = build_data_request(req_id, ids)
        print(f"0x0B req=0x{req_id:02X} count={len(ids)} bytes={len(frame)}")
        print(f"  frame: {hx(frame)}")
        print(f"  ids  : {' '.join(f'{w:04X}' for w in ids)}")


def print_examples() -> None:
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


def load_labels(path: str | None) -> dict[int, str]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text())
    labels: dict[int, str] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            label = value
        elif isinstance(value, dict):
            label = str(value.get("name") or value.get("label") or value.get("title") or value)
        else:
            label = str(value)
        labels[parse_int(str(key))] = label
    return labels


def open_serial(port: str, baud: int):
    try:
        import serial  # type: ignore
    except Exception as e:  # pragma: no cover
        raise SystemExit(
            "pyserial is not installed. Install it or use --hex-only. "
            f"Import error: {e}"
        )
    return serial.Serial(port=port, baudrate=baud, timeout=1)


def read_reply(ser) -> bytes:
    """Read one length-prefixed frame.

    The observed frames use byte 2 as a payload byte count, so the full frame
    length is 3 + payload_len + 1 checksum bytes.
    """
    head = ser.read(3)
    if len(head) < 3:
        return bytes(head)
    payload_len = head[2]
    tail = ser.read(payload_len + 1)
    return bytes(head + tail)


def describe_frame(data: bytes) -> str:
    if len(data) < 4:
        return hx(data)
    cmd = data[0]
    req = data[1]
    payload_len = data[2]
    payload = data[3:-1]
    checksum = data[-1]
    parts = [f"cmd=0x{cmd:02X}", f"req=0x{req:02X}", f"len={payload_len}", f"checksum=0x{checksum:02X}"]
    if len(payload) == payload_len and payload_len:
        parts.append(f"payload={hx(payload)}")
        if payload_len % 2 == 0:
            try:
                parts.append("words=" + " ".join(f"{w:04X}" for w in words_from_bytes(payload)))
            except Exception:
                pass
    return " ".join(parts)


def send_and_receive(ser, frame: bytes) -> bytes:
    ser.write(frame)
    ser.flush()
    return read_reply(ser)


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
        reply = send_and_receive(ser, frame)
        print(f"RX {hx(reply)}")
        print(f"RXD {describe_frame(reply)}")
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


def cmd_live(args: argparse.Namespace) -> int:
    labels = load_labels(args.labels)
    groups = LIVE_GROUPS
    if args.groups:
        wanted = {parse_int(g) for g in args.groups}
        groups = tuple(g for g in LIVE_GROUPS if g.req_id in wanted)
        missing = wanted - {g.req_id for g in groups}
        if missing:
            raise SystemExit(f"unknown live groups: {', '.join(f'0x{x:02X}' for x in sorted(missing))}")

    ser = open_serial(args.port, args.baud)
    try:
        if not args.no_status:
            status_frame = build_simple_request(0x33, args.req_id, [])
            status_reply = send_and_receive(ser, status_frame)
            print(f"STATUS TX {hx(status_frame)}")
            print(f"STATUS RX {hx(status_reply)}")
            print(f"STATUS RXD {describe_frame(status_reply)}")

        for cycle in range(args.cycles):
            if cycle:
                time.sleep(args.delay)
            print(f"-- cycle {cycle + 1}/{args.cycles} --")
            for group in groups:
                frame = build_data_request(args.req_id, group.selectors)
                reply = send_and_receive(ser, frame)
                print(f"GROUP 0x{group.req_id:02X} TX {hx(frame)}")
                print(f"GROUP 0x{group.req_id:02X} RX {hx(reply)}")
                print(f"GROUP 0x{group.req_id:02X} RXD {describe_frame(reply)}")
                if len(reply) >= 4 and reply[0] == 0x0B and reply[1] == (args.req_id & 0xFF):
                    payload = reply[3:-1]
                    if len(payload) == reply[2]:
                        print(
                            f"GROUP 0x{group.req_id:02X} VALUES "
                            f"{format_selector_values(group.selectors, payload, labels, nonzero_only=args.nonzero_only)}"
                        )
                print()
    finally:
        ser.close()
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
    s.add_argument("--baud", type=int, default=57600, help="baud rate (defaults to confirmed 57600)")
    s.add_argument("--hex-only", action="store_true", help="build TX and stop before opening serial")
    s.add_argument("kind", choices=["data", "get-dtcs", "eeprom-ranges", "data-log-status", "raw"], help="frame type")
    s.add_argument("--group", type=lambda s: int(s, 0), help="live 0x0B group id, e.g. 0x72")
    s.add_argument("--req-id", type=lambda s: int(s, 0), default=0x71, help="request id byte")
    s.add_argument("--selectors", nargs="*", help="selector IDs for data requests, e.g. 0x80 0x81 ...")
    s.add_argument("--hex-data", help="hex payload for raw mode")
    s.set_defaults(func=cmd_send)

    s = sub.add_parser("live", help="poll the ECU and print decoded live values")
    s.add_argument("--port", default="/dev/ttyUSB0", help="serial port (default: /dev/ttyUSB0)")
    s.add_argument("--baud", type=int, default=57600, help="baud rate (default: 57600)")
    s.add_argument("--req-id", type=lambda s: int(s, 0), default=0x77, help="request id byte")
    s.add_argument("--cycles", type=int, default=1, help="poll cycles to run")
    s.add_argument("--delay", type=float, default=0.2, help="delay between cycles in seconds")
    s.add_argument("--groups", nargs="*", help="optional subset of live groups, e.g. 0x72 0x73")
    s.add_argument("--labels", help="optional JSON file mapping selector ids to channel names")
    s.add_argument("--nonzero-only", action="store_true", help="hide zero-value channels")
    s.add_argument("--no-status", action="store_true", help="skip the initial 0x33 status probe")
    s.set_defaults(func=cmd_live)

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
