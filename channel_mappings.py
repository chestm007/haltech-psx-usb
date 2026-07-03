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
