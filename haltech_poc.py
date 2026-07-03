#!/usr/bin/env python3
"""Haltech ECU protocol POC.

What this script does:
- builds the protocol frames we currently understand with confidence
- prints the live-capture 0x0B selector groups
- can optionally send frames over a serial port if pyserial is installed
- can run a live polling loop against the ECU on this machine
- can replay and diff saved capture logs without hardware

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
import struct
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
SELECTOR_GROUPS = {g.selectors: g.req_id for g in LIVE_GROUPS}


# Wire selector → internal channel mappings (from DLL analysis)
# Group 1: 0x0080-0x00FF -> Internal 0x0000-0x007F (offset 0x0080)
WIRE_TO_INTERNAL_GROUP1 = {
    0x0080: 0x0000,  # BaseFuel
    0x0081: 0x0001,  # BaseIgnition
    0x0084: 0x0004,  # TargetAFR
    0x0085: 0x0005,  # InjectorDeadTime
    0x0087: 0x0007,  # FuelFiringAngle
    0x008A: 0x000A,  # FuelPrimePulse
    0x008C: 0x000C,  # FuelCrankingInjectionTime
}

# Group 2: 0x0294-0x0296 -> Internal 0x0004-0x0006 (offset 0x0290)
WIRE_TO_INTERNAL_GROUP2 = {
    0x0294: 0x0004,  # TargetAFR
    0x0295: 0x0005,  # InjectorDeadTime
    0x0296: 0x0006,  # InjectorSize
}

# Group 3: 0x0442-0x0447 -> Internal 0x0102-0x0107 (offset 0x0340)
WIRE_TO_INTERNAL_GROUP3 = {
    0x0442: 0x0102,  # LambdaSensor1
    0x0443: 0x0103,  # LambdaSensor2
    0x0444: 0x0104,  # AcceleratorPedal
    0x0445: 0x0105,  # FuelTemp
    0x0446: 0x0106,  # FuelPressure
    0x0447: 0x0107,  # OilTemp
}

# Group 4: 0x0472-0x0475 -> Internal 0x0102-0x0105 (offset 0x0370)
WIRE_TO_INTERNAL_GROUP4 = {
    0x0472: 0x0102,  # LambdaSensor1
    0x0473: 0x0103,  # LambdaSensor2
    0x0474: 0x0104,  # AcceleratorPedal
    0x0475: 0x0105,  # FuelTemp
}

# All wire-to-internal mappings combined
WIRE_TO_INTERNAL = {**WIRE_TO_INTERNAL_GROUP1, **WIRE_TO_INTERNAL_GROUP2, **WIRE_TO_INTERNAL_GROUP3, **WIRE_TO_INTERNAL_GROUP4}

# Internal channel names (from ECUManagerEXE binary)
INTERNAL_CHANNEL_NAMES = {
    0x000: "BaseFuel",
    0x001: "BaseIgnition",
    0x002: "MAFFuel",
    0x003: "VolumetricEfficiency",
    0x004: "TargetAFR",
    0x005: "InjectorDeadTime",
    0x006: "InjectorSize",
    0x007: "FuelFiringAngle",
    0x008: "FuelPrimePulse",
    0x009: "FuelCrankingInjectionTime",
    0x010: "FuelPostStartEnrichment",
    0x011: "FuelCoolantTempCorrection",
    0x012: "FuelAirTempCorrection",
    0x013: "ZeroThrottleFuel",
    0x014: "FullThrottleFuel",
    0x015: "FuelBarometricCorrection",
    0x016: "FuelMAPCorrectiononTPS",
    0x017: "MAFLimit",
    0x018: "FuelEnrichSensitivity",
    0x019: "FuelEnrichClamp",
    0x020: "Injector1FuelTrim",
    0x021: "Injector2FuelTrim",
    0x022: "Injector3FuelTrim",
    0x023: "Injector4FuelTrim",
    0x024: "Injector5FuelTrim",
    0x025: "Injector6FuelTrim",
    0x026: "Injector7FuelTrim",
    0x027: "Injector8FuelTrim",
    0x028: "Injector9FuelTrim",
    0x029: "Injector10FuelTrim",
    0x030: "Injector11FuelTrim",
    0x031: "Injector12FuelTrim",
    0x032: "IgnitionDwellTime",
    0x033: "CrankIgnitionTiming",
    0x034: "IgnPostStartTimingOffset",
    0x035: "IgnitionCoolantTempCorrection",
    0x036: "IgnitionAirTempCorrection",
    0x037: "ZeroThrottleIgnitionTiming",
    0x038: "Ignition1TimingTrim",
    0x039: "Ignition2TimingTrim",
    0x040: "Ignition3TimingTrim",
    0x041: "Ignition4TimingTrim",
    0x042: "Ignition5TimingTrim",
    0x043: "Ignition6TimingTrim",
    0x044: "Ignition7TimingTrim",
    0x045: "Ignition8TimingTrim",
    0x046: "Ignition9TimingTrim",
    0x047: "Ignition10TimingTrim",
    0x048: "Ignition11TimingTrim",
    0x049: "Ignition12TimingTrim",
    0x050: "IntakeCamTargetAngle",
    0x051: "ExhaustCamTargetAngle",
    0x052: "DecelCutRPM",
    0x053: "TargetBoost",
    0x054: "BoostControlOutputStartPoint",
    0x055: "OpenLoopBoostControl",
    0x056: "IdleControlTargetRPM",
    0x057: "IdleControlOutputStartPoint",
    0x058: "KnockThreshold",
    0x059: "TransientThrottleIgnitionAdjustment",
    0x061: "Delta_Amount",
    0x062: "DecelDisEnrichment",
    0x063: "AccelEnrichDecay",
    0x064: "DecelDisEnrichDecay",
    0x065: "AccelIgnDecay",
    0x066: "TTCoolantCorr",
    0x067: "TriggerVoltageThreshold",
    0x068: "HomeVoltageThreshold",
    0x069: "TractionControlWheelSlipLimit",
    0x070: "IgnitionTimingSplit",
    0x071: "InjectorDeadTime_2",
    0x072: "InjectorFlowRate_2",
    0x073: "FuelFiringAngle_3",
    0x074: "InjectorDeadTime_3",
    0x075: "InjectorFlowRate_3",
    0x076: "FuelFiringAngle_3",
    0x077: "InjectorDeadTime_4",
    0x078: "InjectorFlowRate_4",
    0x079: "FuelFiringAngle_4",
    0x080: "ElectronicThrottleTargetOffset",
    0x081: "ElectronicThrottleMaxGradientPos",
    0x082: "ElectronicThrottleMaxGradientNeg",
    0x083: "IdleControlPostStartOffset",
    0x084: "IdleControlMinimumOutput",
    0x085: "TriggerAngle",
    0x086: "FlatShiftIgnDecay",
    0x087: "FuelEGTCorr",
    0x088: "FuelInjPressureDiffCorr",
    0x089: "TargetBoost_2",
    0x090: "BaseFuel_2",
    0x091: "BaseIgnition_2",
    0x092: "GenericDutyOutput",
    0x093: "InjAngleSplit",
    0x094: "StagingBar",
    0x095: "OilMeteringPump",
    0x096: "MAPSensor",
    0x097: "ThrottlePosition",
    0x098: "MAFCalibration",
    0x099: "MAPfromMAF",
    0x100: "AirTemp",
    0x101: "CoolantTemp",
    0x102: "LambdaSensor1",
    0x103: "LambdaSensor2",
    0x104: "AcceleratorPedal",
    0x105: "FuelTemp",
    0x106: "FuelPressure",
    0x107: "OilTemp",
    0x108: "OilPressure",
    0x109: "GSensor",
    0x110: "MAFCorrectionTable",
    0x111: "MAFCalibration2",
    0x112: "MAFCorrectionTable_2",
    0x113: "MAPClampTable",
    0x114: "ExhaustGasTemperature",
    0x115: "MAPSensor2",
    0x116: "MAPClampTable2",
    0x117: "MAFClampTable",
    0x160: "VTEC_Minimum_On_RPM",
    0x161: "IdleControlAirConRpmOffset",
    0x162: "IdleControlAirConStartPointOffset",
    0x163: "IdleControlPowerSteeringRpmOffset",
    0x164: "IdleControlPowerSteeringStartPointOffset",
    0x165: "IdleControlOpenLoopIgnCorrection",
    0x166: "O2ControlTargetVoltage",
    0x167: "O2ControlSampleRate",
    0x168: "O2ControlSensorWarmUpTime",
    0x175: "Fuel_Overall_Trim",
    0x176: "Ignition_Overall_Trim",
    0x196: "Magnitude_profile_1",
    0x197: "Bias_profile_1",
    0x198: "Slip_profile_1",
    0x199: "Magnitude_profile_2",
    0x200: "Bias_profile_2",
    0x201: "Slip_profile_2",
    0x202: "Magnitude_profile_3",
    0x203: "Bias_profile_3",
    0x204: "Slip_profile_3",
    0x205: "Magnitude_profile_4",
    0x206: "Bias_profile_4",
    0x207: "Slip_profile_4",
    0x208: "Magnitude_profile_5",
    0x209: "Bias_profile_5",
    0x210: "Slip_profile_5",
}

def wire_to_internal(wire_selector: int) -> int | None:
    """Convert wire selector ID to internal channel ID."""
    return WIRE_TO_INTERNAL.get(wire_selector)

def internal_to_name(internal_id: int) -> str | None:
    """Convert internal channel ID to human-readable name."""
    return INTERNAL_CHANNEL_NAMES.get(internal_id)

def wire_to_name(wire_selector: int) -> str | None:
    """Convert wire selector ID to human-readable name via internal channel ID."""
    internal_id = wire_to_internal(wire_selector)
    if internal_id is not None:
        return internal_to_name(internal_id)
    return None


def selector_label(selector_id: int, labels: dict[int, str] | None = None) -> str:
    if labels and selector_id in labels:
        return labels[selector_id]
    # Try internal channel name lookup via wire-to-internal mapping
    name = wire_to_name(selector_id)
    if name:
        return name
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


def format_selector_pairs(
    selectors: Sequence[int],
    values: Sequence[int],
    labels: dict[int, str] | None = None,
    *,
    nonzero_only: bool = False,
) -> str:
    parts: list[str] = []
    for selector_id, value in zip(selectors, values, strict=True):
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


CAPTURE_TX_RE = re.compile(r"^GROUP 0x(?P<req>[0-9A-F]{2}) TX (?P<hex>[0-9A-F]+)$")
CAPTURE_VALUES_RE = re.compile(r"^GROUP 0x(?P<req>[0-9A-F]{2}) VALUES (?P<body>.*)$")
CAPTURE_PAIR_RE = re.compile(r"(?P<label>.+?)=0x(?P<value>[0-9A-Fa-f]{1,4})(?=\s|$)")


def parse_capture_values(body: str) -> list[tuple[str, int]]:
    body = body.strip()
    if not body or body == "(all zero)":
        return []
    pairs: list[tuple[str, int]] = []
    for match in CAPTURE_PAIR_RE.finditer(body):
        pairs.append((match.group("label"), int(match.group("value"), 16)))
    return pairs


def parse_capture_tx(hex_data: str) -> tuple[int, tuple[int, ...]]:
    frame = bytes.fromhex(hex_data)
    if len(frame) < 4 or frame[0] != 0x0B:
        raise ValueError("not a data request frame")
    payload_len = frame[2]
    payload = frame[3:-1]
    if payload_len != len(payload):
        raise ValueError(f"payload length mismatch: header={payload_len} actual={len(payload)}")
    return frame[1], tuple(words_from_bytes(payload))


def iter_pcapng_frames(path: str) -> list[bytes]:
    data = Path(path).read_bytes()
    frames: list[bytes] = []
    idx = 0
    while idx + 12 <= len(data):
        block_type, block_len = struct.unpack_from("<II", data, idx)
        if block_len < 12:
            break
        if block_type == 0x00000006 and idx + block_len <= len(data):
            body = data[idx + 8 : idx + block_len - 4]
            if len(body) >= 20:
                caplen = struct.unpack_from("<I", body, 12)[0]
                packet = body[20 : 20 + caplen]
                if len(packet) >= 64:
                    frame = packet[64:]
                    if frame:
                        frames.append(frame)
        idx += block_len
    return frames


def iter_capture_events_from_frames(frames: Sequence[bytes], *, source: str = "") -> list[CaptureEvent]:
    events: list[CaptureEvent] = []
    current_selectors: dict[int, tuple[int, ...]] = {}
    expect_values: dict[int, bool] = {}
    for frame in frames:
        if len(frame) < 4 or frame[0] != 0x0B:
            continue
        req_id = frame[1]
        payload_len = frame[2]
        payload = frame[3:-1]
        if len(payload) != payload_len or payload_len % 2:
            continue
        words = tuple(words_from_bytes(payload))
        if not expect_values.get(req_id, False):
            current_selectors[req_id] = words
            expect_values[req_id] = True
            events.append(CaptureEvent("tx", req_id=req_id, selectors=words, source=source))
            continue
        selectors = current_selectors.get(req_id, ())
        if selectors and len(selectors) == len(words):
            events.append(CaptureEvent("values", req_id=req_id, selectors=selectors, values=words, source=source))
        else:
            events.append(CaptureEvent("values", req_id=req_id, values=words, source=source))
        expect_values[req_id] = False
    return events


def iter_capture_events(text: str, *, source: str = "") -> list[CaptureEvent]:
    events: list[CaptureEvent] = []
    current_selectors: dict[int, tuple[int, ...]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = CAPTURE_TX_RE.match(line)
        if m:
            req_id, selectors = parse_capture_tx(m.group("hex"))
            current_selectors[req_id] = selectors
            events.append(CaptureEvent("tx", req_id=req_id, selectors=selectors, source=source))
            continue
        m = CAPTURE_VALUES_RE.match(line)
        if m:
            req_id = int(m.group("req"), 16)
            pairs = parse_capture_values(m.group("body"))
            values = tuple(value for _, value in pairs)
            selectors = current_selectors.get(req_id, ())
            if selectors and len(selectors) == len(values):
                events.append(CaptureEvent("values", req_id=req_id, selectors=selectors, values=values, source=source))
            elif values:
                events.append(CaptureEvent("values", req_id=req_id, values=values, source=source))
    return events


def latest_capture_state(events: Sequence[CaptureEvent]) -> dict[int, CaptureEvent]:
    latest: dict[int, CaptureEvent] = {}
    for event in events:
        if event.kind == "values" and event.values:
            latest[event.req_id] = event
    return latest


def load_capture_events(path: str) -> list[CaptureEvent]:
    if path.lower().endswith(".pcapng"):
        return iter_capture_events_from_frames(iter_pcapng_frames(path), source=path)
    return iter_capture_events(Path(path).read_text(), source=path)


def summarize_pcapng_packets(path: str) -> list[tuple[int, bytes]]:
    data = Path(path).read_bytes()
    packets: list[tuple[int, bytes]] = []
    idx = 0
    packet_index = 0
    while idx + 12 <= len(data):
        block_type, block_len = struct.unpack_from("<II", data, idx)
        if block_len < 12:
            break
        if block_type == 0x00000006 and idx + block_len <= len(data):
            body = data[idx + 8 : idx + block_len - 4]
            if len(body) >= 20:
                caplen = struct.unpack_from("<I", body, 12)[0]
                packet = body[20 : 20 + caplen]
                if len(packet) >= 64:
                    packets.append((packet_index, packet[64:]))
                else:
                    packets.append((packet_index, b""))
                packet_index += 1
        idx += block_len
    return packets


def describe_packet_payload(payload: bytes) -> str:
    if not payload:
        return "EMPTY"
    prefix = hx(payload[:16])
    if len(payload) >= 3:
        cmd, req, subtype = payload[0], payload[1], payload[2]
        return f"cmd=0x{cmd:02X} req=0x{req:02X} sub=0x{subtype:02X} len={len(payload)} head={prefix}"
    return f"len={len(payload)} head={prefix}"


def split_len_prefixed_records(body: bytes) -> list[bytes]:
    records: list[bytes] = []
    pos = 0
    while pos < len(body):
        length = body[pos]
        if length == 0:
            pos += 1
            continue
        record = body[pos : pos + length]
        if len(record) != length:
            raise ValueError(f"truncated record at 0x{pos:04X}: need {length}, got {len(record)}")
        records.append(record)
        pos += length
    return records


def summarize_len_prefixed_records(body: bytes) -> str:
    from collections import Counter

    records = split_len_prefixed_records(body)
    prefixes = Counter(rec[1:3].hex().upper() for rec in records if len(rec) >= 3)
    top = " ".join(f"{prefix}({count})" for prefix, count in prefixes.most_common(8))
    return f"records={len(records)} body_bytes={len(body)} top={top or '(none)'}"


def detect_repeating_family_cycles(families: list[str], width: int = 5, limit: int = 3) -> list[tuple[int, int, list[str]]]:
    if width < 1:
        return []

    best_by_window: dict[tuple[str, ...], tuple[int, int]] = {}
    for start in range(len(families) - width * 2 + 1):
        window = tuple(families[start : start + width])
        if len(window) < width:
            continue
        if width == 5:
            if not (window[0].startswith("04") and window[1] == "2401" and window[2] == "2402" and window[3].startswith("05") and window[4] == "2501"):
                continue
        count = 0
        i = start
        while i + width <= len(families) and tuple(families[i : i + width]) == window:
            count += 1
            i += width
        if count >= 3:
            prev = best_by_window.get(window)
            if prev is None or count > prev[0] or (count == prev[0] and start < prev[1]):
                best_by_window[window] = (count, start)
    ranked = sorted(((count, start, list(window)) for window, (count, start) in best_by_window.items()), key=lambda item: (-item[0], item[1], item[2]))
    return ranked[:limit]


def summarize_0x09_payload(payload: bytes) -> str:
    if len(payload) < 10 or payload[0] != 0x09:
        return ""
    body = payload[9:]
    try:
        records = split_len_prefixed_records(body)
        families = [f"{rec[1]:02X}{rec[2]:02X}" for rec in records if len(rec) >= 3]
        summary = summarize_len_prefixed_records(body)
        best = detect_best_09_cycle(payload)
        if best is not None:
            _, (count, start, window), width = best
            shape = "matrix5" if width == 5 else "cycle3" if width == 3 else f"cycle{width}"
            summary += f" shape={shape} cycle={' '.join(window)} x{count}@{start}"
        else:
            cycles = detect_repeating_family_cycles(families, width=5, limit=3)
            for count, start, window in cycles:
                summary += f" cycle={' '.join(window)} x{count}@{start}"
        if families and families[0] == "0B00":
            summary += " kind=page_transfer"
        if families[:4] == ["0400", "2101", "0581", "0501"] or families[:4] == ["0400", "2111", "0581", "0501"]:
            summary += " kind=setup_burst"
        if families and set(families) <= {"0400", "0581"}:
            summary += " kind=setup_toggle"
        return summary
    except Exception as exc:
        return f"decode_error={exc}"


def detect_best_09_cycle(payload: bytes) -> tuple[list[bytes], tuple[int, int, list[str]], int] | None:
    if len(payload) < 10 or payload[0] != 0x09:
        return None
    records = split_len_prefixed_records(payload[9:])
    families = [f"{rec[1]:02X}{rec[2]:02X}" for rec in records if len(rec) >= 3]

    candidates: list[tuple[list[bytes], tuple[int, int, list[str]], int]] = []
    for width in (5, 3):
        cycles = detect_repeating_family_cycles(families, width=width, limit=1)
        if cycles:
            candidates.append((records, cycles[0], width))

    if not candidates:
        return None

    return max(candidates, key=lambda item: (item[1][0] * item[2], item[1][0], item[2]))


def guess_09_cycle_role(slot: int, width: int) -> str:
    if width == 5:
        return {
            0: "row_header",
            1: "row_meta",
            2: "axis_payload",
            3: "value_payload",
            4: "trailer",
        }.get(slot, "unknown")
    if width == 3:
        return {
            0: "row_header",
            1: "payload_a",
            2: "payload_b",
        }.get(slot, "unknown")
    return f"slot_{slot}"


def decode_09_row_header(rec: bytes) -> dict[str, int | str]:
    """Decode the row-header record for the matrix5 shape.

    Observed layout in packet 327:
      data[0] = row/column index
      data[4] = column count (0x20 -> 32)
      data[5] = table/channel id (0x05 -> InjectorDeadTime)
    """
    if len(rec) < 9 or rec[1] == 0 or rec[2] == 0:
        return {}
    data = rec[3:]
    out: dict[str, int | str] = {
        "row_index": data[0] if len(data) > 0 else 0,
        "field_1": data[1] if len(data) > 1 else 0,
        "field_2": data[2] if len(data) > 2 else 0,
        "field_3": data[3] if len(data) > 3 else 0,
        "column_count": data[4] if len(data) > 4 else 0,
        "table_id": data[5] if len(data) > 5 else 0,
    }
    table_id = out["table_id"] if isinstance(out["table_id"], int) else None
    if table_id is not None and table_id in INTERNAL_CHANNEL_NAMES:
        out["table_name"] = INTERNAL_CHANNEL_NAMES[table_id]
    return out


def decode_09_value_record(rec: bytes) -> dict[str, int]:
    """Decode a value record.

    Observed layout in packet 327:
      data[0:2] = big-endian 16-bit value (e.g. 09F8)
      data[2:4] = trailing flags / row-local metadata
    """
    if len(rec) < 7:
        return {}
    data = rec[3:]
    if len(data) < 2:
        return {}
    return {
        "value_u16": (data[0] << 8) | data[1],
        "flags_u16": (data[2] << 8) | data[3] if len(data) >= 4 else 0,
        "value_hi": data[0],
        "value_lo": data[1],
        "flag_hi": data[2] if len(data) >= 3 else 0,
        "flag_lo": data[3] if len(data) >= 4 else 0,
    }


def extract_09_cycle_fields(slot: int, rec: bytes, width: int) -> tuple[str, ...]:
    if width == 5:
        header = decode_09_row_header(rec) if slot == 0 else {}
        value = decode_09_value_record(rec) if slot == 3 else {}
        row_index = f"{header.get('row_index', ''):02X}" if header else ""
        row_meta = " ".join(
            f"{b:02X}" for b in (
                header.get("field_1", 0),
                header.get("field_2", 0),
                header.get("field_3", 0),
            )
        ) if header else ""
        axis_value = f"{header.get('column_count', 0):02X}" if header else ""
        value_raw = f"{value.get('value_u16', 0):04X}" if value else ""
        value_flag = f"{value.get('flags_u16', 0):04X}" if value else ""
        return row_index, row_meta, axis_value, value_raw, value_flag

    if width == 3:
        row_index = f"{rec[3]:02X}" if slot == 0 and len(rec) >= 4 else ""
        field_a = f"{rec[3]:02X}" if len(rec) >= 4 else ""
        field_b = f"{rec[4]:02X}" if len(rec) >= 5 else ""
        field_c = f"{rec[5]:02X}" if len(rec) >= 6 else ""
        return row_index, field_a, field_b, field_c

    return tuple()


def format_09_cycle_csv(packet_index: int, payload: bytes) -> str:
    best = detect_best_09_cycle(payload)
    if best is None:
        return ""

    records, (count, start, window), width = best
    rows: list[str] = []
    if width == 5:
        rows.append("packet_index,occ,slot,role_guess,family,length,row_index,row_meta,column_count,value_u16,value_flags,table_id,table_name,hex")
    else:
        rows.append("packet_index,occ,slot,role_guess,family,length,row_index,field_a,field_b,field_c,internal_channel_id,internal_channel_name,hex")
    for occ in range(count):
        base = start + occ * len(window)
        for slot, fam in enumerate(window):
            rec = records[base + slot]
            fields = extract_09_cycle_fields(slot, rec, width)
            if width == 5:
                header = decode_09_row_header(rec) if slot == 0 else {}
                value = decode_09_value_record(rec) if slot == 3 else {}
                table_id = f"0x{int(header.get('table_id', 0)):04X}" if header else ""
                table_name = str(header.get("table_name", "")) if header else ""
                row_index, row_meta, axis_value, value_raw, value_flag = fields
                rows.append(
                    f"{packet_index},{occ},{slot},{guess_09_cycle_role(slot, width)},{fam},{len(rec):02X},"
                    f"{row_index},{row_meta},{axis_value},{value_raw},{value_flag},{table_id},{table_name},{hx(rec)}"
                )
            else:
                row_index, field_a, field_b, field_c = fields
                internal_id = ""
                internal_name = ""
                if slot == 0 and len(rec) >= 4:
                    raw_id = int(rec[3])
                    internal_id = f"0x{raw_id:04X}"
                    internal_name = INTERNAL_CHANNEL_NAMES.get(raw_id, "")
                rows.append(
                    f"{packet_index},{occ},{slot},{guess_09_cycle_role(slot, width)},{fam},{len(rec):02X},"
                    f"{row_index},{field_a},{field_b},{field_c},{internal_id},{internal_name},{hx(rec)}"
                )
    return "\n".join(rows)


def format_09_cycle_table(packet_index: int, payload: bytes) -> str:
    best = detect_best_09_cycle(payload)
    if best is None:
        return "(no repeating 0x09 cycle found)"

    records, (count, start, window), width = best
    rows: list[str] = []
    rows.append(f"packet {packet_index:05d} 0x09 cycle {' '.join(window)} x{count} start={start} width={width}")
    if width == 5:
        rows.append("| occ | slot | role | family | len | row | meta | colcnt | value_u16 | flags | table | hex |")
        rows.append("| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |")
    else:
        rows.append("| occ | slot | role | family | len | row | a | b | c | hex |")
        rows.append("| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- |")

    for occ in range(count):
        base = start + occ * len(window)
        for slot, fam in enumerate(window):
            rec = records[base + slot]
            fields = extract_09_cycle_fields(slot, rec, width)
            if width == 5:
                header = decode_09_row_header(rec) if slot == 0 else {}
                value = decode_09_value_record(rec) if slot == 3 else {}
                row_index, row_meta, axis_value, value_raw, value_flag = fields
                table_name = str(header.get("table_name", "")) if header else ""
                rows.append(
                    f"| {occ} | {slot} | {guess_09_cycle_role(slot, width)} | {fam} | {len(rec):02X} | "
                    f"{row_index} | {row_meta} | {axis_value} | {value_raw} | {value_flag} | {table_name} | {hx(rec)} |"
                )
            else:
                row_index, field_a, field_b, field_c = fields
                rows.append(
                    f"| {occ} | {slot} | {guess_09_cycle_role(slot, width)} | {fam} | {len(rec):02X} | "
                    f"{row_index} | {field_a} | {field_b} | {field_c} | {hx(rec)} |"
                )
    return "\n".join(rows)


def cmd_inspect_capture(args: argparse.Namespace) -> int:
    wanted = {parse_int(v) for v in args.cmds} if args.cmds else None
    packets = summarize_pcapng_packets(args.capture)
    for packet_index, payload in packets:
        if not payload:
            continue
        cmd = payload[0]
        if wanted is not None and cmd not in wanted:
            continue
        if args.table and cmd == 0x09:
            if args.packet_index is not None and packet_index != args.packet_index:
                continue
            if args.csv:
                print(format_09_cycle_csv(packet_index, payload))
            else:
                print(format_09_cycle_table(packet_index, payload))
            print()
            continue
        line = f"pkt {packet_index:05d} {describe_packet_payload(payload)}"
        if args.detail and cmd == 0x09:
            line += f" 09DETAIL {summarize_0x09_payload(payload)}"
        if args.tail and len(payload) > args.head_bytes:
            line += f" tail={hx(payload[-args.tail:])}"
        print(line)
    return 0


def render_capture_event(event: CaptureEvent, labels: dict[int, str] | None = None, *, nonzero_only: bool = False) -> str:
    if event.kind == "tx":
        selectors = " ".join(f"0x{s:04X}" for s in event.selectors)
        return f"GROUP 0x{event.req_id:02X} SELECTORS {selectors}"
    if event.selectors:
        return f"GROUP 0x{event.req_id:02X} VALUES {format_selector_pairs(event.selectors, event.values, labels, nonzero_only=nonzero_only)}"
    return f"GROUP 0x{event.req_id:02X} VALUES " + " ".join(f"value_{i}=0x{value:04X}" for i, value in enumerate(event.values))


def event_value_map(event: CaptureEvent) -> dict[int, int]:
    return dict(zip(event.selectors, event.values, strict=True)) if event.selectors and event.values else {}


def cmd_replay(args: argparse.Namespace) -> int:
    labels = load_labels(args.labels)
    wanted = {parse_int(g) for g in args.groups} if args.groups else None
    for path in args.capture_paths:
        events = load_capture_events(path)
        print(f"== {path} ==")
        for event in events:
            if wanted and event.req_id not in wanted:
                continue
            if event.kind == "tx":
                print(render_capture_event(event, labels, nonzero_only=args.nonzero_only))
            elif event.kind == "values":
                print(render_capture_event(event, labels, nonzero_only=args.nonzero_only))
        print()
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    labels = load_labels(args.labels)
    wanted = {parse_int(g) for g in args.groups} if args.groups else None
    before_state = latest_capture_state(load_capture_events(args.before))
    after_state = latest_capture_state(load_capture_events(args.after))

    req_ids = sorted(set(before_state) | set(after_state))
    if wanted is not None:
        req_ids = [req_id for req_id in req_ids if req_id in wanted]

    for req_id in req_ids:
        before = before_state.get(req_id)
        after = after_state.get(req_id)
        if before is None:
            print(f"GROUP 0x{req_id:02X} only in after: {render_capture_event(after, labels, nonzero_only=args.nonzero_only)}")
            continue
        if after is None:
            print(f"GROUP 0x{req_id:02X} only in before: {render_capture_event(before, labels, nonzero_only=args.nonzero_only)}")
            continue

        before_map = event_value_map(before)
        after_map = event_value_map(after)
        selectors = list(before.selectors or after.selectors)
        if not selectors:
            selectors = sorted(set(before_map) | set(after_map))

        changed: list[str] = []
        for selector_id in selectors:
            before_value = before_map.get(selector_id)
            after_value = after_map.get(selector_id)
            if before_value == after_value:
                continue
            label = selector_label(selector_id, labels)
            changed.append(f"  {label}: {('n/a' if before_value is None else f'0x{before_value:04X}')} -> {('n/a' if after_value is None else f'0x{after_value:04X}')}")

        if changed:
            print(f"GROUP 0x{req_id:02X}")
            for line in changed:
                print(line)
    return 0


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

    s = sub.add_parser("replay", help="normalize a saved capture log without hardware")
    s.add_argument("capture_paths", nargs="+", help="one or more saved live logs")
    s.add_argument("--labels", help="optional JSON file mapping selector ids to channel names")
    s.add_argument("--groups", nargs="*", help="optional subset of live groups, e.g. 0x72 0x73")
    s.add_argument("--nonzero-only", action="store_true", help="hide zero-value channels")
    s.set_defaults(func=cmd_replay)

    s = sub.add_parser("diff", help="diff two saved capture logs")
    s.add_argument("before", help="baseline capture log")
    s.add_argument("after", help="comparison capture log")
    s.add_argument("--labels", help="optional JSON file mapping selector ids to channel names")
    s.add_argument("--groups", nargs="*", help="optional subset of live groups, e.g. 0x72 0x73")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("inspect-pcapng", help="summarize packets from a pcapng capture")
    s.add_argument("capture", help="capture file, e.g. haltech_usb_capture.pcapng")
    s.add_argument("--cmds", nargs="*", help="optional command bytes to filter, e.g. 0x09 0x0B")
    s.add_argument("--detail", action="store_true", help="decode known nested payload shapes")
    s.add_argument("--table", action="store_true", help="render repeating 0x09 cycles as a table")
    s.add_argument("--csv", action="store_true", help="render repeating 0x09 cycles as CSV")
    s.add_argument("--packet-index", type=int, help="only show a specific packet index")
    s.add_argument("--head-bytes", type=int, default=16, help="number of leading bytes to display")
    s.add_argument("--tail", type=int, default=0, help="also show this many trailing bytes")
    s.set_defaults(func=cmd_inspect_capture)

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
