# Optical Transceiver Protocol Decoder (CMIS / SFF-8472 / SFF-8436)
# High-Level Analyzer for Saleae Logic 2
# Designed for Optical Modules, QSFP-DD, OSFP, SFP+, QSFP28 transceivers
#
# This file is the entry point and nothing else: it declares the HLA to Logic 2,
# applies the display filter, and wires the layers together. The decoding itself
# lives in three layers that do not know about each other:
#
#   i2c_session.py  I2C addressing -> register accesses (no register semantics)
#   cmis.py         CMIS register semantics  (no I2C frames, no AnalyzerFrames)
#   sff8472.py      SFF-8472 register semantics
#
# with fields.py as the vocabulary they share and regmap.py / decode_utils.py as
# the tables and primitives they both draw on.

import os
import sys
import logging
import traceback
from logging.handlers import RotatingFileHandler

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Logic 2 gives each extension its own module namespace, but a Ctrl+R reload only
# re-executes THIS file - already-imported sibling modules would silently keep
# running their old code. Drop them so the reload actually reloads.
#
# NOTE: inside Logic 2 `sys.modules` is replaced by ModuleDictShim, whose pop()
# takes NO default argument - `sys.modules.pop(name, None)` raises TypeError and
# would take the whole extension down. Always test membership first.
_LOCAL_MODULES = ('saleae_compat', 'fields', 'decode_utils', 'regmap',
                  'user_config', 'i2c_session', 'dispatch', 'aggregate',
                  'compliance', 'cdb', 'cmis', 'sff8472')
for _m in _LOCAL_MODULES:
    if _m in sys.modules:
        sys.modules.pop(_m)

from saleae_compat import HighLevelAnalyzer, AnalyzerFrame, ChoicesSetting  # noqa: E402
from fields import CONSUMED, ControlEvent  # noqa: E402
from i2c_session import I2cSession  # noqa: E402
from dispatch import Dispatcher  # noqa: E402
import aggregate  # noqa: E402
import compliance  # noqa: E402

# --- Logger Setup ---
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "hla_debug.log")

