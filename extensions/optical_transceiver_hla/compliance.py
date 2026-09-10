# Consistency checks: the layer that turns the decoder from a translator into a
# checker.
#
# A decoder can only say what a register contains. It cannot say that the
# contents contradict each other or the spec, which is usually what actually
# matters when a module misbehaves. That is this module's job.
#
# Rules are pure functions over the fields a transaction decoded plus a small
# context object. They never touch I2C frames, never render anything, and never
# import a decoder - so a rule can be read, written and tested on its own.
#
# Findings are reported, never enforced. Nothing here alters or suppresses a
# decoded field.

import logging
from typing import NamedTuple

from fields import Finding

logger = logging.getLogger("OpticalTransceiverHLA")

ERROR = 'error'
WARNING = 'warning'
INFO = 'info'

SEVERITIES = (ERROR, WARNING, INFO)


class Context(NamedTuple):
    """What a rule may know beyond the fields of the current transaction.

    `state` is every field decoded so far in the capture, keyed by field name.
    Rules need it because the values they compare are rarely read together: the
    supervision thresholds arrive in one page-02h sweep and the monitors they
    apply to arrive in other transactions entirely.

    The firing convention is the other half of that: a rule fires on the fields
    of the CURRENT transaction and uses `state` only for lookup - otherwise a
    contradiction found once would be re-reported on every later transaction.
    """

    page: int
    bank: int
    is_read: bool
    touched_upper: bool
    page_ever_selected: bool
    state: dict = None


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

_RULES = []


def rule(func):
    """Register a check. Each takes (fields, context) and returns Findings."""
    _RULES.append(func)
    return func


def check(fields, context, mode):
    """Run every enabled rule over one transaction's decoded fields.

    `mode` is the compliance_mode setting: 'Warnings + Errors', 'Errors Only'
    or 'Off'. Rules are skipped by severity, so a rule author never has to
    think about the switch.
    """
    if mode == 'Off':
        return []

    allow = {ERROR} if mode == 'Errors Only' else {ERROR, WARNING}
    findings = []
    for func in _RULES:
        try:
            for finding in func(fields, context):
                if finding.severity in allow:
                    findings.append(finding)
        except Exception as err:
            # A broken rule must not cost the user their decode.
            logger.error("[compliance] rule %s raised %s: %s",
                         getattr(func, '__name__', func), type(err).__name__, err)
    return findings


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

# Pages 02h and 11h are read-only in their entirety:
#   "All fields on Page 02h are read-only." (spec p.211)
#   "All fields on Page 11h are read-only." (spec p.233)
READ_ONLY_PAGES = {0x02: 'Page 02h', 0x11: 'Page 11h'}


@rule
def decoder_findings(fields, context):
    """Spread anything a decoder raised about a field it decoded.

    Some contradictions only the decoder can see: a CDB check code that does
    not match the message block it protects cannot be spotted from the rendered
    fields alone. The decoder attaches those to the field they concern, so this
    module stays ignorant of every decoder - the dependency is one-way.
    """
    return [finding for field in fields for finding in field.findings]


@rule
def write_to_read_only(fields, context):
    """A write to a page the spec defines as entirely read-only.

    `touched_upper` is part of the test, not a detail. Selecting page 02h is a
    write to register 0x7F while the page is 02h, so a rule that only looked at
    the direction and the page would flag every page select in the capture. A
    real write to the page has to land on an upper-memory register.
    """
    if context.is_read or not context.touched_upper:
        return []
    label = READ_ONLY_PAGES.get(context.page)
    if label is None:
        return []
    return [Finding('WRITE_TO_READ_ONLY', WARNING,
                    'host wrote to %s, which is entirely read-only' % label)]


@rule
def page_stale(fields, context):
    """Upper-memory access with no page ever selected.

    Page selection persists across transactions, so an upper-memory access
    before any page select is being interpreted as page 00h by default -
    probably not what the host intended.
    """
    if context.page_ever_selected or not context.touched_upper:
        return []
    return [Finding('PAGE_STALE', INFO,
                    'upper-memory access before any page select; '
                    'reading page 0x%02X by default' % context.page)]


@rule
def threshold_uninitialized(fields, context):
    """A supervision threshold that has not been programmed.

    All-zero and all-ones are the two values an unprogrammed threshold takes,
    and either one makes every comparison against it meaningless.
    """
    findings = []
    for field in fields:
        if 'Threshold' not in field.name or field.raw is None:
            continue
        if field.raw == 0.0:
            findings.append(Finding('THRESHOLD_UNINITIALIZED', WARNING,
                                    '%s is 0 - threshold not programmed' % field.name))
        elif field.raw == 0xFFFF or field.raw == 0xFFFFFFFF:
            findings.append(Finding('THRESHOLD_UNINITIALIZED', WARNING,
                                    '%s is all ones - threshold not programmed'
                                    % field.name))
    return findings


