# Haltech Platinum Sport 1000 USB Protocol Notes

Status: static reverse engineering in progress.

## What is confirmed

- ECU Manager is a .NET assembly.
- The transport code lives under `com.Haltech.ECUManager.Core.SerialComs`.
- The connected hardware exposes a CP210x USB-to-serial bridge:
  - vendor/product: `10c4:ea60`
  - device path on this machine: `/dev/ttyUSB0`
- The protocol is proprietary binary, not text.
- `SerialRequest` is the shared base type for protocol requests.
- `SerialRequest` fields:
  - `m_commandId`
  - `m_requestId`
  - `m_hasAddress`
  - `m_address`
  - `m_trysLeft`
- `get_CommandID()` returns the stored command byte.
- `get_RequestID()` returns the stored request byte.
- The read path uses a 2048-byte ring buffer.
- `ProcessSyncBytes()` treats `0xFF` specially.
- `WriteSyncBytes()` emits an 8-byte sync block.
- Many response validators use an 8-bit additive checksum: last byte equals the sum of earlier bytes modulo 256.
- Live USB capture on the host shows the CP210x bridge at bus 3, device address 4 while ECU Manager talks to the ECU.
- On connect, ECU Manager immediately starts a burst of proprietary `0x0B`/`0x0C` request frames, then settles into a repeating poll/download pattern.
- In the live capture, the dominant application bytes are `0x0B` (by far the most common), then `0x0C`, then `0x33`; `0xFF`-only transfers also appear frequently as control/empty/status traffic.
- The first observed real application frames after attach included:
  - `0x0B 0x70 0x18 ... 0x93` (30-byte IN transfer)
  - `0x0C 0x71 0x01 0x03 0x81` (5-byte OUT transfer)
  - `0x0C 0x71 0x02 0x03 0xFE 0x80 0xFF 0xFF` (8-byte IN transfer)
- The startup/download phase contains repeated `0x0B 0x72`/`0x0B 0x73`/`0x0B 0x74`/`0x0B 0x75` style frames carrying large selector tables and ECU data blocks, with responses mirroring the request id in the second byte.
- `0x33` traffic appears during startup as well:
  - `0x33 0x77 0xAA` request
  - `0x33 0x77 ...` response carrying status bytes
- The live trace strongly suggests a request-id based half-duplex exchange: request id increments, payload body changes, and the ECU answers with matching request id plus checksum.

## Live-decoded payload shapes

### `0x33` data-log status request (`DataLogStatusRequest`)

The binary decodes this one down to a 3-byte frame:

- byte 0: command `0x33`
- byte 1: request id
- byte 2: checksum = `(0x33 + request id) & 0xFF`

Live-capture example:

- request: `33 77 AA`
- response: `33 77 ...`

This is the startup/status probe we saw alongside the `0x0B` live-data bursts.

### `0x0B` data requests (`DataRequest`)

The live capture matches the static `DataRequest.PopulateSendData()` shape exactly:

- byte 0: command `0x0B`
- byte 1: request id
- byte 2: payload byte count = `2 * N`
- bytes 3..n: `N` big-endian 16-bit selectors / channel ids
- final byte: additive checksum over all previous bytes

Representative request groups from the capture:

- `0B 72 40 ...`
  - 32 selectors
  - ids: `0080 0081 0084 0085 0087 008A 008B 008C 00A4 00E1 00E4 00E5 00E6 00EC 00F2 012F 0130 0180 0181 0182 0183 0184 0186 0189 018A 018C 0195 0197 01AF 01DF 01E1 01E2`
  - response mirrors the header and returns 32 big-endian 16-bit values in the same slots

- `0B 73 3E ...`
  - 31 selectors
  - ids: `0201 0202 022B 0240 0241 0242 0280 0281 0282 0283 0284 0285 0286 0287 0288 0289 0294 0295 0296 02E0 02E1 02E2 02F8 02F9 02FA 0442 0443 0444 0445 0446 0447`

