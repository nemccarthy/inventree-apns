"""Reading values out of free text.

Plain Python, with no Django or InvenTree imports.

- parse_quantity: '100nF', '0.1 µF', '4k7', '±1%', '1/16W' -> a number in the
  base unit, with the unit
- normalise_package / normalise_dielectric: one spelling for the same thing
- parse_qualification / parse_temperature_range: 'AEC-Q200', '-55°C ~ 125°C'
- derive_attributes: pick value, package, tolerance, voltage... out of a part
  name and description, for parts which have no parameters filled in
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

PREFIXES = {
    'f': 1e-15,
    'p': 1e-12,
    'n': 1e-9,
    'u': 1e-6,
    'µ': 1e-6,
    'μ': 1e-6,
    'm': 1e-3,
    'k': 1e3,
    'K': 1e3,
    'M': 1e6,
    'G': 1e9,
}

# Spellings of each unit (lower case) -> the unit
UNIT_ALIASES = {
    'f': 'F',
    'farad': 'F',
    'farads': 'F',
    'h': 'H',
    'henry': 'H',
    'ohm': 'Ω',
    'ohms': 'Ω',
    'ω': 'Ω',
    'r': 'Ω',
    'v': 'V',
    'vdc': 'V',
    'vac': 'V',
    'volt': 'V',
    'volts': 'V',
    'a': 'A',
    'amp': 'A',
    'amps': 'A',
    'w': 'W',
    'watt': 'W',
    'watts': 'W',
    'hz': 'Hz',
    '%': '%',
    'ppm': 'ppm',
    'ppm/°c': 'ppm',
    'ppm/c': 'ppm',
    's': 's',
    'sec': 's',
    'm': 'm',
    'mm': 'mm',
    'g': 'g',
    'b': 'B',
    'bit': 'bit',
    'bits': 'bit',
    'db': 'dB',
    'lm': 'lm',
    'cd': 'cd',
    'k': 'K',
    '°c': '°C',
}

# The Ω sign has two code points (U+2126 and U+03A9)
_OHM_SIGNS = str.maketrans({'Ω': 'Ω', 'Ω': 'Ω', 'ω': 'Ω'})

_NUMBER = r'(-?\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)'
_QUANTITY = re.compile(r'^' + _NUMBER + r'\s*([^\d\s]*(?:\s?[^\d\s]+)?)$')

# '±5%', '+/-5%', '+-5%', '~5%', '<5%', '+5%'
_LEADING = re.compile(r'^(?:±|\+\s*/\s*-|\+-|[~<>≤≥+])\s*')

# 4k7, 4R7, 0R, 2n2, 4u7, 1M5
_INFIX = re.compile(r'^(\d+)([RrkKMmuUµnNpP])(\d*)$')


@dataclass(frozen=True)
class Quantity:
    """A number in the base unit (farads, ohms, volts...), and that unit.

    The unit is '' when the text only held a number, or a number with a
    multiplier ('10k').
    """

    value: float
    unit: str = ''


def _number(text: str) -> Optional[float]:
    text = text.replace(' ', '')

    try:
        if '/' in text:
            top, bottom = text.split('/', 1)
            bottom_value = float(bottom.replace(',', '.'))
            return float(top.replace(',', '.')) / bottom_value if bottom_value else None

        # '1,5' is a decimal comma; '1,000' a thousands separator
        if ',' in text and '.' not in text and not re.fullmatch(r'\d{1,3}(,\d{3})+', text):
            text = text.replace(',', '.')

        return float(text.replace(',', ''))
    except ValueError:
        return None


def _split_unit(unit: str) -> Optional[tuple[float, str]]:
    """Split 'nF' into (1e-9, 'F'). Returns None if the unit is not recognised."""
    unit = unit.strip().translate(_OHM_SIGNS)

    if not unit:
        return 1.0, ''

    # mm is a unit of its own, not milli-metres of something else
    whole = UNIT_ALIASES.get(unit.lower())

    if unit in ('m', 'M', 'k', 'K', 'G', 'u', 'µ', 'μ', 'n', 'p'):
        # A bare multiplier: '10k', '4.7M', '100n'
        return PREFIXES[unit], ''

    if unit[0] in PREFIXES and len(unit) > 1:
        rest = UNIT_ALIASES.get(unit[1:].lower())

        # 'mm' and 'ppm' are whole units; 'MHz', 'mV', 'kOhm' are prefixed
        if rest and unit.lower() not in ('mm', 'ppm', 'ppm/°c', 'ppm/c', 'db', 'cd'):
            return PREFIXES[unit[0]], rest

    if whole:
        return 1.0, whole

    return None


def parse_quantity(text, default_unit: str = '') -> Optional[Quantity]:
    """Read a single quantity from text. Returns None if it is not one.

    'default_unit' (e.g. 'nF', from a parameter template) is used when the
    text holds no unit of its own.
    """
    if text is None:
        return None

    if isinstance(text, (int, float)) and not isinstance(text, bool):
        scale = _split_unit(default_unit) or (1.0, '')
        return Quantity(float(text) * scale[0], scale[1])

    text = _LEADING.sub('', str(text).strip().translate(_OHM_SIGNS))

    if not text or len(text) > 40:
        return None

    infix = _INFIX.match(text)

    if infix and (infix.group(3) or infix.group(2) in 'Rr'):
        whole, letter, fraction = infix.groups()
        value = float(f'{whole}.{fraction or 0}')

        if letter in 'Rr':
            return Quantity(value, 'Ω')

        return Quantity(value * PREFIXES['u' if letter in 'Uµ' else letter], '')

    match = _QUANTITY.match(text)

    if not match:
        # The same value given twice, as suppliers do: '0.063W, 1/16W'
        if ', ' in text:
            return parse_quantity(text.split(', ')[0], default_unit)

        return None

    value = _number(match.group(1))

    if value is None:
        return None

    unit = match.group(2).strip()

    # '16 V DC', '50 V (DC)'
    unit = re.sub(r'\s*\(?(dc|ac|rms)\)?$', '', unit, flags=re.IGNORECASE)

    split = _split_unit(unit)

    if split is None:
        return None

    scale, base = split

    if not base and default_unit:
        default = _split_unit(default_unit)

        if default:
            # '100' with a template unit of nF; '10k' with a template unit of Ω
            scale *= default[0]
            base = default[1]

    return Quantity(value * scale, base)


# Chip sizes: the metric code for each imperial one
CHIP_SIZES = {
    '01005': '0402',
    '0201': '0603',
    '0402': '1005',
    '0603': '1608',
    '0805': '2012',
    '1206': '3216',
    '1210': '3225',
    '1806': '4516',
    '1812': '4532',
    '2010': '5025',
    '2512': '6332',
}

_CHIP = re.compile(r'(?<![\d.])(' + '|'.join(CHIP_SIZES) + r')(?![\d.])')

_IC_PACKAGE = re.compile(
    r'\b((?:SOT|SOD|SC|TO|DO)-?\d{1,3}[A-Z]{0,2}(?:-\d{1,2})?'
    r'|(?:H?V?T?S?SOP|SOIC|MSOP|[HV]?[LTV]?QFP|[HV]?[UWX]?[DQ]FN|[FLW]?BGA|WLCSP|DIP|PLCC)-?\d{1,3}'
    r'|D2?PAK|SM[ABC]F?|MELF|MINI-?MELF)\b',
    re.IGNORECASE,
)

DIELECTRICS = ('C0G', 'NP0', 'X5R', 'X6S', 'X7R', 'X7S', 'X7T', 'X8R', 'Y5V', 'Z5U', 'U2J')
_DIELECTRIC = re.compile(r'\b(' + '|'.join(DIELECTRICS) + r'|COG|NPO)\b', re.IGNORECASE)


# Different names for the same package
_PACKAGE_ALIASES = {
    'SOT-23-3': 'SOT-23',
    'TO-236': 'SOT-23',
    'SC-59': 'SOT-23',
    'SC-70-3': 'SC-70',
    'SOT-323': 'SC-70',
    'SOD-123F': 'SOD-123',
    'TO-252': 'DPAK',
    'TO-252-3': 'DPAK',
    'TO-263-3': 'D2PAK',
    'TO-263': 'D2PAK',
    'DO-214AC': 'SMA',
    'DO-214AA': 'SMB',
    'DO-214AB': 'SMC',
    'SOP-8': 'SOIC-8',
}


def normalise_package(text) -> str:
    """One spelling for a package: '0402 (1005 Metric)' -> '0402', 'SOT23-5' -> 'SOT-23-5'."""
    if not text:
        return ''

    raw = str(text).strip()
    chip = _CHIP.search(raw)

    if chip:
        return chip.group(1)

    upper = raw.upper()

    # '8-SOIC (0.154", 3.90mm Width)' -> 'SOIC-8'
    leading = re.match(r'^(\d{1,3})-([A-Z]{2,8})\b', upper)

    if leading:
        upper = f'{leading.group(2)}-{leading.group(1)}'

    ic = _IC_PACKAGE.search(upper)

    if ic:
        name = ic.group(1).replace('MINIMELF', 'MINI-MELF')
        # SOT23-5 -> SOT-23-5, SOIC8 -> SOIC-8
        parts = re.match(r'^([A-Z]+)-?(\d+[A-Z]{0,2})(?:-(\d+))?$', name)

        if parts:
            family, number, pins = parts.groups()
            name = f'{family}-{number}' + (f'-{pins}' if pins else '')

        return _PACKAGE_ALIASES.get(name, name)

    return re.sub(r'[\s_]+', ' ', upper)


def normalise_dielectric(text) -> str:
    """One spelling for a dielectric class: 'NP0', 'COG', 'C0G (NP0)' -> 'C0G'."""
    if not text:
        return ''

    match = _DIELECTRIC.search(str(text))

    if not match:
        return ''

    code = match.group(1).upper().replace('COG', 'C0G').replace('NPO', 'NP0')

    return 'C0G' if code == 'NP0' else code


_AEC = re.compile(r'AEC[\s\-]?Q[\s\-]?(\d{3})', re.IGNORECASE)
_AEC_GRADE = re.compile(r'grade[\s\-]?([0-4])\b', re.IGNORECASE)
_MIL = re.compile(r'\bMIL[\s\-]?(PRF|STD|DTL|R|C)[\s\-]?(\d{2,6})', re.IGNORECASE)
_AUTOMOTIVE = re.compile(r'\bautomotive\b', re.IGNORECASE)
_YES = re.compile(r'^(yes|y|true|1|qualified|compliant)$', re.IGNORECASE)


def parse_qualification(text, name: str = '') -> tuple[frozenset, Optional[int]]:
    """The qualifications a value states, and the AEC-Q100 grade if one is given.

    'AEC-Q200' -> ({'AEC-Q200', 'AUTOMOTIVE'}, None)
    'Automotive, AEC-Q100 Grade 1' -> ({'AEC-Q100', 'AUTOMOTIVE'}, 1)
    'MIL-PRF-55342' -> ({'MIL-PRF-55342'}, None)
    '-', 'No', 'Commercial' -> (empty, None)

    'name' is the name of the parameter: a parameter called 'AEC-Q200' with
    the value 'Yes' states that qualification.
    """
    text = str(text or '')

    if _YES.match(text.strip()):
        text = str(name or '')

    found = {f'AEC-Q{number}' for number in _AEC.findall(text)}
    found |= {f'MIL-{kind.upper()}-{number}' for kind, number in _MIL.findall(text)}

    if found & {item for item in found if item.startswith('AEC')} or _AUTOMOTIVE.search(text):
        # An AEC-Q part is an automotive part
        found.add('AUTOMOTIVE')

    grade = _AEC_GRADE.search(text)

    return frozenset(found), int(grade.group(1)) if grade and found else None


_RANGE = re.compile(
    r'([+\-\u2212]?\s?\d+(?:\.\d+)?)\s*°?\s*[CK]?\s*(?:~|to|\.\.\.?|\u2026|/|\u2013|\u2014|-(?=\s*[+\d]))\s*'
    r'([+\-\u2212]?\s?\d+(?:\.\d+)?)\s*°?\s*C?',
    re.IGNORECASE,
)


def parse_temperature_range(text) -> Optional[tuple[float, float]]:
    """'-55°C ~ 125°C', '-40 to +85 °C', '0°C ~ 70°C (TA)' -> (low, high)."""
    match = _RANGE.search(str(text or ''))

    if not match:
        return None

    try:
        low, high = (
            float(item.replace('\u2212', '-').replace(' ', '').replace('+', '')) for item in match.groups()
        )
    except ValueError:
        return None

    return (low, high) if low < high else None


# Which attribute a quantity found in a description belongs to, by its unit
_UNIT_ROLES = {
    'F': 'capacitance',
    'Ω': 'resistance',
    'H': 'inductance',
    'V': 'voltage',
    'W': 'power',
    'A': 'current',
    '%': 'tolerance',
    'Hz': 'frequency',
}

_TOKEN_SPLIT = re.compile(r'[\s,;|()\[\]]+')


def derive_attributes(*texts) -> dict[str, str]:
    """Pick well-known attributes out of free text (part name, description).

    Returns {role: text}, e.g. {'capacitance': '100nF', 'package': '0402',
    'voltage': '16V', 'tolerance': '10%', 'dielectric': 'X7R'}. Only the
    first value found for each attribute is kept.
    """
    found: dict[str, str] = {}
    text = ' '.join(str(item) for item in texts if item)

    if not text.strip():
        return found

    # 'X7R', 'C0G' before anything else, so that they are not read as values
    dielectric = normalise_dielectric(text)

    if dielectric:
        found['dielectric'] = dielectric

    qualifications, grade = parse_qualification(text)

    if any(item.startswith(('AEC', 'MIL')) for item in qualifications):
        stated = sorted(item for item in qualifications if item != 'AUTOMOTIVE')
        found['qualification'] = ', '.join(stated) + (f' Grade {grade}' if grade is not None else '')

    chip = _CHIP.search(text)
    ic = _IC_PACKAGE.search(text)

    if chip:
        found['package'] = chip.group(1)
    elif ic:
        found['package'] = normalise_package(ic.group(1))

    # Join a number to a unit which follows it after a space: '100 nF' -> '100nF'
    joined = re.sub(
        r'(\d)\s+(?=(?:[fpnuµμmkKMG]?(?:F|H|Hz|V|W|A|Ω|ohms?|Ohms?|R)|%)(?![A-Za-z]))',
        r'\1',
        text.translate(_OHM_SIGNS),
    )

    for token in _TOKEN_SPLIT.split(joined):
        token = token.strip('.:=')

        if not token or not (token[0].isdigit() or token[0] in '±+<'):
            continue

        if _DIELECTRIC.fullmatch(token) or _CHIP.fullmatch(token):
            continue

        quantity = parse_quantity(token)

        if quantity is None:
            continue

        role = _UNIT_ROLES.get(quantity.unit)

        if role is None and not quantity.unit:
            # '10k', '4k7', '1M' is a resistance and '100n', '22p' a capacitance.
            # A bare number is not a value.
            if re.fullmatch(r'\d+(?:\.\d+)?[kKM]\d*', token):
                role = 'resistance'
            elif re.fullmatch(r'\d+(?:\.\d+)?[np]\d*', token):
                role = 'capacitance'

        if role and role not in found:
            found[role] = _LEADING.sub('', token)

    return found
