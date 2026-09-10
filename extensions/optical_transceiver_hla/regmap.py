# Register addresses and encoding tables. No logic lives here - decoders import
# these and render them.
#
# Every offset carries the OIF-CMIS-05.4 table it came from so it can be
# re-checked against the spec without re-deriving it. CMIS renumbers tables
# between revisions (e.g. the Data Path State encoding is Table 8-77 in CMIS 5.2
# and Table 8-94 in 5.4), so always cite the table WITH the revision.
#
# A copy of the spec is expected at
#   C:\Users\J03378\Documents\协议书\OIF-CMIS-05.4.pdf
# (PDF page = spec page + 1).

# ---------------------------------------------------------------------------
# SFF-8024 Table 4-1 - pluggable module identifiers at lower memory byte 0.
# Maps identifier byte -> (decoding standard, human readable name).
# ---------------------------------------------------------------------------
IDENTIFIERS = {
    0x03: ('SFF-8472', 'SFP/SFP+'),
    0x0C: ('SFF-8436', 'QSFP+'),
    0x0D: ('SFF-8436', 'QSFP28'),
    0x11: ('SFF-8436', 'QSFP28 (SFF-8636)'),
    0x18: ('CMIS', 'QSFP-DD Double Density'),
    0x19: ('CMIS', 'OSFP 8X Pluggable'),
    0x1E: ('CMIS', 'SFP-DD Double Density'),
    0x1F: ('CMIS', 'DSFP'),
}

# ---------------------------------------------------------------------------
# Lower memory (page-independent), CMIS 5.4 Tables 8-4 .. 8-16
# ---------------------------------------------------------------------------
REG_IDENTIFIER = 0x00
REG_CMIS_REVISION = 0x01
REG_MEMORY_MODEL = 0x02
REG_MODULE_STATE = 0x03          # bits[3:1] state, bit0 InterruptDeasserted
REG_FLAGS_SUMMARY = 0x04         # 4 bytes, one per bank
REG_MODULE_FLAGS = 0x08          # 6 bytes (8 .. 13)
REG_TEMP_MON = 0x0E              # 14-15, S16, 1/256 degC   (Table 8-10)
REG_VCC_MON = 0x10               # 16-17, U16, 100 uV       (Table 8-10)
REG_MEDIA_TYPE = 0x55            # NOT a monitor - see REG_TEMP_MON

# ---------------------------------------------------------------------------
# CMIS 5.4 Table 8-7 - ModuleState, lower memory byte 3 bits[3:1]
# ---------------------------------------------------------------------------
CMIS_MODULE_STATES = {
    1: 'LowPwr (Low Power)',
    2: 'PwrUp (Powering Up)',
    3: 'Ready',
    4: 'PwrDn (Powering Down)',
    5: 'Fault',
}

# ---------------------------------------------------------------------------
# CMIS 5.4 Table 8-8 - FlagsSummary, lower memory bytes 4-7 (one per bank).
# A set bit means "some flag is pending on that upper page".
# ---------------------------------------------------------------------------
CMIS_FLAGS_SUMMARY = {
    3: 'Page2Ch',
    2: 'Page14h',
    1: 'Page12h',
    0: 'Page11h',
}

# ---------------------------------------------------------------------------
# CMIS 5.4 Table 8-9 - module-level temperature/Vcc flags, lower memory byte 9.
# NOTE: this is NOT byte 4. Decoding byte 4 with this table attaches the right
# alarm vocabulary to the wrong bits, which can invert the reported direction.
# ---------------------------------------------------------------------------
CMIS_TEMP_VCC_FLAGS = {
    7: 'VccLowWarn',
    6: 'VccHighWarn',
    5: 'VccLowAlarm',
    4: 'VccHighAlarm',
    3: 'TempLowWarn',
    2: 'TempHighWarn',
    1: 'TempLowAlarm',
    0: 'TempHighAlarm',
}

# Module-level flag bytes 8, 10 and 11 (Table 8-9). Byte 9 holds the
# temperature/Vcc flags and is CMIS_TEMP_VCC_FLAGS above. All four bytes use the
# same bit order within a monitor group: LowWarning, HighWarning, LowAlarm,
# HighAlarm, ascending from bit 0.
CMIS_MODULE_FLAGS_8 = {
    7: 'CdbCmdComplete2',
    6: 'CdbCmdComplete1',
    3: 'AbnormalFwIndication',
    2: 'DataPathFirmwareError',
    1: 'ModuleFirmwareError',
    0: 'ModuleStateChanged',
}

