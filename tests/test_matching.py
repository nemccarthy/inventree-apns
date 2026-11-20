"""Matching parts by their attributes."""

from inventree_apns.matching import Catalogue, build_features, compare, role_for


def part(pk, name='', description='', category=1, mpns=(), **params):
    """A part whose keyword arguments are parameters: Capacitance='100nF'."""
    parameters = [
        {'name': key.replace('_', ' '), 'data': value, 'units': '', 'numeric': None}
        for key, value in params.items()
    ]

    return build_features(
        pk, name=name, description=description, category=category, mpns=mpns, parameters=parameters
    )


def cap(pk, value='100nF', package='0402', voltage='16V', tolerance='10%', dielectric='X7R', **kwargs):
    return part(
        pk,
        name=kwargs.pop('name', f'CAP {value} {package}'),
        Capacitance=value,
        Package=package,
        Voltage_Rating=voltage,
        Tolerance=tolerance,
        Dielectric=dielectric,
        **kwargs,
    )


def verdicts(match):
    return {row['key']: row['verdict'] for row in match.rows}


def test_parameter_names_map_to_roles():
    assert role_for('Capacitance') == 'capacitance'
    assert role_for('Package / Case') == 'package'
    assert role_for('Supplier Device Package') == 'package'
    assert role_for('Voltage - Rated') == 'voltage'
    assert role_for('Voltage Rating (DC)') == 'voltage'
    assert role_for('Power (Watts)') == 'power'
    assert role_for('Temperature Coefficient') == 'dielectric'
    assert role_for('Tolerance') == 'tolerance'
    # Not a rating: has to be compared as it is
    assert role_for('Voltage - Output') == 'p:voltage output'
    # Says nothing about interchangeability
    assert role_for('RoHS Status') is None
    assert role_for('Packaging') is None
    assert role_for('Series') is None


def test_identical_parts_are_interchangeable():
    match = compare(cap(1), cap(2))

    assert match.direction == 'both'
    assert match.basis == 'parameters'
    assert match.strength >= 95
    assert set(verdicts(match).values()) == {'match'}


def test_values_are_compared_whatever_the_notation():
    match = compare(cap(1, value='100nF'), cap(2, value='0.1 µF', package='0402 (1005 Metric)'))

    assert match.direction == 'both'
    assert verdicts(match)['capacitance'] == 'match'
    assert verdicts(match)['package'] == 'match'


def test_a_different_value_or_package_is_not_an_alternate():
    assert compare(cap(1), cap(2, value='220nF')) is None
    assert compare(cap(1), cap(2, package='0603')) is None


def test_a_better_part_is_a_one_way_alternate():
    loose, tight = cap(1, tolerance='10%', voltage='16V'), cap(2, tolerance='5%', voltage='50V')
    match = compare(loose, tight)

    # The tighter, higher-rated part can replace the other, not the reverse
    assert match.direction == 'forward'
    assert verdicts(match)['tolerance'] == 'better'
    assert verdicts(match)['voltage'] == 'better'

    back = compare(tight, loose)

    assert back.direction == 'reverse'
    assert verdicts(back)['voltage'] == 'worse'


def test_flipped_match_reads_from_the_other_part():
    match = compare(cap(1, voltage='16V'), cap(2, voltage='50V'))
    flipped = match.flipped()

    assert (flipped.part, flipped.other) == (2, 1)
    assert flipped.direction == 'reverse'
    assert verdicts(flipped)['voltage'] == 'worse'
    assert flipped.strength == match.strength


def test_better_one_way_and_worse_the_other_is_no_alternate():
    # Higher voltage but looser tolerance: neither can replace the other
    assert compare(cap(1, voltage='16V', tolerance='5%'), cap(2, voltage='50V', tolerance='10%')) is None


def test_a_different_dielectric_lowers_the_strength():
    same = compare(cap(1), cap(2))
    other = compare(cap(1), cap(2, dielectric='Y5V'))

    assert other is not None
    assert other.strength < same.strength - 5
    assert verdicts(other)['dielectric'] == 'differ'


def test_missing_parameters_lower_the_strength():
    full = compare(cap(1), cap(2))
    sparse = compare(cap(1), part(2, name='CAP 100nF 0402', Capacitance='100nF', Package='0402'))

    assert sparse.direction == 'both'
    assert sparse.strength < full.strength
    assert sparse.coverage < full.coverage
    assert verdicts(sparse)['voltage'] == 'missing'


def test_attributes_are_read_from_the_description():
    bare = part(1, name='CAP CER 100nF 16V X7R 0402 10%')
    match = compare(bare, cap(2))

    assert match is not None
    assert match.direction == 'both'
    assert verdicts(match)['capacitance'] == 'match'
    assert all(row['derived'] for row in match.rows)
    # Counts for less than a match on real parameters
    assert match.strength < compare(cap(1), cap(2)).strength


