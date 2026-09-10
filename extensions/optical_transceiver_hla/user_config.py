# User-editable overrides for the things the decoder cannot work out on its own.
#
# Everything here exists because some CMIS field's meaning depends on another
# register that may simply not appear in a given capture:
#
#   * Aux1/2/3 monitor units follow 01h:145 (laser temperature? TEC current?
#     a second supply rail?), so without that read the scale is unknowable.
#   * The Tx bias multiplier lives in 01h:160; assuming x1 on a module that
#     means x4 under-reports the current fourfold.
#   * The lane count lives in the application descriptors at 00h:86-117.
#
# The rule everywhere is: derive it from the capture when the capture says;
# otherwise take the user's setting; otherwise fall back and SAY SO in the
# output rather than presenting a guess as a measurement.
#
# The loader is deliberately forgiving. A missing file, malformed JSON, or a
# value of the wrong type logs and falls back to the defaults - a broken config
# must never take the decoder down.

import json
import logging
import os

logger = logging.getLogger("OpticalTransceiverHLA")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'user_config.json')

# Sentinel meaning "work it out from the capture".
AUTO = 'auto'

# How each auxiliary monitor function is encoded: (scale, unit, signed).
# A scale of None means the spec does not establish one here, so the value is
# rendered raw with no unit rather than asserting a unit that may be wrong.
# Only these two are pinned down by CMIS (Table 8-64):
#   laser temperature  S16, 1/256 degC
#   supply voltage     S16, 100 uV
MONITOR_FUNCTIONS = {
    'laser_temperature': (1.0 / 256.0, '°C', True),
    'supply_voltage': (100e-6, 'V', True),
    'tec_current': (None, '', True),
    'custom': (None, '', True),
    'unknown': (None, '', True),
}

# Used when neither the capture nor the user says what an auxiliary monitor
# measures. These are the spec's own 0b meanings (01h:145 bits 2/1/0), i.e. the
# reading a module gets if it never advertises otherwise.
DEFAULT_AUX_FUNCTIONS = {
    'aux1': 'custom',
    'aux2': 'laser_temperature',
    'aux3': 'laser_temperature',
    'custom': 'custom',
}

DEFAULTS = {
    'aux_monitor_functions': DEFAULT_AUX_FUNCTIONS,
    'tx_bias_scaling': AUTO,
    'lane_count': AUTO,
    'show_assumption_caveats': True,
}


def _merge(user, defaults):
    """Overlay `user` onto `defaults`, keeping the default type on mismatch."""
    merged = dict(defaults)
    for key, default_value in defaults.items():
        if key not in user:
            continue
        value = user[key]
        if isinstance(default_value, dict):
            if isinstance(value, dict):
                merged[key] = _merge(value, default_value)
            else:
                logger.warning("user_config: '%s' should be an object; using defaults", key)
        elif value is not None:
            merged[key] = value
    return merged


def load(path=CONFIG_PATH):
    """Read the user config, falling back to DEFAULTS on any problem."""
    try:
        with open(path, encoding='utf-8') as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        logger.info("user_config: %s not found, using built-in defaults", path)
        return dict(DEFAULTS)
    except Exception as err:
        logger.error("user_config: cannot read %s (%s: %s); using built-in defaults",
                     path, type(err).__name__, err)
        return dict(DEFAULTS)

    if not isinstance(raw, dict):
        logger.error("user_config: top level must be an object; using defaults")
        return dict(DEFAULTS)

    # Keys starting with '_' are documentation.
    user = {k: v for k, v in raw.items() if not k.startswith('_')}
    merged = _merge(user, DEFAULTS)
    logger.info("user_config loaded from %s", path)
    return merged


def monitor_function(name, config):
    """The (scale, unit, signed) triple for an auxiliary monitor function."""
    if name not in MONITOR_FUNCTIONS:
        logger.warning("user_config: unknown monitor function '%s'; treating as unknown",
                       name)
        name = 'unknown'
    return MONITOR_FUNCTIONS[name]


def resolve(name, observed, config):
    """Pick the setting for `name`: user override, else what the capture showed.

    `observed` is the value derived from the capture (None if the capture never
    said). Returns None when neither is available, which callers must treat as
    "unknown" rather than substituting a plausible-looking number.
    """
    override = config.get(name)
    if override is not None and override != AUTO:
        return override
    return observed
