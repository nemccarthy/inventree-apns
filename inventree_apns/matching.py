"""Finding parts which could stand in for each other.

Plain Python, with no Django or InvenTree imports, so that it can be tested
on its own.

Each part is reduced to a set of attributes (capacitance, package, voltage
rating, ...) taken from its parameters, and from its name and description
where a parameter is missing. Two parts are then compared attribute by
attribute:

- Some attributes have to be the same (value, package, dielectric).
- Some may be better on the alternate: a tighter tolerance or a higher
  voltage rating can replace a looser or lower one, but not the other way
  round. That is what makes a match one-way.

The result is a strength from 0 to 100, the direction in which the two parts
can replace each other, and the comparison of each attribute.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Iterable, Optional

from .parse import (
    Quantity,
    derive_attributes,
    normalise_dielectric,
    normalise_package,
    parse_qualification,
    parse_quantity,
    parse_temperature_range,
)

# How much each kind of attribute counts
WEIGHTS = {'critical': 5.0, 'major': 3.0, 'minor': 1.0}
NAME_WEIGHT = 1.5
CATEGORY_WEIGHT = 0.5

# An attribute read out of the description counts for less than a parameter
DERIVED_FACTOR = 0.7

# Numbers within 1% are the same value
SAME = 0.01
# A part which exceeds a rating is a slightly weaker match than one which
# equals it, so that the like-for-like part is listed first
BETTER = 0.9
# Numbers within 10% are close (for attributes which do not have to be equal)
CLOSE = 0.10
# Text which is at least this similar is close
TEXT_CLOSE = 0.8

# A match which rests on the names alone is worth less
NAME_ONLY_FACTOR = 0.7
NAME_ONLY_MINIMUM = 0.75

# Groups larger than this are not searched pair by pair
MAX_GROUP = 400


@dataclass(frozen=True)
class Role:
    """A kind of attribute, and how two values of it are compared."""

    key: str
    label: str
    level: str = 'minor'  # critical / major / minor
    direction: str = 'equal'  # equal / higher / lower (which way is better)
    kind: str = 'auto'  # number / package / dielectric / qualification / range / text / auto
    unit: str = ''
    # A different number rules the part out as an alternate (output voltage,
    # number of pins), although the attribute is not one of the known ones
    strict: bool = False


ROLES = {
    role.key: role
    for role in (
        Role('capacitance', 'Capacitance', 'critical', 'equal', 'number', 'F'),
        Role('resistance', 'Resistance', 'critical', 'equal', 'number', 'Ω'),
        Role('inductance', 'Inductance', 'critical', 'equal', 'number', 'H'),
        Role('frequency', 'Frequency', 'critical', 'equal', 'number', 'Hz'),
        Role('value', 'Value', 'critical', 'equal', 'auto'),
        Role('package', 'Package', 'critical', 'equal', 'package'),
        Role('dielectric', 'Dielectric', 'major', 'equal', 'dielectric'),
        # A qualified part can replace an unqualified one, not the reverse
        Role('qualification', 'Qualification', 'major', 'higher', 'qualification'),
        # A wider operating range can replace a narrower one
        Role('temperature', 'Operating temperature', 'major', 'higher', 'range'),
        Role('tolerance', 'Tolerance', 'major', 'lower', 'number', '%'),
        Role('voltage', 'Voltage rating', 'major', 'higher', 'number', 'V'),
        Role('power', 'Power rating', 'major', 'higher', 'number', 'W'),
        Role('current', 'Current rating', 'major', 'higher', 'number', 'A'),
        Role('tempco', 'Temperature coefficient', 'minor', 'lower', 'number', 'ppm'),
        Role('esr', 'ESR', 'minor', 'lower', 'number', 'Ω'),
        Role('dcr', 'DC resistance', 'minor', 'lower', 'number', 'Ω'),
        Role('mounting', 'Mounting', 'minor', 'equal', 'text'),
    )
}

# Parameter names (normalised: lower case, punctuation removed) -> role.
# Checked in order; the first match wins.
_NAME_RULES: list[tuple[str, re.Pattern]] = [
    (key, re.compile(pattern))
    for key, pattern in (
        ('esr', r'^esr\b|equivalent series resistance'),
        ('dcr', r'^dcr\b|^dc resistance'),
        ('capacitance', r'^capacitance( value)?$|^cap(acitor)? value$'),
        ('resistance', r'^resistance( value)?$|^resistor value$|^ohms$'),
        ('inductance', r'^inductance( value)?$'),
        ('frequency', r'^(center |nominal )?frequency( nominal)?$'),
        ('value', r'^(nominal )?value$'),
        (
            'package',
            r'^package$|^package case$|^case package$|^case$|^case code$|^case size$'
            r'|^footprint$|^supplier device package$|^package type$|^encapsulation$'
            r'|^smd size$|^size$|^size code$|^chip size$',
        ),
        ('tolerance', r'^((capacitance|resistance|inductance|frequency) )?tolerance$'),
        (
            'voltage',
            r'^voltage rat(ed|ing)( dc)?$|^rated voltage( dc)?$|^voltage$|^voltage dc$'
            r'|^working voltage$|^max(imum)? voltage$|^voltage max(imum)?$',
        ),
        ('power', r'^power( rating)?( watts)?$|^rated power$|^power max(imum)?$|^max(imum)? power$'),
        (
            'current',
            r'^current rating( amps)?$|^rated current$|^current rated$|^current max(imum)?$'
            r'|^max(imum)? current$',
        ),
        (
            'dielectric',
            r'^dielectric( type| material)?$|^temperature (coefficient|characteristic)$'
            r'|^temp(erature)? ?co(efficient)?$',
        ),
        ('mounting', r'^mount(ing)?( type| style)?$'),
        (
            'qualification',
            r'^qualifications?$|^ratings?$|^grade$|^automotive( grade| qualified)?$|^aec\b|^aec q',
        ),
        (
            'temperature',
            r'^operating temp(erature)?( range)?$|^temp(erature)? range$|^working temp(erature)?( range)?$',
        ),
    )
]

# Parameters which say nothing about whether one part can replace another
_IGNORED = re.compile(
    r'\b(rohs|reach|lifecycle|life cycle|status|lead time|moq|msl|moisture|htsus|eccn'
    r'|datasheet|url|link|sku|mpn|part number|manufacturer|supplier|lcsc|jlc|jlcpcb'
    r'|packaging|package qty|standard package|base product|series|price|cost|note'
    r'|notes|comment|weight|height|length|width|thickness|dimension|dimensions'
    r'|seated|stock|features)\b'
)

# Other parameters which usually have to be the same
_KEY = re.compile(
    r'\b(output|nominal|number of|count|pins?|positions?|channels?|circuits?|contacts?'
    r'|rows?|bits?|memory size|pitch|colou?r|wavelength|type|configuration|polarity'
    r'|function|interface|protocol|core|speed|gender|style|technology|topology)\b'
)

# The attributes which say what value a part is
_VALUE_ROLES = ('capacitance', 'resistance', 'inductance', 'frequency', 'value')

_STOPWORDS = frozenset(
    'a an and the of for with to in on by mm smd smt chip ic part generic'.split()
)

_WORD = re.compile(r'[a-z0-9]+(?:\.[0-9]+[a-z0-9]*)?')


def normalise_name(name) -> str:
    """Lower case, with punctuation turned into single spaces."""
    return re.sub(r'[^a-z0-9%]+', ' ', str(name or '').lower()).strip()


def normalise_mpn(mpn) -> str:
    """Manufacturer part number without spaces or punctuation, in upper case."""
    return re.sub(r'[^A-Z0-9]', '', str(mpn or '').upper())


def role_for(name) -> Optional[str]:
    """The role of a parameter, from its name. None if it is to be ignored.

    Parameters with no role of their own get the key 'p:<normalised name>',
    and are only ever compared with the same parameter of another part.
    """
    norm = normalise_name(name)

    if not norm:
        return None

    for key, pattern in _NAME_RULES:
        if pattern.search(norm):
            return key

    if _IGNORED.search(norm):
        return None

    return f'p:{norm}'


@lru_cache(maxsize=8192)
def spec_for(key: str, label: str = '') -> Role:
    """How the attribute with this key is compared."""
    role = ROLES.get(key)

    if role:
        return role

    name = key[2:] if key.startswith('p:') else key

    important = bool(_KEY.search(name))

    return Role(key, label or name, 'major' if important else 'minor', strict=important)


@dataclass
class Attr:
    """One attribute of a part."""

    key: str
    label: str
    text: str
    quantity: Optional[Quantity] = None
    norm: str = ''
    derived: bool = False
    # The name of the parameter it was taken from
    source: str = ''


@dataclass
class PartFeatures:
    """What is known about a part, for matching."""

    pk: int
    name: str = ''
    ipn: str = ''
    description: str = ''
    category: Optional[int] = None
    category_path: tuple = ()
    mpns: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)
    tokens: frozenset = frozenset()
    numbers: frozenset = frozenset()
    norm_name: str = ''
    active: bool = True
    # Parameters which are shown in a comparison but not compared:
    # {parameter name: value}
    extras: dict = field(default_factory=dict)


def make_attr(key: str, label: str, text, unit: str = '', numeric=None, derived=False) -> Optional[Attr]:
    """Build an attribute from a parameter value.

    'unit' is the unit of the parameter template (may be empty) and 'numeric'
    the number InvenTree worked out for the value, in that unit (may be None).
    """
    text = '' if text is None else str(text).strip()

    if not text:
        return None

    spec = spec_for(key, label)
    display = text if not unit or text.lower().endswith(unit.lower()) else f'{text} {unit}'

    if spec.kind == 'package':
        return Attr(key, spec.label, display, None, normalise_package(text), derived)

    if spec.kind == 'dielectric':
        code = normalise_dielectric(text)

        if code:
            return Attr(key, spec.label, display, None, code, derived)

        # A temperature coefficient given as a number (resistors): ±100 ppm/°C
        quantity = parse_quantity(re.sub(r'\s*/\s*°?[ck]\b', '', text, flags=re.IGNORECASE), unit)

        if quantity:
            role = ROLES['tempco']
            return Attr(role.key, role.label, display, quantity, '', derived)

        return Attr(key, spec.label, display, None, normalise_name(text), derived)

    if spec.kind == 'qualification':
        stated, grade = parse_qualification(text, label)

        # 'No', '-', 'Commercial': nothing is claimed, which is the same as
        # the parameter not being there
        if not stated:
            return None

        return Attr(key, spec.label, display, None, qualification_norm(stated, grade), derived)

    if spec.kind == 'range':
        limits = parse_temperature_range(text)

        if limits is None:
            return Attr(f'p:{normalise_name(label)}', label, display, None, normalise_name(text), derived)

        return Attr(key, spec.label, display, None, f'{limits[0]:g}|{limits[1]:g}', derived)

    quantity = None

    if spec.kind in ('number', 'auto'):
        quantity = parse_quantity(text, unit or '')

        if quantity is None and numeric is not None and math.isfinite(numeric):
            quantity = parse_quantity(float(numeric), unit or '')

        if quantity and not quantity.unit and spec.unit:
            quantity = Quantity(quantity.value, spec.unit)

    if key == 'value' and quantity:
        # A 'Value' parameter is a capacitance, resistance... by its unit
        actual = {'F': 'capacitance', 'Ω': 'resistance', 'H': 'inductance', 'Hz': 'frequency'}.get(
            quantity.unit
        )

        if actual:
            role = ROLES[actual]
            return Attr(role.key, role.label, display, quantity, '', derived)

    return Attr(key, spec.label, display, quantity, normalise_name(text), derived)


def qualification_norm(stated, grade) -> str:
    """'AEC-Q100+AUTOMOTIVE|1': the qualifications, and the grade if given."""
    return '+'.join(sorted(stated)) + ('' if grade is None else f'|{grade}')


def _qualification(norm: str) -> tuple[frozenset, Optional[int]]:
    names, _, grade = norm.partition('|')

    return frozenset(filter(None, names.split('+'))), int(grade) if grade else None


# Shown for the part which states no qualification
NO_QUALIFICATION = 'None stated'


def build_features(
    pk: int,
    name: str = '',
    ipn: str = '',
    description: str = '',
    category: Optional[int] = None,
    category_path: Iterable[int] = (),
    mpns: Iterable[str] = (),
    parameters: Iterable[dict] = (),
    active: bool = True,
    use_description: bool = True,
) -> PartFeatures:
    """Reduce a part to its attributes.

    'parameters' is a list of {'name', 'data', 'units', 'numeric'}.
    """
    attrs: dict[str, Attr] = {}
    extras: dict[str, str] = {}

    def shown(parameter) -> None:
        name = str(parameter.get('name') or '').strip()
        value = str(parameter.get('data') or '').strip()
        units = str(parameter.get('units') or '')

        if name and value:
            extras[name] = value if not units or value.lower().endswith(units.lower()) else f'{value} {units}'

    for parameter in parameters:
        key = role_for(parameter.get('name'))

        if key is None:
            shown(parameter)
            continue

        attr = make_attr(
            key,
            str(parameter.get('name') or ''),
            parameter.get('data'),
            str(parameter.get('units') or ''),
            parameter.get('numeric'),
        )

        if attr is None:
            continue

        existing = attrs.get(attr.key)

        # Two parameters for the same thing ('Package / Case' and 'Supplier
        # Device Package'): keep the one which reads as a known value
        attr.source = str(parameter.get('name') or '').strip()

        if existing is None:
            attrs[attr.key] = attr
        elif existing.quantity is None and attr.quantity is not None:
            # The one which reads as a known value is compared; the other is shown
            if existing.source:
                extras[existing.source] = existing.text

            attrs[attr.key] = attr
        else:
            shown(parameter)

    if use_description:
        derived = derive_attributes(name, description)
        # '16V' in the description of a capacitor is its rating; in the
        # description of a regulator it is not. Ratings are only read from
        # the text of parts which have a value.
        passive = any(key in attrs or key in derived for key in _VALUE_ROLES)

        for key, text in derived.items():
            if key in attrs:
                continue

            if not passive and key not in ('package', 'qualification'):
                continue

            # A value read from the text is only trusted if nothing else
            # already says what kind of part this is
            if key in ('capacitance', 'resistance', 'inductance', 'frequency') and any(
                other in attrs for other in ('capacitance', 'resistance', 'inductance', 'frequency', 'value')
            ):
                continue

            attr = make_attr(key, ROLES[key].label, text, derived=True)

            if attr:
                attrs[attr.key] = attr

    norm_name = normalise_name(name)
    words = _WORD.findall(f'{name or ""} {description or ""}'.lower())
    tokens = frozenset(word for word in words if word not in _STOPWORDS and len(word) > 1)

    return PartFeatures(
        pk=pk,
        name=name or '',
        ipn=ipn or '',
        description=description or '',
        category=category,
        category_path=tuple(category_path or ()),
        mpns=frozenset(filter(None, (normalise_mpn(mpn) for mpn in mpns))),
        attrs=attrs,
        tokens=tokens,
        numbers=frozenset(token for token in tokens if any(char.isdigit() for char in token)),
        norm_name=norm_name,
        active=active,
        extras=extras,
    )


def _relative(a: float, b: float) -> float:
    if a == b:
        return 0.0

    return abs(a - b) / max(abs(a), abs(b))


def compare_attr(spec: Role, a: Attr, b: Attr) -> tuple[float, str]:
    """Compare one attribute, for 'b' taking the place of 'a'.

    Returns (score from 0 to 1, verdict). The verdict is one of: match,
    better, close, worse, differ.
    """
    if spec.kind == 'qualification':
        wanted, wanted_grade = _qualification(a.norm)
        offered, offered_grade = _qualification(b.norm)

        # Every qualification of the part has to be held by its replacement
        if not wanted <= offered:
            return 0.0, 'worse'

        # AEC-Q100 grades: 0 is the widest temperature range
        if wanted_grade is not None and offered_grade is not None and offered_grade > wanted_grade:
            return 0.0, 'worse'

        if wanted == offered and wanted_grade == offered_grade:
            return 1.0, 'match'

        if wanted == offered and offered_grade is None:
            # The same qualification, with no grade given for the replacement
            return 1.0, 'match'

        return BETTER, 'better'

    if spec.kind == 'range' and '|' in a.norm and '|' in b.norm:
        low, high = (float(item) for item in a.norm.split('|'))
        other_low, other_high = (float(item) for item in b.norm.split('|'))

        if abs(low - other_low) <= 0.5 and abs(high - other_high) <= 0.5:
            return 1.0, 'match'

        if other_low <= low + 0.5 and other_high >= high - 0.5:
            return BETTER, 'better'

        return 0.0, 'worse'

    if a.quantity and b.quantity and (
        a.quantity.unit == b.quantity.unit or not a.quantity.unit or not b.quantity.unit
    ):
        x, y = a.quantity.value, b.quantity.value
        difference = _relative(x, y)

        if spec.direction == 'higher':
            if difference <= SAME:
                return 1.0, 'match'
            return (BETTER, 'better') if y > x else (0.0, 'worse')

        if spec.direction == 'lower':
            if difference <= SAME:
                return 1.0, 'match'
            return (BETTER, 'better') if y < x else (0.0, 'worse')

        if difference <= SAME:
            return 1.0, 'match'

        if spec.level != 'critical' and difference <= CLOSE:
            return 0.5, 'close'

        return 0.0, 'differ'

    left = a.norm or normalise_name(a.text)
    right = b.norm or normalise_name(b.text)

    if left == right:
        return 1.0, 'match'

    if spec.kind == 'package':
        # 'SOT-23-5' and 'SOT-23-6' are nearly the same text, and not the same package
        return 0.0, 'differ'

    ratio = SequenceMatcher(None, left, right).ratio()

    if ratio >= TEXT_CLOSE:
        return ratio, 'close'

    return 0.0, 'differ'


def name_similarity(a: PartFeatures, b: PartFeatures, precise: bool = True) -> float:
    """How alike two parts are by name and description, from 0 to 1.

    'precise' also compares the names letter by letter, which is slower: it
    is used when the names are all there is to go on.
    """
    if not a.tokens or not b.tokens:
        return 0.0

    shared = len(a.tokens & b.tokens)
    jaccard = shared / len(a.tokens | b.tokens)

    if not precise or a.norm_name == b.norm_name:
        return jaccard if not precise else 0.5 * jaccard + 0.5

    ratio = SequenceMatcher(None, a.norm_name, b.norm_name).ratio()

    return 0.5 * jaccard + 0.5 * ratio


def category_similarity(a: PartFeatures, b: PartFeatures) -> float:
    if a.category is None or b.category is None:
        return 0.0

    if a.category == b.category:
        return 1.0

    # One inside the other, or the same parent
    if a.category in b.category_path or b.category in a.category_path:
        return 0.5

    if a.category_path[-2:-1] and a.category_path[-2:-1] == b.category_path[-2:-1]:
        return 0.5

    return 0.0


@dataclass
class Match:
    """The comparison of two parts.

    direction: 'both' (interchangeable), 'forward' ('other' can replace
    'part', not the reverse), 'reverse' ('part' can replace 'other') or
    'none' (only from a forced comparison).
    """

    part: int
    other: int
    strength: int
    direction: str
    basis: str  # 'parameters', 'name' or 'mpn'
    coverage: float
    rows: list
    same_mpn: bool = False
    flags: list = field(default_factory=list)

    def flipped(self) -> 'Match':
        """The same match, seen from the other part."""
        swap = {'forward': 'reverse', 'reverse': 'forward'}
        verdicts = {'better': 'worse', 'worse': 'better'}

        return Match(
            part=self.other,
            other=self.part,
            strength=self.strength,
            direction=swap.get(self.direction, self.direction),
            basis=self.basis,
            coverage=self.coverage,
            rows=[
                {
                    **row,
                    'a': row['b'],
                    'b': row['a'],
                    'verdict': verdicts.get(row['verdict'], row['verdict']),
                }
                for row in self.rows
            ],
            same_mpn=self.same_mpn,
            flags=list(self.flags),
        )


def compare(a: PartFeatures, b: PartFeatures, force: bool = False) -> Optional[Match]:
    """Compare two parts. Returns None if neither can replace the other.

    With 'force', a comparison is always returned (for two parts which are
    already linked): its direction is 'none' if the attributes say that
    neither part can replace the other.
    """
    if a.pk == b.pk:
        return None

    same_mpn = bool(a.mpns & b.mpns)
    rows = []
    total = compared = 0.0
    forward = reverse = 0.0
    block_forward = block_reverse = False
    # What the two parts were compared on, leaving the package aside: the
    # same package alone does not make two parts alternates
    critical_compared = 0
    major_compared = 0
    package_compared = False

    for key in sorted(set(a.attrs) | set(b.attrs), key=_row_order):
        left, right = a.attrs.get(key), b.attrs.get(key)
        spec = spec_for(key, (left or right).label)
        derived = bool((left and left.derived) or (right and right.derived))
        weight = WEIGHTS[spec.level] * (DERIVED_FACTOR if derived else 1.0)
        total += weight

        row = {
            'key': key,
            'label': spec.label,
            'level': spec.level,
            'a': left.text if left else None,
            'b': right.text if right else None,
            'derived': derived,
        }

        if key == 'qualification' and (left is None or right is None):
            # Stating no qualification is not the same as an unknown value:
            # the part is taken to have none, so it cannot stand in for one
            # which has
            nothing = Attr(key, spec.label, NO_QUALIFICATION)
            left, right = left or nothing, right or nothing
            row['a'], row['b'] = left.text, right.text

        if left is None or right is None:
            row['verdict'] = 'missing'
            rows.append(row)
            continue

        score, verdict = compare_attr(spec, left, right)
        back_score, back_verdict = compare_attr(spec, right, left)

        compared += weight
        forward += weight * score
        reverse += weight * back_score

        if spec.level == 'critical':
            if key == 'package':
                package_compared = True
            else:
                critical_compared += 1

            if verdict == 'differ':
                block_forward = block_reverse = True
        elif spec.level == 'major':
            major_compared += 1

            if spec.strict and verdict == 'differ' and left.quantity and right.quantity:
                block_forward = block_reverse = True

        if verdict == 'worse':
            block_forward = True

        if back_verdict == 'worse':
            block_reverse = True

        row['verdict'] = verdict
        rows.append(row)

    # Every other parameter of either part is listed, without being compared
    for name in sorted(set(a.extras) | set(b.extras), key=str.lower):
        rows.append({
            'key': f'x:{normalise_name(name)}',
            'label': name,
            'level': 'info',
            'a': a.extras.get(name),
            'b': b.extras.get(name),
            'derived': False,
            'verdict': 'info',
        })

    if same_mpn:
        # The same manufacturer part number is the same part, whatever the
        # parameters say
        return Match(a.pk, b.pk, 100, 'both', 'mpn', 1.0, rows, same_mpn=True)

    if block_forward and block_reverse and not force:
        return None

    by_parameters = (
        critical_compared >= 1
        or major_compared >= 2
        or (package_compared and major_compared >= 1)
    )

    names = name_similarity(a, b, precise=not by_parameters)
    category = category_similarity(a, b)

    if not by_parameters:
        # Nothing but the names to go on: they have to be very alike, and
        # must not differ in a number ('M2x5' and 'M2x8', '10k' and '12k')
        if (names < NAME_ONLY_MINIMUM or a.numbers != b.numbers) and not force:
            return None

    total += NAME_WEIGHT + CATEGORY_WEIGHT
    compared += NAME_WEIGHT + CATEGORY_WEIGHT
    shared = NAME_WEIGHT * names + CATEGORY_WEIGHT * category

    coverage = compared / total if total else 0.0

    if block_forward and block_reverse:
        direction, raw = 'none', min(forward, reverse)
    elif block_forward:
        direction, raw = 'reverse', reverse
    elif block_reverse:
        direction, raw = 'forward', forward
    else:
        direction, raw = 'both', min(forward, reverse)

    score = (raw + shared) / compared if compared else 0.0
    strength = 100.0 * score * (0.55 + 0.45 * coverage)

    if not by_parameters:
        strength *= NAME_ONLY_FACTOR

    return Match(
        part=a.pk,
        other=b.pk,
        strength=max(0, min(99, round(strength))),
        direction=direction,
        basis='parameters' if by_parameters else 'name',
        coverage=round(coverage, 3),
        rows=rows,
    )


_LEVEL_ORDER = {'critical': 0, 'major': 1, 'minor': 2}


def _row_order(key: str):
    spec = spec_for(key)
    return (_LEVEL_ORDER[spec.level], 0 if key in ROLES else 1, key)


def _bucket(value: float):
    """Values within 1% of each other fall in the same or a neighbouring bucket."""
    if value <= 0:
        return 'zero' if value == 0 else None

    return round(math.log10(value) * 100)


class Catalogue:
    """All the parts, indexed so that likely matches are found without
    comparing every part with every other part."""

    def __init__(self, parts: Iterable[PartFeatures]):
        self.parts: dict[int, PartFeatures] = {part.pk: part for part in parts}
        # {(role, value bucket): {package: parts}}
        self._values: dict = defaultdict(dict)
        self._categories: dict = defaultdict(set)
        self._tokens: dict = defaultdict(set)
        self._mpns: dict = defaultdict(set)

        for part in self.parts.values():
            for mpn in part.mpns:
                self._mpns[mpn].add(part.pk)

            keys = self._value_keys(part)
            package = self._package(part)

            for key in keys:
                self._values[key].setdefault(package, set()).add(part.pk)

            if not keys:
                if part.category is not None:
                    self._categories[part.category].add(part.pk)

                for token in part.tokens:
                    self._tokens[token].add(part.pk)

    @staticmethod
    def _value_keys(part: PartFeatures) -> list:
        keys = []

        for role in _VALUE_ROLES:
            attr = part.attrs.get(role)

            if attr and attr.quantity:
                bucket = _bucket(attr.quantity.value)

                if bucket is not None:
                    keys.append((role, bucket))

        return keys

    @staticmethod
    def _package(part: PartFeatures) -> str:
        attr = part.attrs.get('package')

        return attr.norm if attr else ''

    def _same_value(self, key, package: str) -> set:
        """Parts with this value, in this package or with no package given."""
        groups = self._values.get(key)

        if not groups:
            return set()

        if not package:
            return set().union(*groups.values())

        return groups.get(package, set()) | groups.get('', set())

    def _mates(self, part: PartFeatures, limit: int = MAX_GROUP) -> set:
        """Parts worth comparing with this one."""
        mates: set = set()

        for mpn in part.mpns:
            mates |= self._mpns[mpn]

        keys = self._value_keys(part)
        package = self._package(part)

        for role, bucket in keys:
            if bucket == 'zero':
                mates |= self._same_value((role, bucket), package)
                continue

            for near in (bucket - 1, bucket, bucket + 1):
                mates |= self._same_value((role, near), package)

        if not keys:
            group = self._categories.get(part.category, set())

            if len(group) <= limit:
                mates |= group

            # Parts in other categories which share an uncommon word
            for token in part.tokens:
                group = self._tokens.get(token, set())

                if len(token) > 2 and len(group) <= 40:
                    mates |= group

        mates.discard(part.pk)

        return mates

    def match(self, part: int, other: int) -> Optional[Match]:
        """Compare two parts by their keys."""
        a, b = self.parts.get(part), self.parts.get(other)

        return compare(a, b) if a and b else None

    def candidates(self, pk: int, minimum: int = 0, limit: int = 50, exclude: Iterable[int] = ()) -> list[Match]:
        """Parts which could replace this part or be replaced by it, strongest first."""
        part = self.parts.get(pk)

        if part is None:
            return []

        skip = set(exclude)
        found = []

        for other in self._mates(part, limit=5 * MAX_GROUP):
            if other in skip:
                continue

            match = compare(part, self.parts[other])

            if match and match.strength >= minimum:
                found.append(match)

        found.sort(key=_rank)

        return found[:limit]

    def pairs(self, minimum: int = 0, limit: int = 200, exclude: Iterable[tuple] = ()) -> list[Match]:
        """The strongest matches across the whole catalogue, each pair once."""
        skip = {tuple(sorted(pair)) for pair in exclude}
        found = []

        for part in self.parts.values():
            for other in self._mates(part):
                if other <= part.pk or (part.pk, other) in skip:
                    continue

                match = compare(part, self.parts[other])

                if match and match.strength >= minimum:
                    found.append(match)

        found.sort(key=_rank)

        return found[:limit]

    def duplicates(self) -> list[tuple[str, list[int]]]:
        """Manufacturer part numbers which are held under more than one part."""
        return sorted(
            (mpn, sorted(parts)) for mpn, parts in self._mpns.items() if len(parts) > 1
        )


def _rank(match: Match):
    return (-match.strength, match.direction != 'both', -match.coverage, match.part, match.other)
