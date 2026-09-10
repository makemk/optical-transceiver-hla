# Regression tests for the CMIS register corrections in Stage 1.
# Feeds synthetic I2C frames straight into the HLA - no Logic 2 required.
#
# Every expected register offset here is taken from OIF-CMIS-05.4 (Tables 8-8,
# 8-9, 8-10, 8-78..8-81, 8-93, 8-94) and cross-checked against the register map
# in Downloads/cmis-module-manager/cmis_registers.py.

import os
import sys

EXT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'extensions', 'optical_transceiver_hla'))
sys.path.insert(0, EXT_DIR)

from optical_hla import OpticalTransceiverHla, AnalyzerFrame  # noqa: E402
import user_config  # noqa: E402

# The extension logs to hla_debug.log next to itself, which a running Logic 2
# also holds open; on Windows the 1 MB rotation then fails and logging prints a
# traceback to stderr. The tests do not need the file log.
import logging  # noqa: E402
logging.getLogger("OpticalTransceiverHLA").handlers = []
logging.getLogger("OpticalTransceiverHLA").addHandler(logging.NullHandler())

FAILURES = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s\n          got:  %r\n          want: %r" % (name, got, want))
        FAILURES.append(name)


class Bus:
    """Drives the HLA the way the I2C analyzer would."""

    def __init__(self, standard='CMIS (QSFP-DD/OSFP)', output_mode='Per Byte',
                 compliance_mode='Warnings + Errors'):
        self.hla = OpticalTransceiverHla({'module_standard': standard,
                                          'filter_mode': 'Show All',
                                          'output_mode': output_mode,
                                          'compliance_mode': compliance_mode})
        self.t = 0.0

    def _frame(self, ftype, **data):
        self.t += 1e-4
        return AnalyzerFrame(ftype, self.t, self.t + 1e-5, data)

    def feed(self, frame):
        return self.hla.decode(frame)

    def set_page(self, page):
        """Write transaction [0x7F, page] on 0x50. Returns the frames it emitted,
        which for a compliance run includes the transaction's own stop frame."""
        return self.write(0x7F, [page])

    def read(self, reg, values, addr=0x50):
        """Write pointer, repeated start, read N bytes. Returns emitted frames."""
        self.feed(self._frame('start'))
        self.feed(self._frame('address', address=[addr], read=False, ack=True))
        self.feed(self._frame('data', data=[reg], ack=True))
        self.feed(self._frame('start'))
        self.feed(self._frame('address', address=[addr], read=True, ack=True))
        out = []
        for v in values:
            r = self.feed(self._frame('data', data=[v], ack=True))
            for f in (r if isinstance(r, list) else [r]):
                if f is not None:
                    out.append(f)
        r = self.feed(self._frame('stop'))
        for f in (r if isinstance(r, list) else [r]):
            if f is not None:
                out.append(f)
        return out

    def write(self, reg, values, addr=0x50):
        self.feed(self._frame('start'))
        self.feed(self._frame('address', address=[addr], read=False, ack=True))
        out = []
        for v in [reg] + list(values):
            r = self.feed(self._frame('data', data=[v], ack=True))
            for f in (r if isinstance(r, list) else [r]):
                if f is not None:
                    out.append(f)
        r = self.feed(self._frame('stop'))
        for f in (r if isinstance(r, list) else [r]):
            if f is not None:
                out.append(f)
        return out


def fields(frames):
    return [(f.data.get('field'), f.data.get('value'))
            for f in frames if f.type == 'optical_field']


def value_of(frames, field):
    for f, v in fields(frames):
        if f == field:
            return v
    return None


