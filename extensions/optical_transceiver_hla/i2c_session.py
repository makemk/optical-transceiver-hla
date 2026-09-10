# The I2C layer: turns the raw Logic 2 frame stream into register accesses.
#
# This layer owns I2C addressing, the register pointer, page/bank selection and
# module identification. It knows NOTHING about what any register means - it
# hands an Access to a protocol decoder and lets that decide. Adding a new page
# or protocol never requires touching this file.

import logging
from typing import NamedTuple

from fields import Access, AccessAssembler, ControlEvent, Field, SessionOutput
import regmap

logger = logging.getLogger("OpticalTransceiverHLA")


class Transaction(NamedTuple):
    """A completed I2C transaction, snapshotted for the summary output mode.

    Captured at STOP because the session resets its addressing state there -
    by the time a caller wants to render the transaction, `addr` and the rest
    are already gone.
    """

    index: int
    addr: int
    page: int
    bank: int
    is_read: bool
    start_time: object
    end_time: object
    byte_count: int
    touched_upper: bool = False

# Register pointer helpers: the first write byte of a transaction is the address
# the following bytes refer to. 0x7E selects the bank and 0x7F the page in CMIS
# (and SFF-8636 uses 0x7F for pages too), so both are consumed as control rather
# than decoded as data.
REG_POINTER_PAGE = 0x7F
REG_POINTER_BANK = 0x7E

# Slave addresses. A0h is the base page, A2h the SFF-8472 diagnostics page.
ADDR_A0H = 0x50
ADDR_A2H = 0x51

DEFAULT_STANDARD = 'SFF-8472'


