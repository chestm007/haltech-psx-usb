# Wire Selector → Internal Channel Mapping

## Summary

The wire selector IDs (used in 0x0B live data polling) are NOT the same as the internal channel IDs (used in 0x09 tune transfer and ECU Manager internals). The mapping between them is a complex lookup table maintained by ECU Manager.

## Key Findings from Offset Analysis

The offset analysis reveals that wire selectors map to internal channel IDs in groups with consistent offsets:

| Wire Selector Group | Internal Channel Group | Offset | Matches |
|---|---|---|---|
| 0x0080-0x00FF | 0x0000-0x007F | 0x0080 | 32 |
| 0x0180-0x01FF | 0x0000-0x007F | 0x0180 | 29 |
| 0x0280-0x02FF | 0x0000-0x007F | 0x0280 | 21 |
| 0x0340-0x03FF | 0x0100-0x01FF | 0x0340 | 14 |
| 0x0440-0x04FF | 0x0000-0x00FF | 0x0440 | 28 |
| 0x0470-0x04FF | 0x0000-0x00FF | 0x0470 | 21 |
| 0x0480-0x04FF | 0x0000-0x00FF | 0x0480 | 12 |
| 0x04E0-0x04FF | 0x0000-0x00FF | 0x04E0 | 7 |

## Verified Mappings

### Group 1: Wire 0x0080-0x00FF → Internal 0x0000-0x007F (Offset 0x0080)

| Wire Selector | Internal ID | Internal Name | Verified Label |
|---|---|---|---|
| 0x0080 | 0x0000 | BaseFuel | Target - Idle RPM |
| 0x0081 | 0x0001 | BaseIgnition | Ignition Advance |
| 0x0084 | 0x0004 | TargetAFR | - |
| 0x0085 | 0x0005 | InjectorDeadTime | Fuel - Target AFR |
| 0x0087 | 0x0007 | FuelFiringAngle | Injector Duty Cycle |
| 0x008A | 0x000A | FuelPrimePulse | Boost Control Output |
| 0x008C | 0x000C | FuelCrankingInjectionTime | Boost Control Trim |

### Group 2: Wire 0x0294-0x0296 → Internal 0x0004-0x0006 (Offset 0x0290)

| Wire Selector | Internal ID | Internal Name | Verified Label |
|---|---|---|---|
| 0x0294 | 0x0004 | TargetAFR | Engine Speed.RPM |
| 0x0295 | 0x0005 | InjectorDeadTime | Manifold Pressure |
| 0x0296 | 0x0006 | InjectorSize | Throttle Position |

### Group 3: Wire 0x0442-0x0447 → Internal 0x0102-0x0107 (Offset 0x0340)

| Wire Selector | Internal ID | Internal Name | Verified Label |
|---|---|---|---|
| 0x0442 | 0x0102 | LambdaSensor1 | - |
| 0x0443 | 0x0103 | LambdaSensor2 | Actual O2 Value Bank 1 |
| 0x0444 | 0x0104 | AcceleratorPedal | Actual O2 Value Bank 2 |
| 0x0445 | 0x0105 | FuelTemp | Battery Voltage |
| 0x0446 | 0x0106 | FuelPressure | - |
| 0x0447 | 0x0107 | OilTemp | - |

### Group 4: Wire 0x0472-0x0475 → Internal 0x0102-0x0105 (Offset 0x0370)

| Wire Selector | Internal ID | Internal Name | Verified Label |
|---|---|---|---|
| 0x0472 | 0x0102 | LambdaSensor1 | Coolant Temperature |
| 0x0473 | 0x0103 | LambdaSensor2 | Oil Temp Sensor 1 |
| 0x0474 | 0x0104 | AcceleratorPedal | Fuel Temp Sensor 1 |
| 0x0475 | 0x0105 | FuelTemp | Actual Boost Level |

## Important Notes

1. **The mapping is NOT a simple offset** — different groups of wire selectors map to different ranges of internal channel IDs.
2. **The 0x09 tune transfer protocol encodes this mapping** — the `row_index` field likely contains the wire selector ID, and the `row_meta` field contains the internal channel ID.
3. **The mapping is ECU-specific** — different ECU models may have different mappings.
4. **The mapping is version-specific** — ECU Manager versions may change the mapping.
5. **Live GUI cross-checking is required** — to confirm the mapping for unverified selectors.

## Next Steps

1. **Extract the full mapping table from the 0x09 tune transfer data** — the `matrix5` and `cycle3` patterns in the 0x09 protocol should contain the complete mapping.
2. **Correlate with ECU Manager live GUI behavior** — when ECU Manager displays a channel, it shows both the wire selector ID and the internal channel ID.
3. **Build a lookup table** — once the mapping is confirmed, create a lookup table that can be used to decode wire selector IDs to internal channel names.