- `0B 74 40 ...`
  - 32 selectors
  - ids: `0448 0449 044A 044E 044F 0450 0451 0452 0453 0472 0473 0474 0475 0476 0477 0478 0479 047A 047E 047F 0480 0481 0482 0483 04D8 04D9 04DA 04DB 04DC 04DD 04DE 04DF`

- `0B 75 18 ...`
  - 12 selectors
  - ids: `04E0 04E4 04E5 04E6 04E7 04E8 04E9 054B 054C 054D 05B5 05B6`

These are the live ECU data blocks the GUI polls after connect.

### `0x0C` short-control / status requests

Two short forms are confirmed in the trace:

- `0C <req> 01 03 <checksum>`
  - response: `0C <req> 02 03 FE <checksum> FF FF`
  - confirmed as the `GetDTCs` family / DTC-status probe

- `0C <req> 06 05 00 00 00 00 <checksum>`
  - response: `0C <req> 02 05 FE <checksum> FF FF`
  - this matches `EEPROMRangesChangedRequest` when its range/address fields are zeroed


## Command IDs confirmed from request constructors

| Class | Command ID |
|---|---:|
| `ECUIDRequest` | `0x01` |
| `DisableEnableInternalProcesses` | `0x02` |
| `EepromRequest` | `0x03` |
| `EepromWrite` | `0x04` |
| `DataPageSetupRequest` | `0x05` |
| `DataPageRequest` | `0x06` |
| `ResetRequest` | `0x07` |
| `DataRequest` | `0x0B` |
| `EraseDTCs` | `0x0C` |
| `GetDeviceInfo` | `0x0C` |
| `GetDTCs` | `0x0C` |
| `ChipDescriptorsRequest` | `0x0C` |
| `SetPassword` | `0x0C` |
| `CheckPasswordKey` | `0x0C` |
| `BlackListEnable` | `0x42` |
| `FirmwareErase` | `0x20` |
| `IsFirmwareErased` | `0x21` |
| `FirmwareWrite` | `0x23` |
| `DataLogStatusRequest` | `0x33` |
| `DataLogRead` | `0x34` |
| `DataLogErase` | `0x35` |
| `ECUDescriptorsRequest` | `0x36` |
| `SetECUVariant` | `0x37` |
| `DisableRAMLoad` | `0x38` |
| `RebootToBootcode` | `0x39` |
| `GetConsoleMessage` | `0x40` |
| `SendConsoleMessage` | `0x41` |
| `BlackListEnable` | `0x42` |

## Request / response shapes recovered so far

### Simple command-only requests

- `ECUIDRequest`
  - send payload: `[0x01, 0x00, 0x01]`
  - response validity: command byte must be `0x01`; response payload is checked against the checksum rule

- `ResetRequest`
  - send payload: `[0x07, 0x00, 0x07]`
  - response validity: command byte `0x07`, zero-length payload expected in the response class logic

- `ECUDescriptorsRequest`
  - send payload: `[0x36, 0x01, 0x37]`
  - `Matches()` requires command `0x36` and length at least `14`

- `FirmwareErase`
  - command `0x20`
  - request frame is built from a static 11-byte template and then patched with the request id/checksum

- `IsFirmwareErased`
  - command `0x21`
  - send payload: `[0x21, 0x00, 0x21]`
  - response length checked at 5 bytes; several byte-position checks follow

### Requests with small payloads / selectors

- `DataPageRequest`
  - command `0x06`
  - constructor stores a page/selector byte in a field
  - send payload begins with command + request byte, then a constant `0x01`, then the selector, then checksum

- `DataRequest`
  - command `0x0B`
  - payload length depends on the selected data group count (`m_requestId`-driven sizing)
  - the request body is built as a command/request header plus data-group bytes, then checksum

- `DataPageSetupRequest`
  - command `0x05`
  - includes a selector byte plus address/page bytes
  - the payload is variable length and ends with a checksum byte

- `DisableEnableInternalProcesses`
  - command `0x02`
  - payload carries two mode bytes stored in fields `0x040007AC` and `0x040007AD`
  - response validator checks the command and a short-length condition

- `DisableRAMLoad`
  - command `0x38`
  - payload includes a boolean flag encoded as `0`/`1`

