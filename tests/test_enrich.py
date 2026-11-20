"""Turning values found at a supplier into InvenTree parameters."""

from inventree_apns.enrich import (
    clean_value,
    description_source,
    digikey_numbers,
    find_template,
    format_quantity,
    lcsc_numbers,
    map_parameters,
    parse_digikey,
    parse_lcsc,
)
from inventree_apns.matching import role_for
from inventree_apns.parse import Quantity


def template(pk, name, units='', **extra):
    return {'pk': pk, 'name': name, 'units': units, 'checkbox': False, 'choices': False, 'role': role_for(name), **extra}


TEMPLATES = [
    template(1, 'Capacitance', 'F'),
    template(2, 'Package'),
    template(3, 'Voltage Rating', 'V'),
    template(4, 'Tolerance', '%'),
    template(5, 'Dielectric'),
    template(6, 'Mounting Type', choices=True),
]


def test_format_quantity():
    assert format_quantity(Quantity(100e-9, 'F')) == '100 nF'
    assert format_quantity(Quantity(4.7e-6, 'F')) == '4.7 µF'
    # Capacitors are not given in millifarads
    assert format_quantity(Quantity(2.2e-3, 'F')) == '2200 µF'
    assert format_quantity(Quantity(10e3, 'Ω')) == '10 kΩ'
    assert format_quantity(Quantity(0, 'Ω')) == '0 Ω'
    assert format_quantity(Quantity(0.0625, 'W')) == '62.5 mW'
    assert format_quantity(Quantity(10, '%')) == '10 %'
    assert format_quantity(Quantity(32768, 'Hz')) == '32.768 kHz'


def test_clean_value_for_a_template_with_units():
    assert clean_value('0.1 µF', 'capacitance', 'F') == '100 nF'
    assert clean_value('±10%', 'tolerance', '%') == '10 %'
    assert clean_value('16V', 'voltage', 'V') == '16 V'
    # Not a value in that unit
    assert clean_value('±0.25pF', 'tolerance', '%') is None
    assert clean_value('X7R', 'capacitance', 'F') is None


def test_clean_value_for_a_template_without_units():
    assert clean_value('0402 (1005 Metric)', 'package') == '0402 (1005 Metric)'
    assert clean_value('C0G, NP0', 'dielectric') == 'C0G'
    assert clean_value('0.1uF', 'capacitance') == '100 nF'
    assert clean_value('  -40°C ~ 125°C ', None) == '-40°C ~ 125°C'
    assert clean_value('-', 'package') is None
    assert clean_value('', None) is None


def test_find_template_by_name_and_by_meaning():
    assert find_template('Capacitance', 'capacitance', TEMPLATES)['pk'] == 1
    # DigiKey's names for the same things
    assert find_template('Package / Case', 'package', TEMPLATES)['pk'] == 2
    assert find_template('Voltage - Rated', 'voltage', TEMPLATES)['pk'] == 3
    assert find_template('Temperature Coefficient', 'dielectric', TEMPLATES)['pk'] == 5
    # A template with fixed choices is never filled in
    assert find_template('Mounting Type', 'mounting', TEMPLATES) is None
    assert find_template('Operating Temperature', role_for('Operating Temperature'), TEMPLATES) is None


def test_map_parameters_adds_keeps_and_creates():
    found = [
        {'name': 'Capacitance', 'value': '0.1 µF', 'source': 'digikey'},
        {'name': 'Voltage - Rated', 'value': '16V', 'source': 'digikey'},
        {'name': 'Package / Case', 'value': '0402 (1005 Metric)', 'source': 'digikey'},
        {'name': 'Operating Temperature', 'value': '-55°C ~ 125°C', 'source': 'digikey'},
        {'name': 'Tolerance', 'value': '±0.25pF', 'source': 'digikey'},
        {'name': 'RoHS Status', 'value': 'ROHS3 Compliant', 'source': 'digikey'},
        # A second source for something already found is left out
        {'name': 'Capacitance', 'value': '100nF', 'source': 'description'},
    ]

    proposals = {item['template_name']: item for item in map_parameters(found, TEMPLATES, existing={2: '0402'})}

    assert proposals['Capacitance']['action'] == 'add'
    assert proposals['Capacitance']['value'] == '100 nF'
    assert proposals['Capacitance']['source'] == 'digikey'
    assert proposals['Voltage Rating']['value'] == '16 V'
    assert proposals['Package']['action'] == 'keep'
    assert proposals['Package']['current'] == '0402'
    assert proposals['Operating Temperature']['action'] == 'create'
    assert proposals['Operating Temperature']['units'] == ''
    assert proposals['Tolerance']['action'] == 'skip'
    assert 'RoHS Status' not in proposals
    assert len(proposals) == 5


def test_map_parameters_without_creating_templates():
    found = [{'name': 'Operating Temperature', 'value': '-55°C ~ 125°C', 'source': 'digikey'}]

    assert map_parameters(found, TEMPLATES, {}, create=False)[0]['action'] == 'skip'


