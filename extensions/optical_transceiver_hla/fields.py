# The vocabulary the layers share.
#
# Keeping these three types in one small module is what keeps the layers
# decoupled: the I2C session produces Access values, protocol decoders consume
# them and produce Field values, and neither layer has to know how the other is
# implemented or even that the other exists.

from typing import NamedTuple, Optional


class Access(NamedTuple):
    """One register byte, with the addressing context it was read under.

    `page` and `bank` are the values in force for the access, not whatever the
    session holds by the time the byte is decoded - that distinction is the
    whole reason a half-read register can no longer pair with an unrelated byte.
    """

    addr: int
    page: int
    bank: int
    reg: int
    value: int
    is_read: bool
    start_time: object
    end_time: object

    @property
    def context(self):
        """Identity of the addressing context, for validating byte pairing."""
        return (self.addr, self.page, self.bank)


class Finding(NamedTuple):
    """A consistency observation about the decoded data.

    Lives here rather than in compliance.py so a decoder can raise one without
    importing the checking layer: both sides depend on this contract, neither on
    the other.
    """

    rule: str
    severity: str
    message: str

    def __str__(self):
        return '[%s] %s' % (self.rule, self.message)


class Field(NamedTuple):
    """One decoded field, ready to render.

    `category` drives the display filter: 'control' for state and configuration,
    'data' for register contents and monitor readings.

    `raw` is the numeric value behind `value`, in the field's own unit, set only
    where a number exists. Rendering never touches it - it exists so consistency
    checks can compare readings against thresholds without parsing the formatted
    string back into a number.

    `raw_encoded` is the unscaled register value when that representation matters
    to validation. CMIS supervision thresholds use it to distinguish sentinel
    encodings such as 0x0000/0xFFFF from their converted engineering-unit value.
    """

    name: str
    value: str
    category: str = 'data'
    raw: float = None

    # Contradictions only the decoder could have noticed - a CDB check code that
    # does not match the message it protects, say. Attached to the field they
    # concern; the compliance layer raises them like any other rule.
    findings: tuple = ()
    raw_encoded: int = None


class ControlEvent(NamedTuple):
    """A protocol-independent addressing event worth showing on the timeline.

    Register pointer moves and page/bank selects are I2C-level, not
    protocol-level, so they are produced by the session rather than a decoder.
    """

    summary: str
    category: str = 'control'

    # A pointer move is already implied by the address/page header of a
    # transaction summary and is emitted on every write, so it is noise there.
    # A page or bank select changes what the following registers MEAN and is
    # kept. `significant` lets a summary tell the two apart without matching on
    # the summary text.
    significant: bool = True


class _Consumed:
    """Marker for "this decoder owns the byte but has nothing to show for it".

    A decoder returns CONSUMED when it has taken the byte but the field it
    belongs to is not complete yet - typically the MSB half of a 2-byte value,
    which is stashed for the following byte. This is deliberately distinct from
    returning None: None means "not my register", and the caller should fall
    back to the generic register display. Without the distinction a stashed byte
    would be printed raw and then decoded again when its second half arrived.
    """

    __slots__ = ()

    def __repr__(self):
        return 'CONSUMED'


CONSUMED = _Consumed()


class SessionOutput(NamedTuple):
    """What one input frame produced.

    `emission` (a ControlEvent or a Field) is rendered as-is. `access`, when
    present, is handed to the protocol decoder - the session deliberately does
    not know what the byte means.

    At most one of the two is ever set: an input frame either resolves to
    something the session can render itself (a pointer move, a page select, an
    identifier) or to a register byte a decoder has to interpret.
    """

    emission: Optional[object] = None
    access: Optional[Access] = None


class AccessAssembler:
    """Pairs the two halves of a 16-bit register.

    A decoder expecting a 2-byte field calls `stash()` on the MSB access and
    `take()` on the following one. The pairing is accepted only when the bytes
    genuinely belong together: the second must be the register immediately after
    the first, at the same slave address, page and bank.

    Validating at consumption time rather than by invalidation timing is what
    makes this safe. A stash is never carried into a different page or bank, so
    a half-read register cannot pair with an unrelated byte later on and emit a
    plausible-looking but completely wrong value.
    """

    def __init__(self):
        self._pending = None

    def stash(self, access):
        """Record `access` as the pending MSB half."""
        self._pending = (access.reg, access.value, access.context)

    def take(self, access):
        """Return the pending MSB value if `access` is genuinely its LSB half."""
        pending = self._pending
        self._pending = None
        if pending is None:
            return None
        src_reg, src_value, src_context = pending
        if src_reg + 1 != access.reg or src_context != access.context:
            return None
        return src_value

    def clear(self):
        self._pending = None


class StringAssembler:
    """Collects the bytes of an ASCII field so it can be shown as one string.

    A decoder calls `feed()` for every byte of the range. The bytes arrive one
    I2C frame at a time, and decode() can only return one frame per call, so the
    per-character output stays as it was and the assembled string is reported in
    place of the FINAL character - which the assembled string already contains,
    so nothing is lost.

    A field is only assembled when the run was contiguous from its first
    register. A partial read (the host stops halfway, or jumps into the middle
    of the field) would otherwise produce a string that silently looks complete.
    """

    def __init__(self):
        self._reg = None
        self._raw = []
        self._whole = False

    def feed(self, reg, value, first, last):
        """Accumulate one byte; returns the raw bytes once the field is complete.

        Returns None while the field is incomplete, and also when it completes
        but the run did not start at `first` - the caller should then show
        nothing rather than risk presenting a truncated field as a whole one.

        The bytes come back raw rather than pre-rendered: not every field in
        these ranges is ASCII (a vendor OUI is a 24-bit number), so formatting
        belongs to the decoder that knows which is which.
        """
        if reg == first:
            self._raw = [value]
            self._whole = True
        elif self._reg is not None and reg == self._reg + 1:
            self._raw.append(value)
        else:
            self._raw = [value]
            self._whole = False
        self._reg = reg

        if reg != last:
            return None

        raw = list(self._raw) if self._whole else None
        self.clear()
        return raw

    def clear(self):
        self._reg = None
        self._raw = []
        self._whole = False