- `SetECUVariant`
  - command `0x37`
  - payload bytes observed:
    - header bytes derived from `SerialRequest`
    - fixed literal sequence `0x08, 0x54, 0x52, 0x4F, 0x47, 0x44, 0x4F, 0x52`
    - a variant byte at index 10
    - checksum at the end
  - `IsResponseValid()` checks that response byte 3 equals the requested variant

- `SetPassword`
  - command `0x0C`
  - payload is password bytes plus a length/checksum tail
  - response validation compares the final byte against the sum of the payload bytes

- `CheckPasswordKey`
  - command `0x0C`
  - payload length is `password length + 5`
  - layout observed: command/request header, password length byte, password bytes, checksum tail

- `ChipDescriptorsRequest`
  - command `0x0C`
  - send payload: command/request header, literal bytes `0x01, 0x06`, then checksum

- `BlackListEnable`
  - command `0x42`
  - payload uses a boolean flag stored in `0x04000796`
  - when false, byte `0xE0` is used; when true, byte `0xE1` is used
  - response validator checks command `0x42`, length 5, and a `0x01` marker in byte 2

- `EepromRequest`
  - command `0x03`
  - constructor stores a selector/index byte
  - response validation checks command `0x03`, a payload length offset tied to the selector, and additive checksum
  - send payload has a fixed header followed by selector/address bytes and checksum

- `EepromWrite`
  - command `0x04`
  - payload begins with command/request header, then a variable data blob from `m_data`
  - final byte is checksum-like

### Data log and DTC requests

- `DataLogStatusRequest`
  - command `0x33`
  - send payload: `[0x33, 0x00, 0x33]`
  - response validation checks command `0x33`, byte 1, byte 2, and a checksum over the preceding bytes

- `DataLogRead`
  - command `0x34`
  - constructor stores a slot/index byte
  - response validation accepts either the stored slot or a zero-byte status path, then applies checksum validation
  - send payload begins with command/request, includes the slot byte, and ends with checksum

- `DataLogErase`
  - command `0x35`
  - send payload is based on a static template and ends with checksum

- `EraseDTCs`
  - command `0x0C`
  - send payload uses command/request header plus literal bytes `0x01, 0x04`
  - response validation accepts response byte 4 being `0xFE` or `0x01`

- `GetDTCs`
  - command `0x0C`
  - send payload bytes observed: command/request header, literals `0x01, 0x03`, then checksum
  - response validation checks command and that response byte 3 equals `0x03`

### Console message requests

- `GetConsoleMessage`
  - command `0x40`
  - payload is 4 bytes long
  - bytes observed: command, request, a zero placeholder, checksum at index 3

- `SendConsoleMessage`
  - command `0x41`
  - payload length is `message length + 4`
  - layout is command/request header, message length byte, message body, checksum

### Firmware / boot / variant requests

- `FirmwareWrite`
  - command `0x23`
  - payload mirrors `EepromWrite`: header, variable data, checksum tail

- `FirmwareErase`
  - command `0x20`
  - uses a static 11-byte template and computes a checksum byte at the end

- `RebootToBootcode`
  - command `0x39`
  - payload is a static 11-byte template with the command byte embedded
  - checksum is computed by summing the bytes before the final slot

### OBD-II-style request family

These are clearly grouped in the assembly and use a consistent 0x0C-based transport pattern.

- `ObdiiDiagnosticSessionControl`
  - payload bytes observed: command/request header, service byte `0x10`, session byte at field `0x040007D3`, and command/response bookkeeping bytes

- `ObdiiECUReset`
  - similar to `ObdiiDiagnosticSessionControl`, but service byte `0x11` and field `0x040007D6`

- `ObdiiRequestUpload`
  - payload includes service byte `0x34`, mode byte `0x40`, and address/size fields in `0x040007D7` / `0x040007D9`

- `ObdiiRoutineControl`
  - variable-length request; payload length depends on `m_requestData`
  - service byte `0x31`
  - includes routine control bytes/fields and a trailing checksum