def test_parameters_win_over_the_description():
    labelled = part(1, name='CAP 220nF 0402', Capacitance='100nF', Package='0402')

    assert labelled.attrs['capacitance'].text == '100nF'
    assert not labelled.attrs['capacitance'].derived


def test_same_mpn_is_a_duplicate():
    match = compare(
        cap(1, mpns=['GRM155R71C104KA88D']),
        part(2, name='something else', mpns=['grm155r71c104ka88d ']),
    )

    assert match.same_mpn
    assert match.strength == 100
    assert match.basis == 'mpn'


def test_name_only_matches_need_the_same_numbers():
    assert compare(part(1, name='Screw M2x5 Phillips pan'), part(2, name='Screw M2x8 Phillips pan')) is None

    match = compare(
        part(1, name='Membrane vent adhesive IP67'), part(2, name='Membrane vent adhesive IP67 black')
    )

    assert match is not None
    assert match.basis == 'name'
    assert match.strength < 80


def test_unrelated_parts_do_not_match():
    assert compare(part(1, name='USB-C receptacle 16 pin'), part(2, name='Crystal 32.768kHz')) is None


def test_other_parameters_have_to_agree():
    ldo33 = part(1, name='LDO 3.3V', Package='SOT-23-5', Voltage___Output='3.3V', Current___Output='500mA')
    ldo50 = part(2, name='LDO 5.0V', Package='SOT-23-5', Voltage___Output='5V', Current___Output='500mA')
    twin = part(3, name='LDO 3.3V', Package='SOT23-5', Voltage___Output='3.3 V', Current___Output='0.5A')

    assert compare(ldo33, twin).direction == 'both'
    # A different output voltage rules it out
    assert compare(ldo33, ldo50) is None
    assert compare(ldo33, ldo50, force=True).direction == 'none'


def test_ratings_are_not_read_from_the_description_of_other_parts():
    # '3.3V' and '5V' are output voltages here, not ratings to be exceeded
    ldo33 = part(1, name='LDO 3.3V 500mA SOT-23-5', description='LDO regulator 3.3V 500mA')
    ldo50 = part(2, name='LDO 5.0V 500mA SOT-23-5', description='LDO regulator 5V 500mA')

    assert set(ldo33.attrs) == {'package'}
    assert compare(ldo33, ldo50) is None


def test_the_same_package_alone_is_not_a_match():
    assert compare(part(1, name='Op amp', Package='SOIC-8'), part(2, name='EEPROM', Package='SOIC-8')) is None


def test_exact_matches_rank_above_better_parts():
    catalogue = Catalogue([cap(1), cap(3, voltage='50V'), cap(2)])

    assert [match.other for match in catalogue.candidates(1)] == [2, 3]


def test_catalogue_ranks_candidates():
    catalogue = Catalogue([
        cap(1),
        cap(2),  # the same
        cap(3, voltage='50V'),  # better
        cap(4, dielectric='Y5V'),  # weaker match
        cap(5, value='1uF'),  # different value
        cap(6, package='0603'),  # different package
        part(7, name='RES 10k 0402', Resistance='10k', Package='0402'),
    ])

    found = catalogue.candidates(1)

    assert [match.other for match in found] == [2, 3, 4]
    assert found[0].direction == 'both'
    assert found[1].direction == 'forward'
    assert found[0].strength >= found[1].strength >= found[2].strength

    assert [match.other for match in catalogue.candidates(1, minimum=found[2].strength + 1)] == [2, 3]
    assert [match.other for match in catalogue.candidates(1, exclude=[2])] == [3, 4]
    assert catalogue.candidates(99) == []


def test_catalogue_pairs_lists_each_pair_once():
    catalogue = Catalogue([cap(1), cap(2), cap(3, voltage='50V'), cap(5, value='1uF')])
    pairs = catalogue.pairs()

    assert sorted((match.part, match.other) for match in pairs) == [(1, 2), (1, 3), (2, 3)]
    assert catalogue.pairs(exclude=[(2, 1)])[0].part != 1 or catalogue.pairs(exclude=[(2, 1)])[0].other != 2


def test_catalogue_duplicates():
    catalogue = Catalogue([
        cap(1, mpns=['ABC-123']),
        cap(2, value='1uF', mpns=['abc123']),
        cap(3, mpns=['XYZ']),
    ])

    assert catalogue.duplicates() == [('ABC123', [1, 2])]
    # Found as a candidate although the parameters differ
    assert catalogue.candidates(1)[0].other == 2
    assert catalogue.candidates(1)[0].same_mpn


def test_resistors_with_a_tighter_tolerance():
    one = part(1, name='RES 10k 1% 0402', Resistance='10k', Package='0402', Tolerance='1%', Power='1/16W')
    five = part(2, name='RES 10k 5% 0402', Resistance='10 kOhm', Package='0402', Tolerance='5%', Power='0.063W')
    match = compare(five, one)

    assert match.direction == 'forward'
    assert verdicts(match)['resistance'] == 'match'
    assert verdicts(match)['power'] == 'match'