def _setup_logger():
    logger = logging.getLogger("OpticalTransceiverHLA")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        try:
            # Kept small: this file lives in the extension directory and is only
            # a debugging aid, so cap the whole rotation at ~2 MB.
            handler = RotatingFileHandler(LOG_FILE, maxBytes=1 * 1024 * 1024, backupCount=1, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except Exception as err:
            sys.stderr.write(f"[OpticalTransceiverHLA] Failed to initialize file logger: {err}\n")
    return logger

logger = _setup_logger()
logger.info("=" * 60)
logger.info(f"Optical Transceiver HLA module loaded. Log file: {LOG_FILE}")
logger.info(f"Python: {sys.version.split()[0]} | Executable: {sys.executable}")


class OpticalTransceiverHla(HighLevelAnalyzer):
    # Setting: dropdown choice in Saleae Logic 2 UI
    module_standard = ChoicesSetting(
        label='Module Standard',
        choices=('Auto-Detect', 'SFF-8472 (SFP/SFP+)', 'SFF-8436 (QSFP+)', 'CMIS (QSFP-DD/OSFP)')
    )
    filter_mode = ChoicesSetting(
        label='Display Filter',
        choices=('Show All', 'Control & State Only', 'Data & Registers Only')
    )
    output_mode = ChoicesSetting(
        label='Output Mode',
        choices=('Per Byte', 'Transaction Summary')
    )
    compliance_mode = ChoicesSetting(
        label='Consistency Checks',
        choices=('Warnings + Errors', 'Errors Only', 'Off')
    )

    result_types = {
        'optical_event': {
            'format': '{{data.summary}}'
        },
        'optical_field': {
            'format': '{{data.field}}: {{data.value}}'
        },
        'optical_txn': {
            'format': '{{data.summary}}'
        },
        'optical_compliance': {
            'format': '[{{data.severity}}] {{data.message}}'
        },
        'optical_alarm': {
            'format': '[ALARM] {{data.alarm}}'
        }
    }

    def __new__(cls, settings=None, *args, **kwargs):
        # Guarantee default values for all settings if not explicitly provided
        safe_settings = dict(settings) if settings else {}
        for s in cls._get_settings():
            if s.name not in safe_settings:
                if hasattr(s, 'choices') and s.choices:
                    safe_settings[s.name] = s.choices[0]
                else:
                    safe_settings[s.name] = ''
        return super().__new__(cls, safe_settings, *args, **kwargs)

    def __init__(self):
        choice = getattr(self, 'module_standard', 'Auto-Detect')
        forced = None if choice == 'Auto-Detect' else choice.split(' ')[0]
        self.session = I2cSession(forced_standard=forced)
        # Per instance, not shared: see dispatch.py.
        self.dispatcher = Dispatcher()
        self.frame_count = 0
        self._txn_entries = []
        self._txn_fields = []
        # Every field decoded so far, by name. Consistency rules need it because
        # the values they compare are read in different transactions.
        self._state = {}

        logger.info("=" * 60)
        logger.info("OpticalTransceiverHla instance created. Standard: '%s', Filter: '%s'",
                    getattr(self, 'module_standard', 'Auto-Detect'),
                    getattr(self, 'filter_mode', 'Show All'))

    def _create_frame(self, frame_type, start_time, end_time, data, category='data'):
        mode = getattr(self, 'filter_mode', 'Show All')
        if mode == 'Control & State Only' and category != 'control':
            return None
        if mode == 'Data & Registers Only' and category != 'data':
            return None
        return AnalyzerFrame(frame_type, start_time, end_time, data)

    def decode(self, frame: AnalyzerFrame):
        self.frame_count += 1
        try:
            return self._decode_internal(frame)
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            logger.error(f"[Frame #{self.frame_count}] Decode exception: {err_msg}\n{traceback.format_exc()}")
            return AnalyzerFrame('optical_alarm', frame.start_time, frame.end_time, {
                'protocol': 'HLA_ERROR',
                'alarm': f"Decode Error: {err_msg}"
            })

    def _summary_mode(self):
        return getattr(self, 'output_mode', 'Per Byte') == 'Transaction Summary'

    def _decode_internal(self, frame: AnalyzerFrame):
        output = self.session.feed(frame)
        proto = self.session.effective_protocol()
        summarizing = self._summary_mode()

        if frame.type == 'stop':
            return self._finish_transaction(frame, proto, summarizing)

        # The session already knows how to render this one.
        emission = output.emission
        if emission is not None:
            if summarizing:
                self._collect(emission)
                return None
            return self._render_emission(emission, frame, proto)

        if output.access is None:
            return None

        access = output.access
        field = self.dispatcher.decode(self.session, access)

        # The decoder owns the byte but the field it belongs to is not complete
        # yet (first half of a 2-byte value) - show nothing, and above all do
        # not fall through to the raw register display.
        if field is CONSUMED:
            return None
        if field is not None:
            logger.info("[Frame #%d] [%s] %s: %s", self.session.frame_count,
                        proto, field.name, field.value)
            self._txn_fields.append(field)
            if summarizing:
                self._txn_entries.append(('%s: %s' % (field.name, field.value),
                                          field.category))
                return None
            return self._create_frame('optical_field', access.start_time,
                                      access.end_time,
                                      {'protocol': proto, 'field': field.name,
                                       'value': field.value},
                                      category=field.category)

        if summarizing:
            # Nothing per-byte may be emitted in this mode - not even a raw
            # register display. Any frame landing inside the transaction span
            # destroys the data table and stops the analysis partway through the
            # capture, so a stray event here is not cosmetic. Generic reads are
            # represented by the summary's byte count instead.
            return None

        return self._generic(access, proto)

    def _render_emission(self, emission, frame, proto):
        if isinstance(emission, ControlEvent):
            return self._create_frame('optical_event', frame.start_time,
                                      frame.end_time,
                                      {'protocol': proto, 'summary': emission.summary},
                                      category=emission.category)
        return self._create_frame('optical_field', frame.start_time, frame.end_time,
                                  {'protocol': proto, 'field': emission.name,
                                   'value': emission.value},
                                  category=emission.category)

    def _collect(self, emission):
        """Record an emission for the transaction summary.

        Register pointer moves are skipped: one is emitted on every write, and a
        summary's own header already states the address and page it selects.
        """
        if isinstance(emission, ControlEvent):
            if emission.significant:
                self._txn_entries.append((emission.summary, emission.category))
            return
        self._txn_fields.append(emission)
        self._txn_entries.append(('%s: %s' % (emission.name, emission.value),
                                  emission.category))

    def _check_compliance(self, transaction):
        if transaction is None:
            return []
        mode = getattr(self, 'compliance_mode', 'Warnings + Errors')
        if mode == 'Off':
            return []
        context = compliance.Context(
            page=transaction.page,
            bank=transaction.bank,
            is_read=transaction.is_read,
            touched_upper=transaction.touched_upper,
            page_ever_selected=self.session.page_ever_selected,
            state=self._state,
        )
        return compliance.check(self._txn_fields, context, mode)

    def _finish_transaction(self, frame, proto, summarizing):
        """Close a transaction: report consistency findings, and in summary mode
        emit the transaction itself."""
        transaction = self.session.last_transaction

        # Fold this transaction into the accumulated view BEFORE checking, so a
        # rule can compare values read together with ones read earlier. Rules
        # still fire on this transaction's fields alone, so a contradiction is
        # reported when it is seen rather than on every later transaction.
        for field in self._txn_fields:
            self._state[field.name] = field

        findings = self._check_compliance(transaction)

        entries = self._txn_entries
        self._txn_entries = []
        self._txn_fields = []

        if summarizing:
            if transaction is None or transaction.byte_count == 0:
                return None
            summary = aggregate.render(transaction, entries)
            if findings:
                # Folded into the summary rather than emitted as its own frame:
                # a separate frame here would sit inside the transaction's span
                # and destroy the data table. See aggregate.py.
                summary += ' || ' + '; '.join(str(f) for f in findings)
            logger.info("[Txn #%d] %s", transaction.index, summary)
            # Carry the category of the most interesting entry so the display
            # filter still means something: 'Control & State Only' keeps
            # transactions that changed state, 'Data & Registers Only' keeps
            # pure register traffic.
            category = 'control' if any(c == 'control' for _t, c in entries) else 'data'
            return self._create_frame('optical_txn', transaction.start_time,
                                      transaction.end_time,
                                      {'protocol': proto, 'summary': summary},
                                      category=category)

        if not findings:
            return None

        # Emitted on the stop frame. Every per-byte frame of the transaction
        # ended before it, so this overlaps nothing - which is the only reason
        # it can be a frame of its own at all.
        message = '; '.join(str(f) for f in findings)
        logger.info("[Txn #%d] compliance: %s",
                    transaction.index if transaction else 0, message)
        return self._create_frame('optical_compliance', frame.start_time,
                                  frame.end_time,
                                  {'protocol': proto,
                                   'rule': findings[0].rule,
                                   'severity': findings[0].severity,
                                   'message': message},
                                  category='control')

    def _generic(self, access, proto):
        """Fallback for any byte no decoder claimed: show it verbatim."""
        action = "Read" if access.is_read else "Write"
        summary = f"{action} Reg[0x{access.reg:02X}] = 0x{access.value:02X}"
        logger.debug("[Frame #%d] [%s] %s", self.session.frame_count, proto, summary)
        return self._create_frame('optical_event', access.start_time, access.end_time,
                                  {'protocol': proto, 'summary': summary},
                                  category='data')