- `ObdiiTransferData`
  - service byte `0x36`
  - transfer sequence byte in `m_requestId`/`m_requestNumber`-style fields
  - variable payload length based on data block size, checksum at end

## Response validation patterns worth keeping

- Many validators first call a shared `IsResponseValid()`/`HasTimedOut()`-style helper.
- Common checks:
  - command byte at index 3 equals expected command/subcommand
  - one or more fixed bytes after the command
  - final byte equals additive checksum of all previous bytes
- `ResponseMustMatchSerialRequest` is the common response/echo validator used by the base transport.
- `Matches()` methods often gate on command byte and minimum length, then sometimes on request id or payload shape.

## Protocol scaffolding / state types

These are present and likely relevant to the request scheduler, but not all of them have been decoded fully yet:

- `ResponseMustMatchSerialRequest`
- `SerialRequestStatus`
- `StateMachine`
- `StateMachineFunction`
- `StateMachineProcess`
- `StateMachineError`
- `DataLoggingStatus`
- `InternalProcessStatus`
- `DeviceType`
- `DeviceError`
- `LongTermTrimFlags`
- `DiagnosticSessionCtrlSubfunctions`
- `ObdiiErrorCode`

## Enum values recovered so far

- `DataLoggingStatus`: `NONE=4`, `LOGGING=260`, `FINISHED_LOGGING=516`, `FULL=772`, `ERASING=1028`
- `InternalProcessStatus`: `Deactivated=4`, `Activated=260`, `NoChange=516`, `NotAvaliable=772`
- `DeviceType`: `Internal=4`, `DumbExternal=260`, `SmartExternal=516`
- `DeviceError`: `Unknown=4294967044`, `None=4`, `ConflictingIDs=260`, `HardwareFailure=516`, `FirmwareErased=772`, `WatchdogTimeout=1028`, `IllegalOperation=1284`, `VersionToNew=4100`, `VersionToOld=4356`, `TXTimeout=4612`, `OperationalIssue=4868`
- `LongTermTrimFlags`: `None=4`, `Fuel=260`, `Knock=516`, `All=16776964`
- `DiagnosticSessionCtrlSubfunctions`: `ISOSAEReserved=4`, `defaultSession=260`, `programmingSession=516`, `extendedDiagnosticSession=772`, `safetySystemDiagnosticSession=1028`
- `ObdiiErrorCode`: `OK=4`, `SERVICE_NOT_SUPPORTED=4356`, `SUB_FUNCTION_NOT_SUPPORTED=4612`, `INCORRECT_MESSAGE_LENGTH_OR_INVALID_FORMAT=4868`, `CONDITIONS_NOT_CORRECT=8708`, `REQUEST_SEQUENCE_ERROR=9220`, `REQUEST_OUT_OF_RANGE=12548`, `SECURITY_ACCESS_DENIED=13060`, `INVALID_KEY=13572`, `EXCEEDED_NUMBER_OF_ATTEMPTS=13828`, `TRANSFER_DATA_SUSPENDED=28932`, `GENERAL_PROGRAMMING_FAILURE=29188`, `WRONG_BLOCK_SEQUENCE_COUNTER=29444`
- `SerialRequestStatus`: `None=4`, `InQueue=260`, `AwaitingResponse=516`, `ResponseReceived=772`, `Error=1028`, `NoResponse=1284`
- `StateMachineProcess`: `InternalETCs=260`
- `StateMachineFunction`: `RequestState=260`, `ExecuteState=516`, `Reset=772`
- `StateMachineError`: `None=4`, `UnknownFunction=260`, `UnknownProcess=516`, `Busy=772`, `Danger=1028`, `NotSupported=1284`, `ConnectionError=1540`, `StageMismatch=1796`, `InternalTimeOut=2052`, `IllegalSetStage=2308`

## Open questions

- Exact frame delimiters and escaping rules still need live capture.
- The checksum is very likely additive, but I still want a live frame to confirm the wire format.
- The meaning of the request id and address fields needs normalization across all request classes.
- Some response classes are still partially decoded; a few validators are clearly byte-position specific but not yet mapped to human names.

## Working note

Keep this file updated as more request classes are decoded and validated.
