# CMIS protocol decoder (OIF-CMIS 5.4, QSFP-DD / OSFP / SFP-DD).
#
# Pure register semantics: this module receives an Access and returns a Field,
# or None when the byte is not something CMIS defines. It never sees an I2C
# frame and never builds an AnalyzerFrame.
#
# Layout: lower memory (bytes 0-127) is page-independent, so it dispatches on
# the register alone. Upper memory (128-255) is paged, so it dispatches on the
# page and each page gets its own method. Adding a page means adding a method
# and one line in _PAGES - nothing else in the file changes.

import logging

from decode_utils import (
    temperature_c, voltage_v, threshold_str, threshold_value, bias_ma,
    power_str, power_uw, lane_bitmap, flag_names, char_field, ascii_string,
    s16, u16,
)
from cdb import CdbDecoder
from fields import CONSUMED, Field, StringAssembler
import regmap
import user_config

logger = logging.getLogger("OpticalTransceiverHLA")

ADDR_A0H = 0x50

# Lane bits rendered when nothing says how many lanes the module has.
DEFAULT_LANE_COUNT = 8


def _render_identity(kind, raw):
    """Format an assembled page 00h identity field.

    Most of these are ASCII, but the vendor OUI is a 24-bit IEEE company id and
    would be meaningless rendered as characters.
    """
    if kind == 'oui':
        return '-'.join('%02X' % byte for byte in raw)
    return "'%s'" % ascii_string(raw)