def main():
    print("=" * 72)
    print("CMIS register corrections - Stage 1")
    print("=" * 72)

    # --- lower memory monitors -------------------------------------------
    print("\n[Table 8-10] module monitors at 00h:14-17, NOT 85-88")
    b = Bus()
    b.read(0x00, [0x18])                    # identifier -> QSFP-DD, classifies CMIS
    f = b.read(14, [0x27, 0xA5])            # 0x27A5 = 10149 / 256 = 39.6445 C
    check("temperature decoded from 00h:14-15", value_of(f, 'Module Temperature'), '39.64 °C')
    f = b.read(16, [0x8C, 0x49])            # 0x8C49 * 100uV = 3.5913 V
    check("Vcc decoded from 00h:16-17", value_of(f, 'Supply Voltage Vcc'), '3.591 V')

    f = b.read(85, [0x01, 0x00])
    check("00h:85 is NOT a temperature", value_of(f, 'Module Temperature'), None)

    # --- flags ------------------------------------------------------------
    print("\n[Tables 8-8 / 8-9] FlagsSummary at 00h:4-7, temp/Vcc flags at 00h:9")
    b = Bus()
    b.read(0x00, [0x18])
    f = b.read(4, [0x01, 0x00, 0x00, 0x00])
    check("00h:4 is Flags Summary, not Global Flags",
          value_of(f, 'Flags Summary (bank 0)'), 'Page11h')
    check("00h:4 emits no Global Flags", value_of(f, 'Global Flags'), None)

    f = b.read(9, [0x40])
    check("00h:9 bit6 -> VccHighWarn (was reported inverted)",
          value_of(f, 'Global Flags'), 'VccHighWarn')
    f = b.read(9, [0x80])
    check("00h:9 bit7 -> VccLowWarn", value_of(f, 'Global Flags'), 'VccLowWarn')
    f = b.read(9, [0x01])
    check("00h:9 bit0 -> TempHighAlarm", value_of(f, 'Global Flags'), 'TempHighAlarm')
    f = b.read(9, [0x00])
    check("00h:9 clear -> OK (Normal)", value_of(f, 'Global Flags'), 'OK (Normal)')

    # --- page 10h ---------------------------------------------------------
    print("\n[Tables 8-78 / 8-80 / 8-81] page 10h control")
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x10)
    f = b.read(145, [0x11])
    check("DPConfigLane bit0 is ExplicitControl, not part of DataPathID",
          value_of(f, 'Lane 1 DataPath Ctrl'), 'AppSel=1, DataPathID=0, ExplicitControl=1')
    f = b.read(145, [0x26])
    check("DPConfigLane bits3-1 are DPIDX",
          value_of(f, 'Lane 1 DataPath Ctrl'), 'AppSel=2, DataPathID=3, ExplicitControl=0')
    f = b.write(128, [0x05])
    check("10h:128 is the DPDeinitLane bitmap",
          value_of(f, 'DP Deinit Lanes'), '0x05 (deinit lane 1, 3)')
    f = b.write(128, [0x00])
    check("10h:128 all clear -> initialize",
          value_of(f, 'DP Deinit Lanes'), '0x00 (initialize all lanes)')
    f = b.write(143, [0x03])
    check("10h:143 is ApplyDPInit", value_of(f, 'ApplyDPInit'), 'lane 1, 2')
    f = b.write(144, [0x00])
    check("10h:144 is ApplyImmediate", value_of(f, 'ApplyImmediate'), 'no lanes selected')

    # --- page 11h ---------------------------------------------------------
    print("\n[Tables 8-93 / 8-94 / 8-97 / 8-98] page 11h status")
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x11)
    f = b.read(128, [0x41])
    check("DP state base is 11h:128; low nibble is the lower lane",
          value_of(f, 'Lane 1-2 DP State'), 'Lane 1: DPDeactivated, Lane 2: DPActivated')
    f = b.read(131, [0x76])
    check("11h:131 carries lanes 7 and 8",
          value_of(f, 'Lane 7-8 DP State'), 'Lane 7: DPTxTurnOff, Lane 8: DPInitialized')
    f = b.read(129, [0x00])
    check("0h decodes as Reserved",
          value_of(f, 'Lane 3-4 DP State'), 'Lane 3: Reserved, Lane 4: Reserved')
    f = b.read(134, [0x00])
    check("11h:134 is NOT DP state (it is DPStateChanged)",
          value_of(f, 'Lane 1-2 DP State'), None)
    f = b.read(135, [0x05])
    check("11h:135 Tx Fault with lane expansion",
          value_of(f, 'Tx Fault Flags'), '0x05 (1, 3)')
    f = b.read(147, [0xFF])
    check("11h:147 Rx LOS with lane expansion",
          value_of(f, 'Rx LOS Flags'), '0xFF (1, 2, 3, 4, 5, 6, 7, 8)')
    f = b.read(148, [0x00])
    check("11h:148 Rx LOL", value_of(f, 'Rx LOL Flags'), '0x00 (none)')

    # --- page 02h thresholds ---------------------------------------------
    # Expected values are the ones the real capture yields at these offsets
    # (cmis_real_decoded.csv), which is what pins the byte positions down.
    print("\n[Tables 8-64 / 8-65] page 02h supervision thresholds")
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.read(128, [0x4B, 0x00])
    check("02h:128 TempMonHighAlarmThreshold",
          value_of(f, 'TempMonHighAlarmThreshold'), '75.00 °C')
    f = b.read(130, [0xFB, 0x00])
    check("02h:130 TempMonLowAlarmThreshold is signed",
          value_of(f, 'TempMonLowAlarmThreshold'), '-5.00 °C')
    f = b.read(132, [0x46, 0x00])
    check("02h:132 TempMonHighWarningThreshold",
          value_of(f, 'TempMonHighWarningThreshold'), '70.00 °C')
    f = b.read(140, [0x87, 0x5A])
    check("02h:140 VccMonHighWarningThreshold",
          value_of(f, 'VccMonHighWarningThreshold'), '3.465 V')
    f = b.read(136, [0x8D, 0xCC])
    check("02h:136 VccMonHighAlarmThreshold",
          value_of(f, 'VccMonHighAlarmThreshold'), '3.630 V')
    f = b.read(176, [0x15, 0x7C])
    check("02h:176 OpticalPowerTxHighAlarmThreshold renders as power",
          value_of(f, 'OpticalPowerTxHighAlarmThreshold'), '-2.60 dBm (550.0 uW)')

    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.write(128, [0x4B, 0x00])
    check("a write to read-only page 02h is reported, not decoded",
          value_of(f, 'TempMonHighAlarmThreshold'), None)

    # --- lower memory module flags, control, identity ---------------------
    print("\n[Tables 8-9 / 8-10 / 8-11 / 8-15 / 8-16 / 8-20] lower memory")
    b = Bus()
    b.read(0x00, [0x18])
    f = b.read(8, [0x03])
    check("00h:8 module flags (bit0 ModuleStateChanged, bit1 ModuleFirmwareError)",
          value_of(f, 'Module Flags'), 'ModuleFirmwareError, ModuleStateChanged')
    f = b.read(10, [0x80])
    check("00h:10 Aux 1/2 flags", value_of(f, 'Aux 1/2 Flags'), 'Aux2LowWarn')
    f = b.read(11, [0x08])
    check("00h:11 Aux 3 / Custom flags", value_of(f, 'Aux 3 / Custom Flags'), 'Aux3LowWarn')
    # Aux1 defaults to the spec's 0b meaning (vendor custom), whose scale is not
    # established, so the raw value is reported and the assumption is named.
    f = b.read(18, [0x23, 0x80])                  # 0x2380 = 9088
    check("00h:18-19 Aux1 monitor falls back to raw when the scale is unknown",
          value_of(f, 'Aux1MonValue'), '9088 (raw) [assumed custom]')
    f = b.read(20, [0x23, 0x80])
    check("Aux2 defaults to laser temperature, so it scales",
          value_of(f, 'Aux2MonValue'), '35.50 °C [assumed laser_temperature]')
    f = b.read(26, [0x88])
    check("00h:26 Module Control",
          value_of(f, 'Module Control'), 'BankBroadcastEnable, SoftwareReset')
    f = b.read(39, [0x01, 0x02])
    check("00h:39-40 active firmware revision",
          value_of(f, 'FW Active Revision'), '1.2')
    f = b.read(39, [0xFF, 0xFF])
    check("an all-ones firmware revision is called out as invalid",
          value_of(f, 'FW Active Revision'), 'invalid (0xFF.0xFF)')
    f = b.read(41, [0x01])
    check("00h:41 fault cause", value_of(f, 'Module Fault Cause'), 'TEC runaway')
    f = b.read(0x55, [0x02])                      # 0x55 = 85 decimal, not 55
    check("00h:55 media type", value_of(f, 'Media Type'), 'SMF (0x02)')

    # --- page 11h lane monitors and status --------------------------------
    print("\n[Tables 8-95 / 8-99 / 8-101] page 11h monitors and status")
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x11)
    f = b.read(154, [0x15, 0x7C])
    check("11h:154-155 OpticalPowerTx1",
          value_of(f, 'OpticalPowerTx1'), '-2.60 dBm (550.0 uW)')
    f = b.read(186, [0x15, 0x7C])
    check("11h:186-187 OpticalPowerRx1",
          value_of(f, 'OpticalPowerRx1'), '-2.60 dBm (550.0 uW)')
    f = b.read(132, [0x03])
    check("11h:132 OutputStatusRx expands to lanes",
          value_of(f, 'OutputStatusRx'), '0x03 (1, 2)')
    f = b.read(202, [0x12])
    check("11h:202 ConfigStatus carries lanes 1 and 2",
          value_of(f, 'ConfigStatus Lane 1-2'),
          'Lane 1: ConfigRejected, Lane 2: ConfigSuccess')
    f = b.read(205, [0x0C, 0x00])
    check("11h:205 bit 0 is lane 7; Ch is ConfigInProgress",
          value_of(f, 'ConfigStatus Lane 7-8'),
          'Lane 7: ConfigInProgress, Lane 8: ConfigUndefined')

    # --- 01h:160 bias scaling applies to monitor AND threshold ------------
    print("\n[Table 8-53] 01h:160 TxBiasCurrentScalingFactor")
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x11)
    f = b.read(170, [0x0C, 0xC6])
    check("bias monitor without the advertisement says so",
          value_of(f, 'LaserBiasTx1'), '6.54 mA (x1 assumed)')

    b.set_page(0x01)
    f = b.read(160, [0x08])                       # bits 4-3 = 01b -> x2
    check("01h:160 decodes the scaling factor",
          value_of(f, 'TxBiasCurrentScalingFactor'), 'x2')
    b.set_page(0x11)
    f = b.read(170, [0x0C, 0xC6])
    check("bias monitor scales, and drops the caveat",
          value_of(f, 'LaserBiasTx1'), '13.08 mA')
    b.set_page(0x02)
    f = b.read(184, [0x13, 0x88])                 # 0x1388 = 5000 * 2uA = 10mA at x1
    check("bias threshold scales too (spec: Table 8-65 as well as 8-99)",
          value_of(f, 'LaserBiasHighAlarmThreshold'), '20.00 mA')

    # --- assembled identity strings ---------------------------------------
    print("\n[Table 8-26] assembled identity strings")
    b = Bus(standard='SFF-8472 (SFP/SFP+)')
    b.read(0x00, [0x03])
    f = b.read(20, [ord(c) for c in 'FINISAR CORP.   '])      # 16 chars, 20-35
    check("SFF-8472 A0h vendor name assembles on its final byte",
          value_of(f, 'Vendor Name'), "'FINISAR CORP.'")
    check("the earlier characters still show one by one",
          value_of(f, 'Vendor Name[20]'), "'F' (0x46)")

    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x00)
    f = b.read(148, [ord(c) for c in 'TR-F401-XXX     '])     # 16 chars, 148-163
    check("CMIS page 00h part number assembles",
          value_of(f, 'Part Number'), "'TR-F401-XXX'")
    f = b.read(145, [0x00, 0x90, 0x65])
    check("the vendor OUI renders as hex, not as characters",
          value_of(f, 'Vendor OUI'), '00-90-65')

    # A run that starts mid-field must NOT be presented as the whole field.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x00)
    f = b.read(130, [ord('X')] * 15)                          # 130-144, misses 129
    check("a run not starting at the field's first byte is not assembled",
          value_of(f, 'Vendor Name'), None)
    check("...but its characters are still shown individually",
          value_of(f, 'Vendor Name[130]'), "'X' (0x58)")

    # --- user_config overrides and capture-derived values -----------------
    print("\n[user_config] precedence: explicit setting > capture > default")
    original_load = user_config.load
    try:
        # An explicit aux function is used and must NOT be flagged as assumed.
        user_config.load = lambda *a, **k: dict(
            user_config.DEFAULTS,
            aux_monitor_functions={'aux1': 'laser_temperature', 'aux2': 'auto',
                                   'aux3': 'auto', 'custom': 'custom'},
        )
        b = Bus()
        b.read(0x00, [0x18])
        f = b.read(18, [0x23, 0x80])
        check("an explicit aux function is applied and carries no caveat",
              value_of(f, 'Aux1MonValue'), '35.50 °C')

        # ...and the tEC-current function has no established scale, so it must
        # report raw rather than a scaled number.
        user_config.load = lambda *a, **k: dict(
            user_config.DEFAULTS,
            aux_monitor_functions={'aux1': 'tec_current', 'aux2': 'auto',
                                   'aux3': 'auto', 'custom': 'custom'},
        )
        b = Bus()
        b.read(0x00, [0x18])
        f = b.read(18, [0x23, 0x80])
        check("a function with no established scale reports raw",
              value_of(f, 'Aux1MonValue'), '9088 (raw)')

        # Caveats can be turned off wholesale.
        user_config.load = lambda *a, **k: dict(user_config.DEFAULTS,
                                                show_assumption_caveats=False)
        b = Bus()
        b.read(0x00, [0x18])
        f = b.read(18, [0x23, 0x80])
        check("show_assumption_caveats=False silences the marker",
              value_of(f, 'Aux1MonValue'), '9088 (raw)')
    finally:
        user_config.load = original_load

    # 01h:145 tells the decoder what each auxiliary monitor actually measures,
    # which beats the spec's 0b default and removes the assumption marker.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x01)
    f = b.read(0x91, [0x02])                      # bit1 -> aux2 = TEC current
    check("01h:145 reports what the auxiliary monitors measure",
          value_of(f, 'Aux Monitor Function'),
          'AUX1=custom, AUX2=tec_current, AUX3=laser_temperature')
    f = b.read(20, [0x23, 0x80])
    check("aux2 now uses the observed function, and is no longer 'assumed'",
          value_of(f, 'Aux2MonValue'), '9088 (raw)')

    # --- CDB (page 9Fh) ----------------------------------------------------
    print("\n[Tables 8-197..8-200] CDB message block")

    def send_command(cmdid, lpl, check, epl_length=0):
        """Compose a CDB command the way a host does: lengths and check code
        first, then the payload, then the CMDID - which sends it."""
        b = Bus()
        b.read(0x00, [0x18])
        b.set_page(0x9F)
        b.write(130, [(epl_length >> 8) & 0xFF, epl_length & 0xFF, len(lpl), check])
        if lpl:
            b.write(136, lpl)
        frames = b.write(128, [(cmdid >> 8) & 0xFF, cmdid & 0xFF])
        return frames

    # 128..137 minus 133-135 = 01 + 01 + 00 + 00 + 02 + 00 + 00 = 4; ~4 = 0xFB
    f = send_command(0x0101, [0x00, 0x00], 0xFB)
    check("a command is reported when its CMDID is written",
          value_of(f, 'CDB Command'),
          'CMD 0101h (Start Firmware Transfer) | LPL=2 EPL=0, check code OK')

    # With LPLLength 0 the sum is registers 128..135 minus 133-135, i.e. just
    # 128-132: 01 + 00 + 00 + 00 + 00 = 1, and ~1 = 0xFE.
    f = send_command(0x0100, [], 0xFE)
    check("a command with no payload reports zero lengths",
          value_of(f, 'CDB Command'), 'CMD 0100h (Get Firmware Info) | LPL=0 EPL=0'
          + ', check code OK')

    # 02 + 42 + 00 + 00 + 00 = 0x44, and ~0x44 = 0xBB.
    f = send_command(0x0242, [], 0xBB)
    check("an unrecognised command ID is still reported",
          value_of(f, 'CDB Command'), 'CMD 0242h (unknown command) | LPL=0 EPL=0'
          + ', check code OK')

    # A check code that does not match its own message block is a corrupt
    # command, and the only place it can be caught is here.
    f = send_command(0x0101, [0x00, 0x00], 0x00)
    check("a mismatched check code is called out in the field",
          'CHECK CODE MISMATCH' in (value_of(f, 'CDB Command') or ''), True)
    check("...and raised as a finding",
          any('CDB_CHECK_CODE' in x.data.get('message', '')
              for x in f if x.type == 'optical_compliance'), True)

    # The reply header is the module's; RPLLength and RPLChkCode are read back.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x9F)
    f = b.read(134, [0x04, 0x9B])
    check("the reply header decodes", value_of(f, 'RPL Length'), '4 bytes')
    check("...including the module's own check code",
          value_of(f, 'RPL Check Code'), '0x9B')

    # --- consistency checks ------------------------------------------------
    print("\n[compliance] consistency rules")

    def findings(frames):
        return [f for f in frames if f.type == 'optical_compliance']

    def messages(frames):
        return '; '.join(f.data.get('message', '') for f in findings(frames))

    # A threshold left at zero is unprogrammed, and every comparison against it
    # is meaningless.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.read(134, [0x00, 0x00])           # TempMonLowWarning = 0
    check("an all-zero threshold is reported",
          'THRESHOLD_UNINITIALIZED' in messages(f), True)

    # Warm warning sitting ABOVE the warm alarm means it can never warn first.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.read(128, [0x46, 0x00])           # HighAlarm  = 70.00
    f = b.read(132, [0x4B, 0x00])           # HighWarn   = 75.00  (inverted)
    check("an inverted alarm/warning pair is reported",
          'THRESHOLD_ORDER' in messages(f), True)

    # A reading past its own alarm with the matching flag clear: one of the two
    # is wrong, and this is the check that catches a mis-mapped flag register.
    # The threshold, the flags and the monitor are read in three different
    # transactions, which is how a real host does it - the rule has to join them.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    b.read(128, [0x46, 0x00])               # TempMon HighAlarm = 70.00 °C
    b.read(9, [0x00])                       # flags clear
    f = b.read(14, [0x4E, 0x20])            # 0x4E20 / 256 = 80.00 °C
    check("a monitor past its alarm with no flag set is reported",
          'MONITOR_FLAG_MISMATCH' in messages(f), True)

    # ...and the same reading is NOT reported once the module raises the flag.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    b.read(128, [0x46, 0x00])
    b.read(9, [0x01])                       # TempHighAlarm flag set
    f = b.read(14, [0x4E, 0x20])
    check("no finding when the module does raise the flag",
          'MONITOR_FLAG_MISMATCH' in messages(f), False)

    # Without ever having seen the flag byte there is no way to know whether
    # the flag is clear, so the rule must stay quiet rather than assume.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    b.read(128, [0x46, 0x00])
    f = b.read(14, [0x4E, 0x20])
    check("no finding when the flag byte was never read",
          'MONITOR_FLAG_MISMATCH' in messages(f), False)

    # REGRESSION: selecting page 02h is itself a write performed while the page
    # is 02h, so a rule keyed on direction+page flagged every page select in the
    # capture - 39 findings, all false.
    b = Bus()
    b.read(0x00, [0x18])
    f = b.set_page(0x02)
    check("selecting a read-only page is not a write TO that page",
          'WRITE_TO_READ_ONLY' in messages(f), False)

    # ...but writing a register ON the page still is.
    b = Bus()
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.write(134, [0x00, 0x00])
    check("writing a register on the read-only page is reported",
          'WRITE_TO_READ_ONLY' in messages(f), True)

    # The kill switch.
    b = Bus(compliance_mode='Off')
    b.read(0x00, [0x18])
    b.set_page(0x02)
    f = b.read(134, [0x00, 0x00])
    check("compliance_mode='Off' silences every rule",
          findings(f), [])

    # --- transaction summary output mode ----------------------------------
    print("\n[Output Mode] Transaction Summary")
    b = Bus(output_mode='Transaction Summary')
    b.read(0x00, [0x18])
    f = b.read(14, [0x27, 0xA5])
    check("one complete frame per transaction, not one per byte",
          [x.type for x in f], ['optical_txn'])
    summary = f[0].data.get('summary') or ''
    check("the summary carries the decoded field",
          'Module Temperature: 39.64 °C' in summary, True)
    check("the header states direction, address, page and byte count",
          summary.startswith('RD 0x50 pg00 3B'), True)

    b = Bus(output_mode='Transaction Summary')
    b.read(0x00, [0x18])
    f = b.read(9, [0x40])
    check("a state change makes the transaction a control one",
          f[0].type == 'optical_txn' and 'VccHighWarn' in (f[0].data.get('summary') or ''),
          True)

    b = Bus(output_mode='Transaction Summary')
    b.read(0x00, [0x18])
    f = b.read(200, [0x00])            # a register nothing decodes
    check("a transaction with no decoded fields still reports itself",
          [x.type for x in f], ['optical_txn'])
    check("...with the byte count and nothing else",
          f[0].data.get('summary'), 'RD 0x50 pg00 2B')

    # --- stale multi-byte pairing ----------------------------------------
    print("\n[stale MSB] a half-read register must not pair across pages")
    b = Bus()
    b.read(0x00, [0x18])
    b.read(14, [0x27])              # temperature MSB only, no LSB
    b.set_page(0x10)                # page changes
    f = b.read(15, [0xA5])          # LSB arrives on a different page
    check("MSB from another page is not consumed",
          value_of(f, 'Module Temperature'), None)

    b = Bus()
    b.read(0x00, [0x18])
    b.read(14, [0x27])              # MSB only
    f = b.read(15, [0xA5])          # proper adjacent LSB, same context
    check("adjacent LSB in the same context still pairs",
          value_of(f, 'Module Temperature'), '39.64 °C')

    b = Bus()
    b.read(0x00, [0x18])
    b.read(14, [0x27])              # MSB at reg 14
    f = b.read(17, [0xA5])          # LSB-shaped value at reg 17, not 15
    check("non-adjacent register does not consume the stash",
          value_of(f, 'Module Temperature'), None)

    print("\n" + "=" * 72)
    if FAILURES:
        print("FAILED: %d check(s)" % len(FAILURES))
        for n in FAILURES:
            print("   - %s" % n)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    sys.exit(main())
