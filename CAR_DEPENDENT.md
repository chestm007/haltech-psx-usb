# Car-dependent backlog

This file is the running list of protocol work we are deliberately sidelining because it needs a running car, live GUI confirmation, or engine-state changes we cannot reproduce on the bench.

## Deferred items

- Confirm the remaining ambiguous 0x0B selector names against ECU Manager live GUI behavior.
- Split the remaining 0x72 cluster by observing how values move under throttle, load, warmup, or engine-off / engine-on transitions.
- Verify scaling and units for any candidate channel that only has one idle-state sample.
- Cross-check any low-confidence candidate label against a live capture taken while the engine state changes.
- Validate whether there are any additional live-data selector groups that only appear in a real vehicle session.

## Notes

- Keep this list explicit; do not silently move a car-dependent item into the main plan.
- When a new deferred item shows up, add it here rather than burying it in chat.
- If a deferred item later becomes testable without the car, move it back into the active plan.