class CmisDecoder:
    NAME = 'CMIS'

    def __init__(self):
        self.config = user_config.load()

        # What the capture itself told us. Anything here wins over the shipped
        # defaults but loses to an explicit user_config override; see the
        # _observed_* / _resolve helpers below. Kept per decoder instance, and
        # the Dispatcher gives each HLA instance its own decoder.
        self.observed_aux_functions = {}
        self.observed_bias_scaling = None
        self.observed_lane_count = None
        self._descriptor_head = None
        self.strings = StringAssembler()
        # Page 9Fh is big enough to own a module of its own; it keeps the state
        # of the command message block as the host composes it.
        self.cdb = CdbDecoder()

    # --- configured / observed values --------------------------------------
    #
    # Three sources, in order of precedence: an explicit user_config setting,
    # what the capture itself advertised, then a documented default. Only the
    # last is an assumption, and when it is used the rendered value says so -
    # unless show_assumption_caveats is turned off.

    def _caveats(self):
        return bool(self.config.get('show_assumption_caveats', True))

    def _bias_state(self):
        """(Tx bias scaling factor, whether it is actually known)."""
        override = self.config.get('tx_bias_scaling')
        if override is not None and override != user_config.AUTO:
            try:
                return float(override), True
            except (TypeError, ValueError):
                logger.warning("[CMIS] user_config tx_bias_scaling=%r is not a "
                               "number; falling back to the capture", override)
        if self.observed_bias_scaling is not None:
            return self.observed_bias_scaling, True
        return 1.0, False

    def _bias_text(self, msb, lsb):
        factor, known = self._bias_state()
        text = "%.2f mA" % bias_ma(msb, lsb, factor)
        if not known and self._caveats():
            text += ' (x1 assumed)'
        return text

    def _aux_state(self, which):
        """(auxiliary monitor function, whether it is actually known)."""
        override = (self.config.get('aux_monitor_functions') or {}).get(which)
        if override is not None and override != user_config.AUTO:
            return override, True
        observed = self.observed_aux_functions.get(which)
        if observed is not None:
            return observed, True
        return user_config.DEFAULT_AUX_FUNCTIONS.get(which, 'unknown'), False

    def _aux_text(self, which, msb, lsb):
        """Render an auxiliary monitor reading.

        Two independent things can be unknown here, and the output distinguishes
        them: the function (what the monitor measures, assumed from the spec's
        0b default when 01h:145 was never read) and the scale (whether that
        function's encoding is established at all). A raw integer is reported
        rather than a scaled number whenever the scale is unknown.
        """
        name, known = self._aux_state(which)
        scale, unit, signed = user_config.monitor_function(name, self.config)
        raw = s16(msb, lsb) if signed else u16(msb, lsb)
        text = '%d (raw)' % raw if scale is None else '%.2f %s' % (raw * scale, unit)
        if not known and self._caveats():
            text += ' [assumed %s]' % name
        return text

    def _lane_count(self):
        override = self.config.get('lane_count')
        count = self.observed_lane_count
        if override is not None and override != user_config.AUTO:
            count = override
        if count is None:
            return DEFAULT_LANE_COUNT
        try:
            return max(1, min(8, int(count)))
        except (TypeError, ValueError):
            logger.warning("[CMIS] user_config lane_count=%r is not a number; using %d",
                           count, DEFAULT_LANE_COUNT)
            return DEFAULT_LANE_COUNT

    # --- entry point -------------------------------------------------------

    def decode(self, access, asm):
        if access.addr != ADDR_A0H:
            return None
        if access.reg < 0x80:
            return self._lower_memory(access, asm)
        return self._upper_memory(access, asm)

    # --- lower memory: page-independent ------------------------------------

    def _lower_memory(self, access, asm):
        reg = access.reg

        # identity and state
        if reg == regmap.REG_CMIS_REVISION:
            return self._revision(access)
        if reg == regmap.REG_MODULE_STATE:
            return self._module_state(access)

        # latched flags, bytes 4-11
        if regmap.REG_FLAGS_SUMMARY <= reg < regmap.REG_FLAGS_SUMMARY + 4:
            return self._flags_summary(access)
        if reg == 0x08:
            return self._flag_byte('Module Flags', access, regmap.CMIS_MODULE_FLAGS_8)
        if reg == 0x09:
            return self._flag_byte('Global Flags', access, regmap.CMIS_TEMP_VCC_FLAGS)
        if reg == 0x0A:
            return self._flag_byte('Aux 1/2 Flags', access, regmap.CMIS_AUX12_FLAGS_10)
        if reg == 0x0B:
            return self._flag_byte('Aux 3 / Custom Flags', access,
                                   regmap.CMIS_AUX3_CUSTOM_FLAGS_11)

        # monitors, bytes 14-25
        if reg == regmap.REG_TEMP_MON:
            asm.stash(access)
            return CONSUMED
        if reg == regmap.REG_TEMP_MON + 1:
            msb = asm.take(access)
            return None if msb is None else self._temperature(msb, access)
        if reg == regmap.REG_VCC_MON:
            asm.stash(access)
            return CONSUMED
        if reg == regmap.REG_VCC_MON + 1:
            msb = asm.take(access)
            return None if msb is None else self._voltage(msb, access)
        aux = self._aux_monitor(access, asm)
        if aux is not None:
            return aux

        # module control
        if reg == regmap.REG_MODULE_CONTROL:
            return Field('Module Control',
                         flag_names(access.value, regmap.CMIS_MODULE_CONTROL,
                                    empty='None'),
                         'control')

        # firmware revision, fault cause, media type
        if reg == regmap.REG_FW_ACTIVE_MAJOR:
            asm.stash(access)
            return CONSUMED
        if reg == regmap.REG_FW_ACTIVE_MINOR:
            msb = asm.take(access)
            return None if msb is None else self._fw_revision(msb, access)
        if reg == regmap.REG_MODULE_FAULT_CAUSE:
            return self._fault_cause(access)
        if reg == regmap.REG_MEDIA_TYPE:
            return self._media_type(access)

        # application descriptors - source of the host lane count
        descriptor = self._app_descriptor(access)
        if descriptor is not None:
            return descriptor

        return None

    def _app_descriptor(self, a):
        """Application descriptors, 00h:86-117 (Table 8-24).

        Only the host lane count is taken from them; it tells the page 11h
        decoders how many lanes the module actually has, so a 2-lane SFP-DD does
        not report phantom lanes 3-8. A descriptor slot whose lead byte is 0xFF
        is empty, and the first populated one is the primary application.
        """
        base = regmap.REG_APP_DESC_BASE
        span = regmap.APP_DESC_COUNT * regmap.APP_DESC_SIZE
        if not (base <= a.reg < base + span):
            return None

        within = (a.reg - base) % regmap.APP_DESC_SIZE
        if within == 0:
            self._descriptor_head = a.value
            return None
        if within != regmap.APP_DESC_LANE_COUNT_OFFSET:
            return None
        if self._descriptor_head == 0xFF:
            return None

        host_lanes = (a.value >> 4) & 0x0F
        if not host_lanes:
            return None
        if self.observed_lane_count is None:
            self.observed_lane_count = host_lanes
            logger.info("[CMIS] Host lane count %d from application descriptor",
                        host_lanes)
        return Field('Host Lane Count', '%d' % host_lanes, 'data')

    def _flag_byte(self, label, a, bit_names):
        return Field(label, flag_names(a.value, bit_names, empty='OK (Normal)'),
                     'control')

    def _aux_monitor(self, a, asm):
        """Aux / Custom monitors, 2 bytes each (Table 8-10).

        The unit follows the monitor function selected at 01h:145, so the value
        is rendered as the raw 1/256 reading with no unit suffix rather than
        asserting a unit that may be wrong.
        """
        for base, which, name in regmap.CMIS_AUX_MONITORS:
            if not (base <= a.reg <= base + 1):
                continue
            if a.reg == base:
                asm.stash(a)
                return CONSUMED
            msb = asm.take(a)
            if msb is None:
                return None
            return Field(name, self._aux_text(which, msb, a.value), 'data')
        return None

    def _fw_revision(self, major, a):
        if major == 0xFF and a.value == 0xFF:
            return Field('FW Active Revision', 'invalid (0xFF.0xFF)', 'data')
        return Field('FW Active Revision', '%d.%d' % (major, a.value), 'data')

    def _fault_cause(self, a):
        name = regmap.CMIS_FAULT_CAUSE.get(a.value)
        if name is None:
            name = 'Reserved(0x%02X)' % a.value
        return Field('Module Fault Cause', name, 'control')

    def _media_type(self, a):
        name = regmap.CMIS_MEDIA_TYPE.get(a.value)
        text = 'Reserved(0x%02X)' % a.value if name is None else '%s (0x%02X)' % (name, a.value)
        return Field('Media Type', text, 'data')

    def _revision(self, a):
        value = "CMIS %d.%d (0x%02X)" % ((a.value >> 4) & 0x0F, a.value & 0x0F, a.value)
        return Field('CMIS Revision', value, 'data')

    def _module_state(self, a):
        # Lower memory byte 3 bits[3:1]; bit 0 is the interrupt-deasserted flag.
        state = regmap.CMIS_MODULE_STATES.get((a.value >> 1) & 0x07,
                                              'Unknown (%d)' % ((a.value >> 1) & 0x07))
        if a.value & 0x01:
            state += ' [FAULT_FLAG]'
        return Field('Module State', state, 'control')

    def _flags_summary(self, a):
        # Bytes 4-7, one per bank: a bit per upper page with a pending flag.
        value = flag_names(a.value, regmap.CMIS_FLAGS_SUMMARY, empty='OK (Normal)')
        return Field('Flags Summary (bank %d)' % (a.reg - regmap.REG_FLAGS_SUMMARY),
                     value, 'control')

    def _temp_vcc_flags(self, a):
        value = flag_names(a.value, regmap.CMIS_TEMP_VCC_FLAGS, empty='OK (Normal)')
        return Field('Global Flags', value, 'control')

    def _temperature(self, msb, a):
        value = temperature_c(msb, a.value)
        return Field('Module Temperature', "%.2f °C" % value, 'data', raw=value)

    def _voltage(self, msb, a):
        value = voltage_v(msb, a.value)
        return Field('Supply Voltage Vcc', "%.3f V" % value, 'data', raw=value)

    # --- upper memory: paged -----------------------------------------------

    def _upper_memory(self, access, asm):
        handler = self._PAGES.get(access.page)
        if handler is None:
            return None
        return handler(self, access, asm)

    def _page00(self, a, asm):
        # Administrative information: identity fields, shown character by
        # character as they are read. The assembled value takes the place of the
        # final character, which it already contains.
        for first, last, label, kind in regmap.PAGE00_STRINGS:
            if not (first <= a.reg <= last):
                continue
            whole = self.strings.feed(a.reg, a.value, first, last)
            if whole is not None:
                return Field(label, _render_identity(kind, whole), 'data')
            return Field('%s[%d]' % (label, a.reg), char_field(a.value), 'data')
        return None

    def _page02(self, a, asm):
        # Module and lane supervision thresholds. Read-only, and every field is
        # a 2-byte MSB-first value (Tables 8-64 / 8-65).
        if not a.is_read:
            # A write here is a host bug; report it rather than decoding a
            # threshold out of it.
            return Field('Page 02h Write', 'Reg[0x%02X] = 0x%02X' % (a.reg, a.value),
                         'data')

        if a.reg in regmap.PAGE02_THRESHOLDS:
            asm.stash(a)
            return CONSUMED

        spec = regmap.PAGE02_THRESHOLDS.get(a.reg - 1)
        if spec is None:
            return None
        msb = asm.take(a)
        if msb is None:
            return None
        name, unit, aux = spec
        if unit == 'aux':
            # The scale follows 01h:145, so there may be no number to report.
            return Field(name, self._aux_text(aux, msb, a.value), 'data')
        if unit == 'mA':
            factor, _known = self._bias_state()
            return Field(name, self._bias_text(msb, a.value), 'data',
                         raw=bias_ma(msb, a.value, factor))
        return Field(name, threshold_str(msb, a.value, unit), 'data',
                     raw=threshold_value(msb, a.value, unit))

    def _page10(self, a, asm):
        # Staged Data Path control.
        base = regmap.PAGE10_DP_CONFIG_BASE
        if base <= a.reg <= base + 7:
            # Table 8-81: bits 7-4 AppSelCode, bits 3-1 DPIDX, bit 0
            # ExplicitControl.
            return Field(
                'Lane %d DataPath Ctrl' % (a.reg - base + 1),
                "AppSel=%d, DataPathID=%d, ExplicitControl=%d"
                % ((a.value >> 4) & 0x0F, (a.value >> 1) & 0x07, a.value & 0x01),
                'control')

        if a.reg == regmap.PAGE10_DP_DEINIT:
            # Table 8-78: DPDeinitLane1..8 bitmap, bit i-1 is lane i;
            # 0b = initialize, 1b = deinitialize.
            lanes = lane_bitmap(a.value)
            text = ("0x%02X (deinit lane %s)" % (a.value, lanes) if lanes
                    else "0x%02X (initialize all lanes)" % a.value)
            return Field('DP Deinit Lanes', text, 'control')

        if a.reg in (regmap.PAGE10_APPLY_DPINIT, regmap.PAGE10_APPLY_IMMEDIATE):
            # Tables 8-79/8-80: write-only triggers; the value is a lane bit mask.
            name = ('ApplyDPInit' if a.reg == regmap.PAGE10_APPLY_DPINIT
                    else 'ApplyImmediate')
            lanes = lane_bitmap(a.value)
            return Field(name, "lane %s" % lanes if lanes else 'no lanes selected',
                         'control')

        return None

    def _page11(self, a, asm):
        # Data Path status.
        base = regmap.PAGE11_DP_STATE_BASE
        if base <= a.reg <= base + 3:
            # Table 8-93: DPStateHostLane1..8, low nibble is the lower lane.
            first = (a.reg - base) * 2 + 1
            low = regmap.CMIS_DP_STATES.get(a.value & 0x0F,
                                            'Unknown(%d)' % (a.value & 0x0F))
            high = regmap.CMIS_DP_STATES.get((a.value >> 4) & 0x0F,
                                             'Unknown(%d)' % ((a.value >> 4) & 0x0F))
            return Field('Lane %d-%d DP State' % (first, first + 1),
                         "Lane %d: %s, Lane %d: %s" % (first, low, first + 1, high),
                         'control')

        count = self._lane_count()

        name = regmap.PAGE11_FLAG_FIELDS.get(a.reg)
        if name is not None:
            lanes = lane_bitmap(a.value, count)
            text = "0x%02X" % a.value + (" (%s)" % lanes if lanes else " (none)")
            return Field(name, text, 'control')

        if a.reg in regmap.PAGE11_OUTPUT_STATUS:
            # One bit per lane, 1 = the module declares that lane's output valid.
            lanes = lane_bitmap(a.value, count)
            text = "0x%02X" % a.value + (" (%s)" % lanes if lanes else " (none)")
            return Field(regmap.PAGE11_OUTPUT_STATUS[a.reg], text, 'control')

        monitor = self._lane_monitor(a, asm)
        if monitor is not None:
            return monitor

        return self._config_status(a)

    def _lane_monitor(self, a, asm):
        """Per-lane power and bias monitors, 2 bytes per lane (Table 8-99)."""
        for base, name_format, unit in regmap.PAGE11_LANE_MONITORS:
            if not (base <= a.reg < base + 2 * regmap.PAGE11_LANE_COUNT):
                continue
            offset = a.reg - base
            if offset % 2 == 0:
                asm.stash(a)
                return CONSUMED
            msb = asm.take(a)
            if msb is None:
                return None
            lane = offset // 2 + 1
            if lane > self._lane_count():
                # Past the end of this module's lanes - consume silently rather
                # than invent readings for lanes that do not exist.
                return CONSUMED
            if unit == 'mA':
                value = self._bias_text(msb, a.value)
            else:
                value = power_str(power_uw(msb, a.value))
            return Field(name_format % lane, value, 'data')
        return None

    def _config_status(self, a):
        """Configuration command result, 4 bits per lane (Tables 8-100/8-101)."""
        base = regmap.PAGE11_CONFIG_STATUS_BASE
        if not (base <= a.reg < base + 4):
            return None
        first = (a.reg - base) * 2 + 1
        states = []
        for slot, lane in ((a.value & 0x0F, first), ((a.value >> 4) & 0x0F, first + 1)):
            states.append("Lane %d: %s"
                          % (lane, regmap.CMIS_CONFIG_STATUS.get(slot,
                                                                 'Reserved(0x%X)' % slot)))
        return Field('ConfigStatus Lane %d-%d' % (first, first + 1),
                     ', '.join(states), 'control')

    def _page01(self, a, asm):
        # Page 01h is a large advertisement block. Only the fields the decoders
        # actually depend on are decoded: what the auxiliary monitors measure,
        # and the multiplier that scales the Tx bias monitor and thresholds.
        if a.reg == regmap.REG_AUX_MON_OBSERVABLE:
            return self._aux_observable(a)

        if a.reg == regmap.PAGE01_TX_BIAS_SCALING:
            factor = regmap.CMIS_BIAS_SCALING.get((a.value >> 3) & 0x03)
            if factor is None:
                return Field('TxBiasCurrentScalingFactor',
                             'reserved (0x%02X)' % a.value, 'data')
            self.observed_bias_scaling = factor
            return Field('TxBiasCurrentScalingFactor', 'x%g' % factor, 'data')

        return None

    def _aux_observable(self, a):
        """01h:145 bits 2/1/0 - what each auxiliary monitor actually measures."""
        measured = []
        for which in ('aux1', 'aux2', 'aux3'):
            bit = (a.value >> regmap.AUX_MON_OBSERVABLE_BITS[which]) & 1
            function = regmap.AUX_MON_OBSERVABLE.get((which, bit), 'unknown')
            self.observed_aux_functions[which] = function
            measured.append('%s=%s' % (which.upper(), function))
        return Field('Aux Monitor Function', ', '.join(measured), 'data')

    def _page9f(self, a, asm):
        # The CDB message block lives in its own module - it carries the command
        # table and the check-code arithmetic, and belongs to neither this file
        # nor any other page.
        return self.cdb.decode(a, asm)

    _PAGES = {
        0x00: _page00,
        0x01: _page01,
        0x02: _page02,
        0x10: _page10,
        0x11: _page11,
        0x9F: _page9f,
    }
