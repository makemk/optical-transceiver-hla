# CDB (Command Data Block) decoding for page 9Fh.
#
# A page decoder like the _pageXX handlers in cmis.py, but large enough to live
# on its own: it never sees an I2C frame, never builds an AnalyzerFrame, and
# knows nothing about the rest of the analyzer. cmis.py routes page 0x9F here.
#
# The shape of a CDB exchange is what makes this more than a register dump:
#
#   The host writes the lengths, the check code and the payload, and writes the
#   CMDID LAST. It is the CMDID write that "sends" the command (spec p.320).
#
# So the header bytes cannot be reported as they arrive - by the time the CMDID
# goes past, the bytes that describe it are already behind us. They are
# accumulated here and the command is reported at the moment it is sent.
#
# Verified against OIF-CMIS-05.4 Tables 8-197..8-200 (spec pp.320-321). Nothing
# in this file has been checked against a real module: the capture available
# during development never selects page 9Fh.

from decode_utils import u16
from fields import Field, Finding
import regmap


class CdbDecoder:
    NAME = 'CDB'

    def __init__(self):
        # The message block as the host has written it so far, keyed by register.
        self._bytes = {}
        self.commands_seen = 0

    # --- entry point -------------------------------------------------------

    def decode(self, access, asm):
        reg = access.reg

        if reg == regmap.PAGE9F_CMDID:
            self._bytes[reg] = access.value
            return Field('CMDID High', '0x%02X' % access.value, 'control')

        if reg == regmap.PAGE9F_CMDID_LSB:
            self._bytes[reg] = access.value
            if access.is_read:
                return Field('CMDID Low', '0x%02X' % access.value, 'control')
            return self._command_sent()

        if reg == regmap.PAGE9F_EPL_LENGTH:
            self._bytes[reg] = access.value
            return Field('EPL Length High', '0x%02X' % access.value, 'control')
        if reg == regmap.PAGE9F_EPL_LENGTH + 1:
            self._bytes[reg] = access.value
            combined = u16(self._bytes.get(reg - 1, 0), access.value)
            return Field('EPL Length', '%d bytes' % combined, 'control')

        if reg == regmap.PAGE9F_LPL_LENGTH:
            self._bytes[reg] = access.value
            return Field('LPL Length', '%d bytes' % access.value, 'control')

        if reg == regmap.PAGE9F_CHECK_CODE:
            self._bytes[reg] = access.value
            return Field('CdbChkCode', '0x%02X' % access.value, 'control')

        if reg == regmap.PAGE9F_RPL_LENGTH:
            return Field('RPL Length', '%d bytes' % access.value, 'control')

        if reg == regmap.PAGE9F_RPL_CHECK_CODE:
            return Field('RPL Check Code', '0x%02X' % access.value, 'control')

        if reg >= regmap.PAGE9F_LPL_BASE:
            # Payload bytes are remembered so the check code can be verified,
            # but reported one by one like any other register - summarising is
            # the transaction-summary output mode's job, not this module's.
            self._bytes[reg] = access.value

        return None

    # --- the command, at the moment it is sent -----------------------------

    def _command_sent(self):
        cmdid = u16(self._bytes.get(regmap.PAGE9F_CMDID, 0),
                    self._bytes.get(regmap.PAGE9F_CMDID_LSB, 0))
        name = regmap.CDB_COMMANDS.get(cmdid)
        label = '%04Xh (%s)' % (cmdid, name) if name else '%04Xh (unknown command)' % cmdid

        lpl_length = self._bytes.get(regmap.PAGE9F_LPL_LENGTH, 0)
        epl_length = u16(self._bytes.get(regmap.PAGE9F_EPL_LENGTH, 0),
                         self._bytes.get(regmap.PAGE9F_EPL_LENGTH + 1, 0))
        check = self._check_verdict(lpl_length)

        self.commands_seen += 1
        text = 'CMD %s | LPL=%d EPL=%d%s' % (label, lpl_length, epl_length, check[0])

        # The block is consumed; a later command composes a fresh one.
        self._bytes = {}
        return Field('CDB Command', text, 'control', findings=check[1])

    def _check_verdict(self, lpl_length):
        """(text, findings) for the CdbChkCode.

        Formula (spec p.320): the one's complement of the arithmetic sum of
        9Fh:128 through 9Fh:(136 + LPLLength - 1), excluding 9Fh:133-135. The
        spec is explicit that EPLLength and LPLLength are always inside the sum
        and that the reply header never is.

        Bytes the host never wrote count as zero. A host that rewrites only part
        of the block therefore produces a mismatch here that its own check code
        agrees with - so the verdict is only as good as what the analyzer
        captured, which is a limit of observing the bus, not of the formula.
        """
        received = self._bytes.get(regmap.PAGE9F_CHECK_CODE)
        if received is None:
            return '', ()

        total = 0
        for reg in range(regmap.PAGE9F_CMDID, regmap.PAGE9F_LPL_BASE + lpl_length):
            if reg in regmap.PAGE9F_CHECK_EXCLUDED:
                continue
            total += self._bytes.get(reg, 0)
        expected = (~total) & 0xFF

        if expected == received:
            return ', check code OK', ()

        message = ('CDB command %04Xh: check code 0x%02X does not match the message '
                   'block (recomputed 0x%02X)'
                   % (u16(self._bytes.get(regmap.PAGE9F_CMDID, 0),
                          self._bytes.get(regmap.PAGE9F_CMDID_LSB, 0)),
                      received, expected))
        return ', CHECK CODE MISMATCH', (Finding('CDB_CHECK_CODE', 'error', message),)
