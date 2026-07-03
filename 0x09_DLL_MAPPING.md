# 0x09 Tune Transfer → DLL Mapping

## Summary

The 0x09 tune/page-transfer protocol maps directly to ECU Manager's `TableAxisModel`/`SettingsDataGrid` row/column/channel architecture. The wire protocol is a serialized table where each row is a channel and each column is a dimension (axis/value).

## DLL Class Hierarchy

```
com.Haltech.ECUManager.Displays.TextView.XPTable.Models.TableModel
├── ColumnModel (columns = dimensions)
├── RowModel (rows = channels)
├── Cell (value at row×column)
└── TableAxisModel (axis metadata)

com.Haltech.ECUManager.Displays.DisplaySupport.TableControls.SettingsDataGrid
├── SetupRowChannelUnitInfo(row, channel, unit)
├── SetupColumnChannelUnitInfo(column, channel, unit)
├── SetupTableHeaders()
├── SetupAxisInfo(axis, name, color, units)
├── RegisterRowChannel(channel)
├── RegisterColumnChannel(channel)
├── UnregisterRowChannel(channel)
├── UnregisterColumnChannel(channel)
├── GetChannelName(channelID) → string
├── GetChannelShortName(channelID) → string
├── GetColumnIndex(channelID) → int
├── GetColumnNormalisedValue(col, row) → float
├── GetColumnPercentageValue(col, row) → float
├── GetColumnValue(col, row) → float
├── GetRowValue(row, col) → float
├── GetRowNormalisedValue(row, col) → float
├── GetRowPercentageValue(row, col) → float
└── FindColumnZeroPoints() → list

com.Haltech.GenericLibrary.DisplaySupport.TableControls.Controls.RowInfoControl
├── get_ChannelID() → int
├── get_ChannelType() → int
├── get_ChannelTypeCode() → int
├── get_InputChannel() → InputChannel
├── get_RawValue() → float
├── get_DisplayValue() → float
├── set_DisplayValue(value)
├── set_DisplayValues(values)
└── m_rawValue

com.Haltech.GenericLibrary.DisplaySupport.TableControls.Controls.ColumnInfoControl
├── get_ChannelID() → int
├── get_ChannelType() → int
├── get_ChannelTypeCode() → int
├── get_InputChannel() → InputChannel
├── get_RawValue() → float
├── get_DisplayValue() → float
├── set_DisplayValue(value)
├── set_DisplayValues(values)
└── m_rawValue
```

## Model Fields (TextViewDLL TableModel)

```
m_rawRowValues          — raw row values (from ECU)
m_rawColumnValues       — raw column values (from ECU)
m_displayRowValues      — displayed/converted row values
m_displayColumnValues   — displayed/converted column values
m_normalisedRowValues   — normalised row values (0-1 scale)
m_normalisedColumnValues — normalised column values (0-1 scale)
m_percentageRowValues   — percentage row values
m_percentageColumnValues — percentage column values
m_columnZeroPoints      — zero-crossing points per column
```

## Wire Protocol Mapping

### 0x09 matrix5 → TableAxisModel Row/Column Structure

The `matrix5` pattern (5-record repeating units) maps to a row×column grid:

```
Record 0: row_header (04xx) — identifies the row (channel)
Record 1: row_meta (2401/2402) — row metadata (axis info, channel ID)
Record 2: axis_payload (058x) — axis value (column dimension)
Record 3: value_payload (050x) — cell value (row×column intersection)
Record 4: trailer (2501) — row completion marker
```

**Mapping:**
- Each 5-record unit = one cell in the table
- Record 0 (row_header): `row_index` field → maps to `RowModel` index
- Record 1 (row_meta): `2401/2402` → `TableAxisModel.get_AxisName()`, `get_AxisColor()`, `get_AxisUnits()`
- Record 2 (axis_payload): `058x` → `SetupAxisInfo()` axis dimension
- Record 3 (value_payload): `050x` → `Cell` value at row×column
- Record 4 (trailer): `2501` → row completion, triggers `OnRowValuesChanged()`