CMIS_AUX12_FLAGS_10 = {
    7: 'Aux2LowWarn',
    6: 'Aux2HighWarn',
    5: 'Aux2LowAlarm',
    4: 'Aux2HighAlarm',
    3: 'Aux1LowWarn',
    2: 'Aux1HighWarn',
    1: 'Aux1LowAlarm',
    0: 'Aux1HighAlarm',
}

CMIS_AUX3_CUSTOM_FLAGS_11 = {
    7: 'CustomLowWarn',
    6: 'CustomHighWarn',
    5: 'CustomLowAlarm',
    4: 'CustomHighAlarm',
    3: 'Aux3LowWarn',
    2: 'Aux3HighWarn',
    1: 'Aux3LowAlarm',
    0: 'Aux3HighAlarm',
}

# Additional monitors, 2 bytes each, signed 16-bit (Table 8-10). The physical
# unit follows the monitor function selected at 01h:145 - laser temperature at
# 1/256 degC or an additional supply rail at 100 uV - which is not decoded, so
# these render the 1/256 reading with no unit suffix rather than assert one.
CMIS_AUX_MONITORS = (
    (0x12, 'aux1', 'Aux1MonValue'),
    (0x14, 'aux2', 'Aux2MonValue'),
    (0x16, 'aux3', 'Aux3MonValue'),
    (0x18, 'custom', 'CustomMonValue'),
)

# Module Control, byte 0x1A (Table 8-11). Bits 2-0 are vendor custom.
REG_MODULE_CONTROL = 0x1A
CMIS_MODULE_CONTROL = {
    7: 'BankBroadcastEnable',
    6: 'LowPwrAllowRequestHW',
    5: 'SquelchMethodSelect',
    4: 'LowPwrRequestSW',
    3: 'SoftwareReset',
}

# Active firmware revision, bytes 39-40 (Table 8-15). A0xFF pair means the load
# is invalid / not yet determined.
REG_FW_ACTIVE_MAJOR = 0x27
REG_FW_ACTIVE_MINOR = 0x28

# Reason for entering the ModuleFault state, byte 41 (Table 8-16).
REG_MODULE_FAULT_CAUSE = 0x29
CMIS_FAULT_CAUSE = {
    0: 'No Fault',
    1: 'TEC runaway',
    2: 'Data memory corrupted',
    3: 'Program memory corrupted',
    4: 'Transmitter fault',
    5: 'Receiver fault',
    6: 'Temperature related fault',
}

# Media type encoding, byte 85 (Table 8-20).
REG_MEDIA_TYPE = 0x55
CMIS_MEDIA_TYPE = {
    0x00: 'Undefined',
    0x01: 'MMF',
    0x02: 'SMF',
    0x03: 'Passive Copper',
    0x04: 'Active Cable',
    0x05: 'BASE-T',
}

# ---------------------------------------------------------------------------
# Page 9Fh - CDB (Command Data Block) message block (Tables 8-197 .. 8-200).
#
# The host writes length, checksum and payload, and writes the CMDID LAST: a
# write that includes the CMDID's low byte is what "sends" the command.
# ---------------------------------------------------------------------------
PAGE9F_CMDID = 0x80            # 128-129, U16, MSB first
PAGE9F_CMDID_LSB = 0x81        # 129 - writing this register sends the command
PAGE9F_EPL_LENGTH = 0x82       # 130-131, U16
PAGE9F_LPL_LENGTH = 0x84       # 132, U8, 0-120
PAGE9F_CHECK_CODE = 0x85       # 133, U8
PAGE9F_RPL_LENGTH = 0x86       # 134, U8
PAGE9F_RPL_CHECK_CODE = 0x87   # 135, U8
PAGE9F_LPL_BASE = 0x88         # 136-255, 120 bytes of local payload
PAGE9F_LPL_MAX = 120

# Bytes excluded from the CdbChkCode sum: the check code itself plus both reply
# header bytes. The spec is explicit that the reply header is never included,
# and that EPLLength and LPLLength always are.
PAGE9F_CHECK_EXCLUDED = (0x85, 0x86, 0x87)

# CDB command IDs. Verified against the individual command sections (9.3 and
# 9.6) rather than the summary range table, whose byte columns do not line up
# with the sections they point at.
CDB_COMMANDS = {
    0x0000: 'Query Status',
    0x0001: 'Enter Password',
    0x0002: 'Change Password',
    0x0004: 'Abort Processing',
    0x0005: 'Get Module Time',
    0x0006: 'Set Module Time',
    0x0100: 'Get Firmware Info',
    0x0101: 'Start Firmware Transfer',
    0x0102: 'Abort Firmware Transfer',
    0x0103: 'Write Firmware Block LPL',
    0x0104: 'Write Firmware Block EPL',
    0x0105: 'Read Firmware Block LPL',
    0x0106: 'Read Firmware Block EPL',
    0x0107: 'Complete Firmware Transfer',
    0x0108: 'Copy Firmware Load',
    0x0109: 'Run Firmware Load',
    0x010A: 'Commit Firmware Load',
    0x010B: 'Check Firmware Activation Options',
    0x010C: 'Store Firmware Load Tag',
    0x010E: 'Retrieve Firmware Load Tag',
}

