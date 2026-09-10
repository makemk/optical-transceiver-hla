# SFF-8472 decoder (SFP / SFP+ / SFP28).
#
# Two distinct address spaces, which is why decode() branches on the slave
# address first:
#
#   A2h (0x51) - real-time diagnostics (DDM/DOM): temperature, supply voltage,
#                TX bias, TX/RX optical power and the status/control byte.
#                This is the address the values live at regardless of what the
#                identifier byte on A0h claimed.
#   A0h (0x50) - the base page. Only the vendor name is decoded here; the rest
#                is left to the generic register display.
#
# The A0h branch is reached only when the session classified the module as
# SFF-8472 - see select_decoder() in optical_hla.py.

import logging

from decode_utils import (temperature_c, voltage_v, power_str, power_uw, bias_ma,
                          char_field, ascii_string)
from fields import CONSUMED, Field, StringAssembler
import regmap

logger = logging.getLogger("OpticalTransceiverHLA")

ADDR_A0H = 0x50
ADDR_A2H = 0x51

# A2h register map (SFF-8472 Table 9-11). Every monitor is a 2-byte MSB-first
# value, so they all go through the assembler.
REG_TEMPERATURE = 96
REG_VOLTAGE = 98
REG_TX_BIAS = 100
REG_TX_POWER = 102
REG_RX_POWER = 104
REG_STATUS = 110

_VENDOR_NAME = (20, 35)


class Sff8472Decoder:
    NAME = 'SFF-8472'

    def __init__(self):
        self.strings = StringAssembler()

    def decode(self, access, asm):
        if access.addr == ADDR_A2H:
            return self._diagnostics(access, asm)
        if access.addr == ADDR_A0H:
            return self._base_page(access, asm)
        return None

    # --- A2h: real-time diagnostics ----------------------------------------

    def _diagnostics(self, access, asm):
        reg = access.reg

        if reg in (REG_TEMPERATURE, REG_VOLTAGE, REG_TX_BIAS,
                   REG_TX_POWER, REG_RX_POWER):
            asm.stash(access)
            return CONSUMED

        if reg == REG_STATUS:
            return self._status(access)

        # The LSB half is always MSB register + 1.
        source = reg - 1
        if source not in (REG_TEMPERATURE, REG_VOLTAGE, REG_TX_BIAS,
                          REG_TX_POWER, REG_RX_POWER):
            return None
        msb = asm.take(access)
        if msb is None:
            return None
        return self._monitor(source, msb, access)

    def _monitor(self, source, msb, a):
        if source == REG_TEMPERATURE:
            return Field('Module Temperature', "%.2f °C" % temperature_c(msb, a.value),
                         'data')
        if source == REG_VOLTAGE:
            return Field('Supply Voltage Vcc', "%.3f V" % voltage_v(msb, a.value),
                         'data')
        if source == REG_TX_BIAS:
            return Field('TX Bias Current', "%.2f mA" % bias_ma(msb, a.value), 'data')
        if source == REG_TX_POWER:
            return Field('TX Optical Power', power_str(power_uw(msb, a.value)), 'data')
        return Field('RX Optical Power', power_str(power_uw(msb, a.value)), 'data')

    def _status(self, a):
        return Field('Status/Control',
                     "TxDisable=%s, TxFault=%s, RxLOS=%s"
                     % (bool(a.value & (1 << 7)), bool(a.value & (1 << 2)),
                        bool(a.value & (1 << 1))),
                     'control')

    # --- A0h: base page -----------------------------------------------------

    def _base_page(self, access, asm):
        first, last = _VENDOR_NAME
        if not (first <= access.reg <= last):
            return None
        whole = self.strings.feed(access.reg, access.value, first, last)
        if whole is not None:
            return Field('Vendor Name', "'%s'" % ascii_string(whole), 'data')
        return Field('Vendor Name[%d]' % access.reg, char_field(access.value), 'data')
