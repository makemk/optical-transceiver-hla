# Renders a completed I2C transaction as a single summary line.
#
# This is a separate OUTPUT MODE rather than an extra frame emitted alongside the
# per-byte output, and that is not a style choice - it is forced by Logic 2.
# Measured on the real capture, with a throwaway probe extension since removed:
#
#   per-byte frames + aggregate spanning the transaction   1679 rows, 1 aggregate
#   per-byte frames + zero-width aggregate                 2664 rows, 90 aggregates
#   aggregate spanning the transaction, alone                90 rows, 90 aggregates
#
# A frame that spans other frames from the same analyzer does not merely get
# dropped: it wrecks the data table for everything around it and the analysis
# stops partway through the capture. Emitting the spanning aggregate on its own
# is fine. So the two modes must be mutually exclusive - there is no "both".

# Longest summary rendered. The full content is still available in the data
# table; this only bounds the timeline bubble, which stops being readable well
# before this.
MAX_LENGTH = 220


def render(transaction, entries):
    """One line describing a transaction.

    `entries` are (text, category) pairs. Control and state entries are ordered
    ahead of bulk readings, so when a summary is truncated for length it drops
    monitor readings rather than the state someone is usually scanning for.
    """
    head = '%s 0x%02X pg%02X %dB' % (
        'RD' if transaction.is_read else 'WR',
        transaction.addr, transaction.page, transaction.byte_count)

    ordered = ([e for e in entries if e[1] == 'control'] +
               [e for e in entries if e[1] != 'control'])

    shown = []
    for index, (text, _category) in enumerate(ordered):
        if len(' | '.join([head] + shown + [text])) > MAX_LENGTH:
            remaining = len(ordered) - index
            if remaining > 0:
                shown.append('+%d more' % remaining)
            break
        shown.append(text)

    return ' | '.join([head] + shown)