# ---------------------------------------------------------------------------
# CMIS 5.4 Table 8-94 - Data Path state encoding. There is no "DPFault" state in
# CMIS; 6h is DPTxTurnOff and 7h is DPInitialized.
# ---------------------------------------------------------------------------
CMIS_DP_STATES = {
    0: 'Reserved',
    1: 'DPDeactivated',
    2: 'DPInit',
    3: 'DPDeinit',
    4: 'DPActivated',
    5: 'DPTxTurnOn',
    6: 'DPTxTurnOff',
    7: 'DPInitialized',
}

# ---------------------------------------------------------------------------
# Page 10h - staged Data Path control
# ---------------------------------------------------------------------------
PAGE10_DP_CONFIG_BASE = 145       # 145-152, one byte per lane (Table 8-81)
PAGE10_DP_DEINIT = 128            # DPDeinitLane1..8 bitmap     (Table 8-78)
PAGE10_APPLY_DPINIT = 143         # write-only trigger          (Table 8-80)
PAGE10_APPLY_IMMEDIATE = 144      # write-only trigger          (Table 8-80)

# ---------------------------------------------------------------------------
# Page 01h - advertisements the decoders depend on
# ---------------------------------------------------------------------------
PAGE01_TX_BIAS_SCALING = 160      # bits 4-3 (Table 8-53)

# 01h:145 bits 2/1/0 say what each auxiliary monitor actually measures
# (Table 8-55, spec p.194). The bit meanings are NOT uniform across the three
# Aux monitors, so each one carries its own mapping rather than a shared rule.
REG_AUX_MON_OBSERVABLE = 0x91
AUX_MON_OBSERVABLE_BITS = {'aux1': 0, 'aux2': 1, 'aux3': 2}
AUX_MON_OBSERVABLE = {
    ('aux1', 0): 'custom',
    ('aux1', 1): 'tec_current',
    ('aux2', 0): 'laser_temperature',
    ('aux2', 1): 'tec_current',
    ('aux3', 0): 'laser_temperature',
    ('aux3', 1): 'supply_voltage',
}

# Lower memory 00h:86-117 - eight 4-byte application descriptors (Table 8-24).
# Byte 2 of each holds the lane counts: bits 7-4 host lanes, bits 3-0 media
# lanes. 0xFF in the first descripor byte terminates the list.
REG_APP_DESC_BASE = 0x56
APP_DESC_COUNT = 8
APP_DESC_SIZE = 4
APP_DESC_LANE_COUNT_OFFSET = 2

# TxBiasCurrentScalingFactor, 01h:160 bits 4-3. The multiplier applies to BOTH
# the bias monitor (11h:170-185) and the bias thresholds (02h:184-191), so it
# has to be known before either can be rendered in milliamps.
CMIS_BIAS_SCALING = {0b00: 1.0, 0b01: 2.0, 0b10: 4.0}

# ---------------------------------------------------------------------------
# Page 11h - Data Path status
# ---------------------------------------------------------------------------
PAGE11_DP_STATE_BASE = 128        # 128-131, two 4-bit lanes/byte (Table 8-93)

# Lane output status, one bit per lane; 1 = the module declares the signal on
# that lane valid (Table 8-95, spec p.239).
PAGE11_OUTPUT_STATUS = {
    132: 'OutputStatusRx',
    133: 'OutputStatusTx',
}

# Per-lane monitoring values, 2 bytes each, 8 lanes per block (Table 8-99).
# (base register, field name format, unit)
PAGE11_LANE_MONITORS = (
    (154, 'OpticalPowerTx%d', 'uW'),
    (170, 'LaserBiasTx%d', 'mA'),
    (186, 'OpticalPowerRx%d', 'uW'),
)
PAGE11_LANE_COUNT = 8

# Configuration command result, 4 bits per lane over 4 bytes (Table 8-101).
PAGE11_CONFIG_STATUS_BASE = 202