def test_new_templates_for_known_attributes_get_a_unit():
    found = [
        {'name': 'Resistance', 'value': '10 kOhms', 'source': 'digikey'},
        {'name': 'Power (Watts)', 'value': '0.063W, 1/16W', 'source': 'digikey'},
    ]
    proposals = map_parameters(found, [], {})

    assert (proposals[0]['action'], proposals[0]['template_name'], proposals[0]['units'], proposals[0]['value']) == (
        'create',
        'Resistance',
        'ohm',
        '10 kΩ',
    )
    # The same value given twice: the first is used
    assert (proposals[1]['template_name'], proposals[1]['units'], proposals[1]['value']) == ('Power rating', 'W', '63 mW')


def test_a_value_goes_to_the_template_the_part_already_uses():
    templates = [template(7, 'Case'), template(2, 'Package')]
    found = [{'name': 'Package', 'value': '0402', 'source': 'lcsc'}]

    assert map_parameters(found, templates, existing={7: '0402'})[0]['action'] == 'add'
    assert map_parameters(found, [template(7, 'Case')], existing={7: '0402'})[0]['action'] == 'keep'


def test_parse_digikey_product_details():
    payload = {
        'Product': {
            'Description': {'ProductDescription': 'CAP CER 0.1UF 16V X7R 0402'},
            'Manufacturer': {'Id': 399, 'Name': 'KEMET'},
            'ManufacturerProductNumber': 'C0402C104K4RACTU',
            'ProductUrl': 'https://www.digikey.com/en/products/detail/x/1',
            'Parameters': [
                {'ParameterId': 2049, 'ParameterText': 'Capacitance', 'ValueText': '0.1 µF'},
                {'ParameterId': 3, 'ParameterText': 'Tolerance', 'ValueText': '±10%'},
                {'ParameterId': 14, 'ParameterText': 'Voltage - Rated', 'ValueText': '16V'},
                {'ParameterId': 17, 'ParameterText': 'Temperature Coefficient', 'ValueText': 'X7R'},
                {'ParameterId': 16, 'ParameterText': 'Package / Case', 'ValueText': '0402 (1005 Metric)'},
                {'ParameterId': 5, 'ParameterText': 'Features', 'ValueText': '-'},
            ],
        }
    }
    result = parse_digikey(payload, 'C0402C104K4RACTU')

    assert result['mpn'] == 'C0402C104K4RACTU'
    assert result['manufacturer'] == 'KEMET'
    assert [item['name'] for item in result['parameters']] == [
        'Capacitance',
        'Tolerance',
        'Voltage - Rated',
        'Temperature Coefficient',
        'Package / Case',
    ]

    proposals = {item['template_name']: item['value'] for item in map_parameters(result['parameters'], TEMPLATES, {})}

    assert proposals == {
        'Capacitance': '100 nF',
        'Tolerance': '10 %',
        'Voltage Rating': '16 V',
        'Dielectric': 'X7R',
        'Package': '0402 (1005 Metric)',
    }

    assert parse_digikey({}, 'x') is None
    assert parse_digikey({'Product': None}, 'x') is None


def test_parse_lcsc_product_detail():
    payload = {
        'code': 200,
        'result': {
            'productCode': 'C1525',
            'productModel': 'CL05B104KO5NNNC',
            'brandNameEn': 'Samsung Electro-Mechanics',
            'encapStandard': '0402',
            'productIntroEn': '16V 100nF X7R ±10% 0402 MLCC',
            'paramVOList': [
                {'paramNameEn': 'Capacitance', 'paramValueEn': '100nF'},
                {'paramNameEn': 'Voltage Rated', 'paramValueEn': '16V'},
                {'paramNameEn': 'Tolerance', 'paramValueEn': '±10%'},
                {'paramNameEn': 'Temperature Coefficient', 'paramValueEn': 'X7R'},
                {'paramNameEn': 'Something', 'paramValueEn': '-'},
            ],
        },
    }
    result = parse_lcsc(payload, 'C1525')

    assert result['mpn'] == 'CL05B104KO5NNNC'
    assert result['parameters'][0] == {'name': 'Package', 'value': '0402', 'source': 'lcsc'}

    proposals = {item['template_name']: item['value'] for item in map_parameters(result['parameters'], TEMPLATES, {})}

    assert proposals == {
        'Package': '0402',
        'Capacitance': '100 nF',
        'Voltage Rating': '16 V',
        'Tolerance': '10 %',
        'Dielectric': 'X7R',
    }

    assert parse_lcsc({'code': 200, 'result': {}}, 'C1') is None
    assert parse_lcsc({'code': 500}, 'C1') is None


def test_numbers_to_look_up():
    skus = [
        {'supplier': 'LCSC', 'sku': 'C1525'},
        {'supplier': 'JLCPCB', 'sku': 'c25804'},
        {'supplier': 'DigiKey', 'sku': '1276-1043-1-ND'},
        {'supplier': 'Mouser', 'sku': 'C0402'},
    ]
    mpns = [{'manufacturer': 'Samsung', 'mpn': 'CL05B104KO5NNNC'}]

    assert lcsc_numbers(skus) == ['C1525', 'C25804']
    assert digikey_numbers(mpns, skus) == ['1276-1043-1-ND', 'CL05B104KO5NNNC']
    assert digikey_numbers([], []) == []


def test_description_source():
    result = description_source('CAP 100nF 16V X7R 0402', '')

    assert {item['name']: item['value'] for item in result['parameters']} == {
        'Dielectric': 'X7R',
        'Package': '0402',
        'Capacitance': '100nF',
        'Voltage rating': '16V',
    }
    assert description_source('Screw M2x5', '')['parameters'] == []
