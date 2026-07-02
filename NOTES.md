See `PROTOCOL.md` for the active Haltech protocol notebook.

Current status:
- Static RE confirmed the ECU Manager is a .NET serial client and mapped several request command bytes.
- Live baud/framing confirmation is now complete at 57600 on `/dev/ttyUSB0`.
- `haltech_poc.py` now has a live polling mode; keep protocol facts in `PROTOCOL.md` instead.
