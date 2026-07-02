# Haltech PSX USB protocol POC plan

## Goal
Map the Haltech Platinum Sport 1000 live-data selector IDs to human-readable ECU channels and turn the proof-of-concept into a small live-reader that can poll and print decoded values from the ECU.

## Non-goals
- Do not redesign the protocol stack.
- Do not broaden into unrelated request families unless they directly support live-data decoding.
- Do not chase UI polish before the decoder works.
- Do not change the ECU Manager binary or the host setup.

## Current status
- Transport is confirmed working on this machine.
- Baud is confirmed at 57600.
- The live-polling / selector-decoding path is established.
- A candidate label map exists for a larger slice of selectors.
- Car-dependent validation is now sidelined until a running car is available.
- Replay/diff tooling now exists in `haltech_poc.py` and can consume the real `haltech_usb_capture.pcapng` file.
- The immediate focus is on protocol documentation, decoder hardening, and capture import/export work that can be done from captures alone.

## Active workstreams

### Workstream 1: Car-independent protocol documentation
- Tighten the frame decoder and describe each known request/response shape.
- Decode the startup 0x09 tune/page-transfer bursts from the pcapng and document their payload structure.
- Keep the candidate label map separate from verified labels.
- Record the observed 0x33 and 0x0B behaviors in the protocol notes.

Acceptance criteria:
- The known wire shapes are documented from captures, not guesswork.
- Unknowns are explicitly called out.

### Workstream 2: Replay and diff tooling
- Add a way to replay captured frames.
- Add a way to diff two captures and spot value movement.
- Keep raw hex output available for debugging.

Acceptance criteria:
- A future capture can be compared against an earlier one without hand-sorting hex.

### Workstream 3: Car-dependent validation
- Confirm the remaining ambiguous selector names against ECU Manager live GUI behavior.
- Split the remaining 0x72 cluster by observing how values move under throttle, load, warmup, or engine-off / engine-on transitions.
- Validate scaling and units for candidate channels that only have one idle-state sample.

Acceptance criteria:
- Deferred items in `CAR_DEPENDENT.md` have been either verified or explicitly blocked.

## Deferred backlog
- See `CAR_DEPENDENT.md` for the running list of work that is intentionally parked until a car is available.

## Verification commands
- `python3 /home/max/git/haltech-psx-usb/haltech_poc.py examples`
- `sudo python3 /home/max/git/haltech-psx-usb/haltech_poc.py send --port /dev/ttyUSB0 data-log-status --req-id 0x77`
- `sudo python3 /home/max/git/haltech-psx-usb/haltech_poc.py send --port /dev/ttyUSB0 data --group 0x72 --req-id 0x77`

## Next step
Do Workstream 1 first, then build the replay/diff tooling once the protocol notes are clean.