class I2cSession:
    """Stateful decoder for the I2C frame stream.

    Feed it frames; it returns SessionOutput. Feed order matters and is exactly
    the order the I2C analyzer produces: start, address, data..., stop, with
    repeated starts opening a new phase of the same transaction.
    """

    def __init__(self, forced_standard=None):
        """`forced_standard` is the short protocol name when the user picked a
        standard explicitly, or None to auto-detect from the identifier byte."""
        self._forced_standard = forced_standard

        self.addr = None
        self.is_read = False
        self.reg_ptr = 0
        self.page = 0
        self.bank = 0
        self.standard = DEFAULT_STANDARD

        # Bytes seen in the current phase. Only the length and the first value
        # are ever used, but keeping the count is what distinguishes the pointer
        # byte from a payload byte.
        self._data_count = 0
        self.assembler = AccessAssembler()
        self.frame_count = 0

        # Transaction bookkeeping for the summary output mode. The transaction
        # is snapshotted at STOP, because that is where the addressing state
        # below gets reset.
        self.txn_index = 0
        self.last_transaction = None
        self._txn_start = None
        self._txn_bytes = 0
        self._txn_addr = None
        self._txn_is_read = False
        self._txn_upper = False

        # Page selection persists across transactions, so a host that reads
        # upper memory without ever selecting a page is relying on the reset
        # default. Compliance flags that, which needs to know whether any page
        # select has been seen at all - not just in this transaction.
        self.page_ever_selected = False

    # --- classification ----------------------------------------------------

    def effective_protocol(self):
        """The protocol label shown to the user and used to pick a decoder."""
        if self._forced_standard is not None:
            return self._forced_standard
        if self.addr == ADDR_A2H:
            # A2h is the SFF-8472 diagnostics slave regardless of what the
            # identifier byte on A0h said.
            return 'SFF-8472'
        return self.standard

    def is_cmis(self):
        return self.effective_protocol() == 'CMIS' or self.standard == 'CMIS'

    def _classify(self, value):
        """Update the detected standard from an identifier byte, if known."""
        entry = regmap.IDENTIFIERS.get(value)
        if entry is None:
            return None
        standard, name = entry
        if self._forced_standard is None:
            if self.standard != standard:
                logger.info("[Frame #%d] Auto-Detect: standard -> %s",
                            self.frame_count, standard)
            self.standard = standard
        return name

    # --- frame intake ------------------------------------------------------

    def feed(self, frame):
        frame_type = frame.type
        self.frame_count += 1

        if frame_type == 'start':
            self._data_count = 0
            # A repeated start opens a new phase of the SAME transaction, so the
            # transaction start is only taken when one is not already open.
            if self._txn_start is None:
                self._txn_start = frame.start_time
            logger.debug("[Frame #%d] I2C START", self.frame_count)
            return SessionOutput()

        if frame_type == 'address':
            raw = frame.data.get('address', [0])
            addr = raw[0] if raw else 0
            self.addr = addr
            self.is_read = frame.data.get('read', False)
            self._data_count = 0
            self._txn_addr = addr
            self._txn_is_read = self.is_read
            logger.info("[Frame #%d] I2C ADDR: 0x%02X (%s)", self.frame_count, addr,
                        "READ" if self.is_read else "WRITE")
            return SessionOutput()

        if frame_type == 'data':
            self._txn_bytes += 1
            return self._on_data(frame)

        if frame_type == 'stop':
            addr_str = "0x%02X" % self.addr if self.addr is not None else "None"
            logger.debug("[Frame #%d] I2C STOP (Addr: %s, Bytes: %d)",
                         self.frame_count, addr_str, self._data_count)
            if self._txn_start is not None or self._txn_bytes:
                self.txn_index += 1
                self.last_transaction = Transaction(
                    index=self.txn_index,
                    addr=self._txn_addr if self._txn_addr is not None else 0,
                    page=self.page,
                    bank=self.bank,
                    is_read=self._txn_is_read,
                    start_time=self._txn_start if self._txn_start is not None
                    else frame.start_time,
                    end_time=frame.end_time,
                    byte_count=self._txn_bytes,
                    touched_upper=self._txn_upper,
                )
            else:
                self.last_transaction = None
            self.addr = None
            self._txn_start = None
            self._txn_bytes = 0
            self._txn_addr = None
            self._txn_upper = False
            return SessionOutput()

        return SessionOutput()

    def _on_data(self, frame):
        raw = frame.data.get('data', [0])
        value = raw[0] if raw else 0
        self._data_count += 1

        # Writes only: the first byte is the register pointer, and the byte after
        # it may be a page or bank selector.
        if not self.is_read:
            if self._data_count == 1:
                return self._on_register_pointer(value)

            if self._data_count == 2:
                if self.reg_ptr == REG_POINTER_PAGE:
                    return self._on_page_select(value)
                if self.reg_ptr == REG_POINTER_BANK:
                    return self._on_bank_select(value)

        # An access to the identifier byte both classifies the module and is
        # worth showing. It is reported here rather than by a decoder because
        # module identification is a session concern - it decides which decoder
        # runs. (Like the original implementation this fires on a write too,
        # since the register pointer is all that is checked.)
        identifier = None
        if self.addr == ADDR_A0H and self.reg_ptr == regmap.REG_IDENTIFIER:
            name = self._classify(value)
            if name is not None:
                logger.info("[Frame #%d] [%s] Module Identifier: %s (0x%02X)",
                            self.frame_count, self.standard, name, value)
                identifier = Field('Module Identifier', "%s (0x%02X)" % (name, value))

        access = Access(
            addr=self.addr,
            page=self.page,
            bank=self.bank,
            reg=self.reg_ptr,
            value=value,
            is_read=self.is_read,
            start_time=frame.start_time,
            end_time=frame.end_time,
        )
        # The pointer advances for every data byte, including the identifier
        # byte - the byte is still consumed from the module's address space even
        # though it is rendered as an identifier rather than passed to a decoder.
        if access.reg >= 0x80:
            self._txn_upper = True
        self.reg_ptr = (self.reg_ptr + 1) & 0xFF

        if identifier is not None:
            return SessionOutput(emission=identifier)
        return SessionOutput(access=access)

    # --- control events ----------------------------------------------------

    def _on_register_pointer(self, value):
        self.reg_ptr = value
        logger.info("[Frame #%d] [%s] Reg Pointer -> 0x%02X (%d)",
                    self.frame_count, self.effective_protocol(), value, value)
        return SessionOutput(emission=ControlEvent(
            "Set Reg Address -> 0x%02X (%d)" % (value, value), significant=False))

    def _on_page_select(self, value):
        self.page = value
        self.page_ever_selected = True
        self.assembler.clear()
        logger.info("[Frame #%d] [%s] Page Select -> Page 0x%02X",
                    self.frame_count, self.effective_protocol(), value)
        return SessionOutput(
            emission=ControlEvent("Page Select -> Page 0x%02X" % value))

    def _on_bank_select(self, value):
        self.bank = value
        self.assembler.clear()
        logger.info("[Frame #%d] [%s] Bank Select -> Bank %d",
                    self.frame_count, self.effective_protocol(), value)
        return SessionOutput(
            emission=ControlEvent("Bank Select -> Bank %d" % value))