### 0x09 cycle3 → Single-Dimension Channel Stream

The `cycle3` pattern (3-record repeating units) maps to a single-axis channel:

```
Record 0: row_header (0401) — channel identifier
Record 1: payload_a (0583) — axis/value data
Record 2: payload_b (0503) — cell value
```

**Mapping:**
- Each 3-record unit = one channel value
- Record 0: `RegisterRowChannel()` / `RegisterColumnChannel()`
- Record 1: `SetupRowChannelUnitInfo()` / `SetupColumnChannelUnitInfo()`
- Record 2: `set_DisplayValue()` / `set_DisplayValues()`

### 0x09 setup_burst → Table Initialization

The `setup_burst` pattern (`0400` + `210x` + `058x`/`050x`) maps to table setup:

```
0400: Table initialization marker
210x: Table metadata (column count, row count, etc.)
058x/050x: Axis/channel configuration
```

**Mapping:**
- `0400` → `SetupTableHeaders()`
- `210x` → `TableModel` dimension setup
- `058x/050x` → `SetupAxisInfo()`, `SetupRowChannelUnitInfo()`, `SetupColumnChannelUnitInfo()`

### 0x09 setup_toggle → Connection/State Sync

The `setup_toggle` pattern (`0400`/`0581` pairs) maps to connection state:

```
0400: State change marker
0581: State value
```

**Mapping:**
- Triggers `OnConnectionStateChanged()`, `OnDisplayConnected()`, `OnDisplayDisconnected()`
- `m_connectionAdapter` state updates

## Channel ID Mapping

From the DLL strings, channels are identified by:
- `ChannelID` (int) — unique channel identifier
- `ChannelType` (int) — type code (e.g., gauge, display, trace)
- `ChannelTypeCode` (int) — numeric type code
- `InputChannel` — the channel object itself

The 0x09 protocol's `row_index` field (Record 0) maps to `ChannelID`.
The `row_meta` field (Record 1) maps to `ChannelType`/`ChannelTypeCode`.

## Value Conversion Pipeline

The DLL shows a clear value conversion pipeline:

```
Raw Value (m_rawValue)
  → Display Value (m_displayValue) [via m_fromRawConverter]
  → Normalised Value (m_normalisedValue) [via m_normalisedPointer]
  → Percentage Value (m_percentageValue) [via m_percentageColumnValues/m_percentageRowValues]
```

The 0x09 protocol's `value_payload` (Record 3 for matrix5, Record 2 for cycle3) provides the raw value.
The `axis_payload` (Record 2 for matrix5, Record 1 for cycle3) provides the axis dimension.

## Zero Point Handling

`m_columnZeroPoints` and `FindColumnZeroPoints()` indicate that columns can have zero-crossing points.
This maps to the 0x09 protocol's ability to encode signed values (positive/negative around zero).

## Key Insights

1. **The 0x09 protocol is a table serialization format** — each row is a channel, each column is a dimension.
2. **The `matrix5` pattern is the primary data format** — it encodes a full row×column grid.
3. **The `cycle3` pattern is for single-axis channels** — simpler, faster for single-value updates.
4. **The `setup_burst` pattern initializes the table** — sets up headers, axes, and channel mappings.
5. **The `setup_toggle` pattern handles state changes** — connection, display, and channel state.
6. **Channel IDs from the 0x09 protocol map to `ChannelID` in the DLL** — this is the key to correlating wire data with ECU Manager's channel names.
7. **The value conversion pipeline is explicit** — raw → display → normalised → percentage.
8. **Zero points are column-specific** — each column can have its own zero-crossing points.

## Next Steps

1. **Extract the full channel name list from the ECU Manager binary** — correlate `ChannelID` with human-readable names.
2. **Map the 0x09 `row_index` field to `ChannelID`** — verify this mapping with live capture data.
3. **Implement the value conversion pipeline** — raw → display → normalised → percentage.
4. **Handle zero point encoding** — decode `m_columnZeroPoints` from the 0x09 protocol.
5. **Build a full decoder** — take 0x09 captures and produce a table that matches ECU Manager's display.