THRESHOLD_KINDS = ('HighAlarm', 'LowAlarm', 'HighWarning', 'LowWarning')


@rule
def threshold_order(fields, context):
    """Alarm and warning thresholds that are the wrong way round.

    A high warning must sit below the high alarm, and a low warning above the
    low alarm; inverted pairs mean the module warns only after it has already
    alarmed, or never warns at all.

    Fires on any transaction that read into a group, comparing against the whole
    accumulated set, because a host is free to read the four thresholds of a
    group in separate transactions.
    """
    groups = _threshold_groups(context)

    touched = set()
    for field in fields:
        parts = _split_threshold(field.name)
        if parts is not None:
            touched.add(parts[0])

    findings = []
    for label in sorted(touched):
        kinds = groups.get(label) or {}
        if 'HighAlarm' in kinds and 'HighWarning' in kinds:
            if kinds['HighWarning'] > kinds['HighAlarm']:
                findings.append(Finding(
                    'THRESHOLD_ORDER', WARNING,
                    '%sHighWarning (%g) is above HighAlarm (%g)'
                    % (label, kinds['HighWarning'], kinds['HighAlarm'])))
        if 'LowAlarm' in kinds and 'LowWarning' in kinds:
            if kinds['LowWarning'] < kinds['LowAlarm']:
                findings.append(Finding(
                    'THRESHOLD_ORDER', WARNING,
                    '%sLowWarning (%g) is below LowAlarm (%g)'
                    % (label, kinds['LowWarning'], kinds['LowAlarm'])))
    return findings


# Which threshold group and flag names a monitor belongs to. The spec names the
# monitor registers and the threshold groups separately, so the mapping is
# spelled out rather than derived.
MONITOR_GROUPS = {
    'Module Temperature': ('TempMon', 'Temp'),
    'Supply Voltage Vcc': ('VccMon', 'Vcc'),
}


@rule
def monitor_flag_mismatch(fields, context):
    """A monitor outside its alarm band with no matching flag bit set.

    If the module reports a temperature past its own high alarm threshold and
    the corresponding flag reads clear, one of the two is wrong - which is how a
    mis-mapped or inverted flag register shows up. Thresholds and flags come
    from `state` because they are read in other transactions than the monitor.
    """
    groups = _threshold_groups(context)
    flags = _flag_bits(context)
    if not groups or not flags:
        return []

    findings = []
    for field in fields:
        if field.raw is None or field.name not in MONITOR_GROUPS:
            continue
        group, prefix = MONITOR_GROUPS[field.name]
        band = groups.get(group)
        if not band:
            continue
        for kind, word, direction in (('HighAlarm', 'High', 'above'),
                                      ('LowAlarm', 'Low', 'below')):
            limit = band.get(kind)
            if limit is None:
                continue
            outside = field.raw > limit if kind == 'HighAlarm' else field.raw < limit
            if not outside:
                continue
            alarm = flags.get('%s%sAlarm' % (prefix, word))
            warn = flags.get('%s%sWarn' % (prefix, word))
            if alarm is False and warn is False:
                findings.append(Finding(
                    'MONITOR_FLAG_MISMATCH', WARNING,
                    '%s is %g, %s the %s %s threshold %g, but no %s%s flag is set'
                    % (field.name, field.raw, direction, word.lower(), kind,
                       limit, prefix, word)))
    return findings


_FLAG_BITS = ('TempHighAlarm', 'TempLowAlarm', 'TempHighWarn', 'TempLowWarn',
              'VccHighAlarm', 'VccLowAlarm', 'VccHighWarn', 'VccLowWarn')


def _flag_bits(context):
    """Flag names from the 'Global Flags' byte -> True/False.

    The rendered value is the only record of which bits were set, and a clear
    byte renders as 'OK (Normal)' rather than an empty list.
    """
    field = (context.state or {}).get('Global Flags')
    if field is None:
        return {}
    return {name: name in field.value for name in _FLAG_BITS}


def _split_threshold(name):
    """('TempMon', 'HighWarning') for 'TempMonHighWarningThreshold', else None.

    The kind sits between the group label and the trailing 'Threshold', so it
    cannot be found by looking at the end of the name.
    """
    if not name or not name.endswith('Threshold'):
        return None
    stem = name[:-len('Threshold')]
    for kind in THRESHOLD_KINDS:
        if stem.endswith(kind):
            return stem[:-len(kind)], kind
    return None


def _threshold_groups(context):
    """{group label: {kind: raw}} from every threshold decoded so far."""
    groups = {}
    for field in (context.state or {}).values():
        if field.raw is None:
            continue
        parts = _split_threshold(field.name)
        if parts is None:
            continue
        label, kind = parts
        groups.setdefault(label, {})[kind] = field.raw
    return groups
