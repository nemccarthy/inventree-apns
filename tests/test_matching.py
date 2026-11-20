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
    return {row['key']: row['verdict'] for row in match.rows if row['verdict'] != 'info'}


def test_parameter_names_map_to_roles():
    assert role_for('Capacitance') == 'capacitance'
    assert role_for('Package / Case') == 'package'
    assert role_for('Supplier Device Package') == 'package'
    assert role_for('Voltage - Rated') == 'voltage'
    assert role_for('Voltage Rating (DC)') == 'voltage'
    assert role_for('Power (Watts)') == 'power'
    assert role_for('Temperature Coefficient') == 'dielectric'
    assert role_for('Tolerance') == 'tolerance'
    assert role_for('Qualification') == 'qualification'
    assert role_for('Ratings') == 'qualification'
    assert role_for('Grade') == 'qualification'
    assert role_for('AEC-Q200') == 'qualification'
    assert role_for('Operating Temperature') == 'temperature'
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


def test_every_parameter_is_listed_in_the_comparison():
    one = cap(1, RoHS_Status='Compliant', Series='CL', Supplier_Device_Package='0402')
    two = cap(2, RoHS_Status='Compliant', Height='0.5mm')
    match = compare(one, two)
    shown = {row['label']: (row['a'], row['b']) for row in match.rows if row['verdict'] == 'info'}

    assert shown == {
        'Height': (None, '0.5mm'),
        'RoHS Status': ('Compliant', 'Compliant'),
        'Series': ('CL', None),
        # A second parameter for the package: listed, not compared twice
        'Supplier Device Package': ('0402', None),
    }
    # Listing them does not change the match
    assert match.strength == compare(cap(1), cap(2)).strength
    assert match.direction == 'both'
    # They come after the compared attributes, and flip with the rest
    assert [row['verdict'] for row in match.rows][-4:] == ['info'] * 4
    assert {row['label']: (row['a'], row['b']) for row in match.flipped().rows}['Series'] == (None, 'CL')


def test_a_different_qualification_lowers_the_strength_and_keeps_the_direction():
    plain, twin, automotive = cap(1), cap(3), cap(2, Qualification='AEC-Q200')
    match = compare(plain, automotive)

    # Still interchangeable, as far as the matching goes, but a weaker match
    assert match.direction == 'both'
    assert match.strength < compare(plain, twin).strength - 3
    row = next(row for row in match.rows if row['key'] == 'qualification')
    assert (row['a'], row['b'], row['verdict']) == ('None stated', 'AEC-Q200', 'better')

    back = compare(automotive, plain)
    assert back.direction == 'both'
    assert back.strength == match.strength
    assert verdicts(back)['qualification'] == 'worse'


def test_qualification_does_not_change_a_direction_set_by_a_rating():
    # The 50 V part can replace the 16 V one, whichever of them is qualified
    assert compare(cap(1), cap(2, voltage='50V', Qualification='AEC-Q200')).direction == 'forward'
    assert compare(cap(1, Qualification='AEC-Q200'), cap(2, voltage='50V')).direction == 'forward'
    assert compare(cap(1, voltage='50V'), cap(2, voltage='16V', Qualification='AEC-Q200')).direction == 'reverse'


def test_held_to_strictly_a_qualified_part_replaces_an_unqualified_one():
    plain, automotive = cap(1), cap(2, Qualification='AEC-Q200')
    match = compare(plain, automotive, strict_qualification=True)

    assert match.direction == 'forward'
    assert verdicts(match)['qualification'] == 'better'
    # And not the reverse
    back = compare(automotive, plain, strict_qualification=True)
    assert back.direction == 'reverse'
    assert verdicts(back)['qualification'] == 'worse'
    # AEC-Q200 but a lower voltage rating: neither can replace the other
    assert compare(cap(1, voltage='50V'), cap(2, voltage='16V', Qualification='AEC-Q200'), strict_qualification=True) is None

    catalogue = Catalogue([plain, automotive], strict_qualification=True)
    assert catalogue.candidates(1)[0].direction == 'forward'
    assert Catalogue([plain, automotive]).candidates(1)[0].direction == 'both'


def test_the_same_qualification_is_interchangeable():
    match = compare(cap(1, Ratings='AEC-Q200'), cap(2, Qualification='aec q200'))

    assert match.direction == 'both'
    assert verdicts(match)['qualification'] == 'match'
    assert match.strength > compare(cap(1), cap(2, Qualification='AEC-Q200')).strength
    # Parts which state none are not affected
    assert 'qualification' not in verdicts(compare(cap(1), cap(2)))


def test_a_value_which_claims_nothing_is_no_qualification():
    match = compare(cap(1, Grade='-'), cap(2, Qualification='Commercial'))

    assert match.direction == 'both'
    assert 'qualification' not in verdicts(match)


def test_aec_q100_grades():
    def ic(pk, grade):
        return part(pk, name='LDO 3.3V', Package='SOT-23-5', Voltage___Output='3.3V', Qualification=grade)

    same = compare(ic(1, 'AEC-Q100 Grade 1'), ic(2, 'AEC-Q100 Grade 1'))
    assert same.direction == 'both'
    assert verdicts(same)['qualification'] == 'match'

    # A different grade is a weaker match
    other = compare(ic(1, 'AEC-Q100 Grade 2'), ic(2, 'AEC-Q100 Grade 1'))
    assert other.direction == 'both'
    assert other.strength < same.strength
    assert verdicts(other)['qualification'] == 'better'

    # Held to strictly: grade 1 (-40 to 125) can replace grade 2 (-40 to
    # 105), and an AEC part one which is only marked automotive
    assert compare(ic(1, 'AEC-Q100 Grade 2'), ic(2, 'AEC-Q100 Grade 1'), strict_qualification=True).direction == 'forward'
    assert compare(ic(1, 'AEC-Q100 Grade 1'), ic(2, 'AEC-Q100 Grade 2'), strict_qualification=True).direction == 'reverse'
    assert compare(ic(1, 'Automotive'), ic(2, 'AEC-Q100'), strict_qualification=True).direction == 'forward'


def test_qualification_is_read_from_the_description():
    described = part(1, name='CAP 100nF 16V X7R 0402 10% AEC-Q200')

    assert described.attrs['qualification'].derived
    assert verdicts(compare(cap(2), described))['qualification'] == 'better'
    assert compare(cap(2), described, strict_qualification=True).direction == 'forward'


def test_a_wider_temperature_range_can_replace_a_narrower_one():
    narrow = cap(1, Operating_Temperature='-40°C ~ 85°C')
    wide = cap(2, Operating_Temperature='-55°C ~ 125°C')

    match = compare(narrow, wide)
    assert match.direction == 'forward'
    assert verdicts(match)['temperature'] == 'better'
    assert compare(wide, narrow).direction == 'reverse'
    assert compare(wide, cap(3, Operating_Temperature='-55 to +125 °C')).direction == 'both'

    # Neither range covers the other
    assert compare(cap(1, Operating_Temperature='-40°C ~ 105°C'), cap(2, Operating_Temperature='-25°C ~ 125°C')) is None

    # An unknown range is unknown, not a failure
    unknown = compare(wide, cap(4))
    assert unknown.direction == 'both'
    assert verdicts(unknown)['temperature'] == 'missing'
