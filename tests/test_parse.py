"""Reading values, packages and attributes out of text."""

import math

import pytest

from inventree_apns.parse import (
    derive_attributes,
    normalise_dielectric,
    normalise_package,
    parse_qualification,
    parse_quantity,
    parse_temperature_range,
)


@pytest.mark.parametrize(
    'text, value, unit',
    [
        ('100nF', 100e-9, 'F'),
        ('0.1 uF', 100e-9, 'F'),
        ('0.1µF', 100e-9, 'F'),
        ('0.1 μF', 100e-9, 'F'),
        ('4k7', 4700, ''),
        ('4R7', 4.7, 'Ω'),
        ('0R', 0, 'Ω'),
        ('10K', 10e3, ''),
        ('10 kOhm', 10e3, 'Ω'),
        ('10 kΩ', 10e3, 'Ω'),
        ('1 MOhm', 1e6, 'Ω'),
        ('1mOhm', 1e-3, 'Ω'),
        ('16V', 16, 'V'),
        ('16 VDC', 16, 'V'),
        ('±10%', 10, '%'),
        ('+/-5%', 5, '%'),
        ('1/16W', 0.0625, 'W'),
        ('100mW', 0.1, 'W'),
        ('2.2uH', 2.2e-6, 'H'),
        ('32.768kHz', 32768, 'Hz'),
        ('50ppm', 50, 'ppm'),
        ('1F', 1, 'F'),
        ('1,5 A', 1.5, 'A'),
        ('2n2', 2.2e-9, ''),
        ('-40°C', -40, '°C'),
        ('0.063W, 1/16W', 0.063, 'W'),
    ],
)
def test_parse_quantity(text, value, unit):
    quantity = parse_quantity(text)

    assert quantity is not None
    assert math.isclose(quantity.value, value, rel_tol=1e-9, abs_tol=1e-18)
    assert quantity.unit == unit


@pytest.mark.parametrize(
    'text',
    ['', None, 'abc', 'X7R', '-40°C ~ 85°C', 'Surface Mount', '3 x 4', '1N4148', '2N7002', '4N35', '2N3904', '2P2', '4k7501'],
)
def test_not_a_quantity(text):
    assert parse_quantity(text) is None


def test_part_numbers_in_a_description_are_not_values():
    # These used to raise an error, which stopped every part from loading
    assert derive_attributes('1N4148 switching diode SOD-123') == {'package': 'SOD-123'}
    assert derive_attributes('MOSFET 2N7002 N-channel 60V SOT-23') == {'package': 'SOT-23', 'voltage': '60V'}
    assert derive_attributes('MMBT3904 2N3904 NPN') == {}


def test_template_unit_is_used_when_the_text_has_none():
    def same(left, right):
        return left.unit == right.unit and math.isclose(left.value, right.value, rel_tol=1e-9)

    assert same(parse_quantity('100', 'nF'), parse_quantity('100nF'))
    assert same(parse_quantity('10k', 'Ω'), parse_quantity('10kΩ'))
    assert same(parse_quantity(4.7, 'kΩ'), parse_quantity('4700 ohm'))
    # A unit in the text wins over the template unit
    assert same(parse_quantity('0.1uF', 'nF'), parse_quantity('100nF'))


@pytest.mark.parametrize(
    'text, package',
    [
        ('0402', '0402'),
        ('0402 (1005 Metric)', '0402'),
        ('1206 (3216 Metric)', '1206'),
        ('SOT23-5', 'SOT-23-5'),
        ('SOT-23-5', 'SOT-23-5'),
        ('sot-23', 'SOT-23'),
        ('SOT-23-3', 'SOT-23'),
        ('SOIC8', 'SOIC-8'),
        ('8-SOIC (0.154", 3.90mm Width)', 'SOIC-8'),
        ('SOD123', 'SOD-123'),
        ('LQFP-48 (7x7)', 'LQFP-48'),
        ('TO-252-3', 'DPAK'),
    ],
)
def test_normalise_package(text, package):
    assert normalise_package(text) == package


def test_normalise_dielectric():
    assert normalise_dielectric('X7R') == 'X7R'
    assert normalise_dielectric('C0G, NP0') == 'C0G'
    assert normalise_dielectric('NP0') == 'C0G'
    assert normalise_dielectric('npo') == 'C0G'
    assert normalise_dielectric('±100ppm/°C') == ''


def test_derive_attributes_capacitor():
    assert derive_attributes('CAP CER 100nF 16V X7R 0402 10%') == {
        'dielectric': 'X7R',
        'package': '0402',
        'capacitance': '100nF',
        'voltage': '16V',
        'tolerance': '10%',
    }
    # A space between the number and the unit
    assert derive_attributes('Capacitor', '0.1 uF 50 V C0G 0603')['capacitance'] == '0.1uF'


