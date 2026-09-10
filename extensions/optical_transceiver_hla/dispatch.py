# The protocol layer's entry point: picks a decoder for each register access.
#
# Decoder instances are owned by the Dispatcher, and one Dispatcher is created
# per HLA instance - deliberately NOT shared at module level. A decoder may hold
# state that belongs to the module being decoded (the Tx bias scaling factor,
# the lane count from the application descriptors). The dual-track trick mounts
# two HLA instances on the same I2C analyzer, and shared decoders would let them
# corrupt each other's view of the module.

from cmis import CmisDecoder
from sff8472 import Sff8472Decoder

ADDR_A0H = 0x50
ADDR_A2H = 0x51

CMIS = 'CMIS'
SFF_8472 = 'SFF-8472'


class Dispatcher:
    def __init__(self):
        self._decoders = {
            CMIS: CmisDecoder(),
            SFF_8472: Sff8472Decoder(),
        }

    def select(self, session):
        """The decoder responsible for the session's current access, or None.

        A2h is always the SFF-8472 diagnostics slave, whatever the module was
        classified as from the identifier byte. On A0h the classification
        decides, and an unrecognised standard gets no decoder at all - the
        caller falls back to the generic register display.
        """
        if session.addr == ADDR_A2H:
            return self._decoders[SFF_8472]
        if session.addr != ADDR_A0H:
            return None
        if session.is_cmis():
            return self._decoders[CMIS]
        if session.effective_protocol() == SFF_8472:
            return self._decoders[SFF_8472]
        return None

    def decode(self, session, access):
        """Decode one access, or return None when no decoder claims it."""
        decoder = self.select(session)
        if decoder is None:
            return None
        return decoder.decode(access, session.assembler)
