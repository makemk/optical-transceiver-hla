# Pure decoding primitives shared by every protocol decoder.
#
# No state, no imports beyond `math`. Everything here used to be inlined and
# duplicated across the CMIS and SFF-8472 branches; the conversion factors are
# fixed by the specs, so they live in exactly one place.

import math

# CMIS fixes the scaling of these monitor registers:
#   temperature  S16, 1/256 degC      (Table 8-10)
#   voltage      U16, 100 uV          (Table 8-10)
#   optical pwr  U16, 0.1 uW          (Table 8-99)
#   laser bias   U16, 2 uA * mult     (Table 8-99)
CMIS_TEMP_SCALE = 1.0 / 256.0
CMIS_VOLT_SCALE = 100e-6
CMIS_POWER_SCALE = 0.1
CMIS_BIAS_SCALE = 0.002

# Floor for the dBm conversion: 0 uW is -inf, and a module reporting no light is
# conventionally shown at the noise floor rather than as an error.
DBM_FLOOR = -40.0


# --- integer assembly --------------------------------------------------------

def u16(msb, lsb):
    return ((msb & 0xFF) << 8) | (lsb & 0xFF)


def s16(msb, lsb):
    raw = u16(msb, lsb)
    return raw - 0x10000 if raw >= 0x8000 else raw


# --- physical units ----------------------------------------------------------

def temperature_c(msb, lsb):
    """CMIS / SFF-8472 module temperature in degrees Celsius."""
    return s16(msb, lsb) * CMIS_TEMP_SCALE


def voltage_v(msb, lsb):
    """Supply voltage in volts."""
    return u16(msb, lsb) * CMIS_VOLT_SCALE


def power_uw(msb, lsb):
    """Optical power in microwatts."""
    return u16(msb, lsb) * CMIS_POWER_SCALE


def bias_ma(msb, lsb, multiplier=1.0):
    """Laser bias current in milliamps."""
    return u16(msb, lsb) * CMIS_BIAS_SCALE * multiplier


def uw_to_dbm(uw):
    return (10 * math.log10(uw / 1000.0)) if uw > 0 else DBM_FLOOR


def power_str(uw):
    """The existing user-visible power format: '-2.60 dBm (550.0 uW)'."""
    return f"{uw_to_dbm(uw):.2f} dBm ({uw:.1f} uW)"


def threshold_value(msb, lsb, unit, multiplier=1.0):
    """The number behind threshold_str, for consistency checking.

    Returns None where the unit is not established (the auxiliary monitors,
    whose scale depends on a register that may not be in the capture).
    """
    if unit == 'degC':
        return temperature_c(msb, lsb)
    if unit == 'V':
        return voltage_v(msb, lsb)
    if unit == 'uW':
        return power_uw(msb, lsb)
    if unit == 'mA':
        return bias_ma(msb, lsb, multiplier)
    return None


def threshold_str(msb, lsb, unit, multiplier=1.0):
    """Render a 2-byte supervision threshold in its declared unit.

    `multiplier` is the 01h:160 TxBiasCurrentScalingFactor, which the spec
    applies to the bias thresholds as well as the bias monitor.
    """
    if unit == 'degC':
        return f"{temperature_c(msb, lsb):.2f} °C"
    if unit == 'V':
        return f"{voltage_v(msb, lsb):.3f} V"
    if unit == 'uW':
        return power_str(power_uw(msb, lsb))
    if unit == 'mA':
        return f"{bias_ma(msb, lsb, multiplier):.2f} mA"
    # Aux / Custom: the physical unit follows the monitor function selected at
    # 01h:145 (laser temperature vs an additional supply rail), which is not
    # decoded yet. Report the 1/256 reading, the spec's default for these, with
    # no unit suffix rather than asserting the wrong one.
    return f"{temperature_c(msb, lsb):.2f}"


# --- bitfields ---------------------------------------------------------------

def lane_bitmap(val, count=8):
    """Lane numbers whose bit is set in a per-lane 8-bit register.

    Bit 0 is lane 1 (CMIS numbers lanes from 1). `count` caps how many lanes the
    module actually has, so a 2-lane SFP-DD does not report phantom lanes 3-8.
    Returns None when empty so the caller can choose its own empty token.
    """
    lanes = [str(i + 1) for i in range(max(0, min(8, count))) if val & (1 << i)]
    return ', '.join(lanes) if lanes else None


def flag_names(val, bit_names, empty=None):
    """Expand a flag byte to names, highest bit first.

    `bit_names` maps bit position -> name. Bits not present in the mapping are
    ignored, so a partial table degrades to partial output rather than raising.
    """
    names = [bit_names[b] for b in sorted(bit_names, reverse=True) if val & (1 << b)]
    if names:
        return ', '.join(names)
    return empty


def nibble_lane_states(buf, table, base_lane=1):
    """Expand bytes holding two 4-bit lane states each (low nibble first).

    Used for the DP state and ConfigStatus arrays, where the low nibble of the
    first byte belongs to the lowest-numbered lane (CMIS 5.4 Table 8-93).
    """
    out = []
    for i, byte in enumerate(buf):
        out.append((base_lane + 2 * i, table.get(byte & 0x0F, f"Unknown({byte & 0x0F})")))
        out.append((base_lane + 2 * i + 1, table.get((byte >> 4) & 0x0F,
                                                     f"Unknown({(byte >> 4) & 0x0F})")))
    return out


# --- ASCII -------------------------------------------------------------------

def printable(byte):
    """The existing single-character rendering: a printable ASCII char or '.'."""
    return chr(byte) if 32 <= byte <= 126 else '.'


def char_field(byte):
    """The existing per-byte string format: "'A' (0x41)"."""
    return f"'{printable(byte)}' (0x{byte:02X})"


def ascii_string(raw, strip=True):
    """Assemble a NUL-terminated / space-padded ASCII field."""
    text = ''.join(chr(b) if 32 <= b <= 126 else '' for b in raw)
    return text.strip() if strip else text