def test_derive_attributes_resistor():
    assert derive_attributes('RES 10K 1% 0402 1/16W') == {
        'package': '0402',
        'resistance': '10K',
        'tolerance': '1%',
        'power': '1/16W',
    }
    assert derive_attributes('0R 0402 jumper')['resistance'] == '0R'
    assert derive_attributes('Resistor 4k7 0603')['resistance'] == '4k7'


def test_derive_attributes_leaves_plain_numbers_alone():
    assert derive_attributes('Screw M2x5 Phillips') == {}
    assert derive_attributes('Header 2x10 2.54 pitch') == {}
    assert derive_attributes('', None) == {}


def test_parse_qualification():
    assert parse_qualification('AEC-Q200') == (frozenset({'AEC-Q200', 'AUTOMOTIVE'}), None)
    assert parse_qualification('aec q200') == (frozenset({'AEC-Q200', 'AUTOMOTIVE'}), None)
    assert parse_qualification('Automotive, AEC-Q100 Grade 1') == (frozenset({'AEC-Q100', 'AUTOMOTIVE'}), 1)
    assert parse_qualification('Automotive') == (frozenset({'AUTOMOTIVE'}), None)
    assert parse_qualification('MIL-PRF-55342') == (frozenset({'MIL-PRF-55342'}), None)
    # A parameter named for the qualification, with a yes/no value
    assert parse_qualification('Yes', 'AEC-Q200') == (frozenset({'AEC-Q200', 'AUTOMOTIVE'}), None)
    assert parse_qualification('No', 'AEC-Q200') == (frozenset(), None)

    for nothing in ('', '-', 'Commercial', 'Standard', None):
        assert parse_qualification(nothing) == (frozenset(), None)


def test_parse_temperature_range():
    assert parse_temperature_range('-55°C ~ 125°C') == (-55, 125)
    assert parse_temperature_range('-40 to +85 °C') == (-40, 85)
    assert parse_temperature_range('0°C ~ 70°C (TA)') == (0, 70)
    assert parse_temperature_range('-40°C...+105°C') == (-40, 105)
    assert parse_temperature_range('−55 ~ 155') == (-55, 155)
    assert parse_temperature_range('125°C') is None
    assert parse_temperature_range('Surface Mount') is None


def test_derive_attributes_qualification():
    assert derive_attributes('CAP 100nF 50V X7R 0603 AEC-Q200')['qualification'] == 'AEC-Q200'
    assert derive_attributes('LDO 3.3V automotive AEC-Q100 grade 1')['qualification'] == 'AEC-Q100 Grade 1'
    # The word alone is too loose to read out of a description
    assert 'qualification' not in derive_attributes('Automotive connector 2 pin')


def test_nothing_in_a_part_name_raises_an_error():
    """Whatever is typed into a name, description or parameter must be survived."""
    import random

    from inventree_apns.matching import Catalogue, build_features, compare

    random.seed(1123)
    alphabet = list('0123456789') * 3 + list('RrkKMmuUnNpPfFVvAaWwHhzZΩµμ%±+-/.,~° ()[]:;xXABCDEFGabcdefg')
    words = ['1N4148', '2N7002', '4N35', '0402', 'SOT-23', 'X7R', 'AEC-Q200', '100nF', '4k7', '±5%', '16V', '1/16W',
             '-40°C ~ 85°C', '1/0W', '1e999', '10P', '100N', '4U7', '1,00,0', '8-', 'R0', '', '-', 'N/A']
    names = ['Capacitance', 'Resistance', 'Value', 'Package', 'Tolerance', 'Voltage Rating', 'Dielectric',
             'Temperature Coefficient', 'Qualification', 'Operating Temperature', 'Voltage - Output', 'Series', '']
    units = ['', 'F', 'nF', 'ohm', 'kΩ', 'V', '%', 'bogus', 'm', 'M']

    def text():
        if random.random() < 0.4:
            return random.choice(words)
        return ' '.join(
            random.choice(words + [''.join(random.choice(alphabet) for _ in range(random.randint(1, 9)))])
            for _ in range(random.randint(1, 5))
        )

    parts = []

    for pk in range(1, 301):
        parameters = [
            {
                'name': random.choice(names),
                'data': random.choice([text(), None, 5, 1.5]),
                'units': random.choice(units),
                'numeric': random.choice([None, 1.0, float('nan'), float('inf')]),
            }
            for _ in range(random.randint(0, 6))
        ]
        parts.append(
            build_features(pk, name=text(), description=text(), category=pk % 3, mpns=[text()], parameters=parameters)
        )
        parse_quantity(text(), random.choice(units))

    for index, first in enumerate(parts):
        for second in parts[index + 1 : index + 40]:
            for strict in (False, True):
                match = compare(first, second, force=True, strict_qualification=strict)
                match.flipped()

    catalogue = Catalogue(parts)
    catalogue.pairs(limit=50)
    catalogue.candidates(1)