# CMIS 5.4 Table 8-101 - ConfigStatus codes. 2h-8h are negative results, Ch is
# the in-progress execution status; 9h-Bh and Dh-Fh are reserved.
CMIS_CONFIG_STATUS = {
    0x0: 'ConfigUndefined',
    0x1: 'ConfigSuccess',
    0x2: 'ConfigRejected',
    0x3: 'ConfigRejectedInvalidAppSel',
    0x4: 'ConfigRejectedInvalidDataPath',
    0x5: 'ConfigRejectedInvalidSI',
    0x6: 'ConfigRejectedLanesInUse',
    0x7: 'ConfigRejectedPartialDataPath',
    0x8: 'ConfigRejectedNoEmulation',
    0xC: 'ConfigInProgress',
}

# Page 11h per-lane flag registers, one bit per lane (bit 0 = lane 1).
# CMIS 5.4 Tables 8-96 .. 8-98 (spec pp.236-241). Field names follow the
# existing output vocabulary where the register already had one.
PAGE11_FLAG_FIELDS = {
    134: 'DP State Changed Flags',
    135: 'Tx Fault Flags',
    136: 'Tx LOS Flags',
    137: 'Tx CDRLOL Flags',
    138: 'Tx Adaptive EQ Fail Flags',
    139: 'Tx Power High Alarm Flags',
    140: 'Tx Power Low Alarm Flags',
    141: 'Tx Power High Warn Flags',
    142: 'Tx Power Low Warn Flags',
    143: 'Tx Bias High Alarm Flags',
    144: 'Tx Bias Low Alarm Flags',
    145: 'Tx Bias High Warn Flags',
    146: 'Tx Bias Low Warn Flags',
    147: 'Rx LOS Flags',
    148: 'Rx LOL Flags',
    149: 'Rx Power High Alarm Flags',
    150: 'Rx Power Low Alarm Flags',
    151: 'Rx Power High Warn Flags',
    152: 'Rx Power Low Warn Flags',
    153: 'Rx Output Status Changed Flags',
}

# ---------------------------------------------------------------------------
# Page 00h - administrative information (Table 8-26)
# ---------------------------------------------------------------------------
# ASCII and U24 fields (Table 8-26, spec p.184). (first, last, label, kind).
# Each is shown character by character as it arrives, and the assembled value
# takes the place of the final character - see StringAssembler.
PAGE00_STRINGS = (
    (129, 144, 'Vendor Name', 'ascii'),
    (145, 147, 'Vendor OUI', 'oui'),
    (148, 163, 'Part Number', 'ascii'),
    (164, 165, 'Vendor Rev', 'ascii'),
    (166, 181, 'Vendor Serial', 'ascii'),
    (182, 189, 'Date Code', 'ascii'),
    (190, 199, 'CLEI Code', 'ascii'),
)

# ---------------------------------------------------------------------------
# Page 02h - supervision thresholds, all read-only (Tables 8-64 / 8-65).
#
# Nine groups of 8 bytes; each group is four 2-byte thresholds in the order
# HighAlarm, LowAlarm, HighWarning, LowWarning. The temp and Vcc groups are
# cross-validated against the real capture: decoding there yields 75.00/-5.00/
# 70.00/0.00 degC and 3.630/2.970/3.465/3.135 V, while a +/-2 byte shift yields
# nonsense. The Aux/Custom unit depends on the monitor function selected at
# 01h:145, which is not decoded yet.
# ---------------------------------------------------------------------------
# (base register, field label, unit, aux monitor key). The unit 'aux' means the
# real unit is whatever that auxiliary monitor measures - see user_config.
PAGE02_THRESHOLD_GROUPS = (
    (128, 'TempMon', 'degC', None),
    (136, 'VccMon', 'V', None),
    (144, 'Aux1Mon', 'aux', 'aux1'),
    (152, 'Aux2Mon', 'aux', 'aux2'),
    (160, 'Aux3Mon', 'aux', 'aux3'),
    (168, 'CustomMon', 'aux', 'custom'),
    (176, 'OpticalPowerTx', 'uW', None),
    (184, 'LaserBias', 'mA', None),
    (192, 'OpticalPowerRx', 'uW', None),
)

_THRESHOLD_SUFFIXES = ('HighAlarm', 'LowAlarm', 'HighWarning', 'LowWarning')

# register -> (field name, unit, aux key). Names follow the spec's own register
# names so they stay greppable and CSV consumers can pivot on them.
PAGE02_THRESHOLDS = {
    _base + 2 * _i: (f'{_label}{_suffix}Threshold', _unit, _aux)
    for _base, _label, _unit, _aux in PAGE02_THRESHOLD_GROUPS
    for _i, _suffix in enumerate(_THRESHOLD_SUFFIXES)
}
