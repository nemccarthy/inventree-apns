"""Seed an InvenTree development instance with demo data for the Alternate Parts plugin.

Creates a small made-up catalogue (capacitors, resistors, regulators,
hardware) in which some parts are alternates of each other, and two
assemblies which use them.

    python dev/seed_demo.py http://localhost:8000 <api token>

Only run this against a throwaway database.
"""

from __future__ import annotations

import sys

import requests


class Api:
    """Minimal InvenTree API client."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip('/')
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Token {token}'

    def call(self, method: str, url: str, data=None):
        response = self.session.request(method, f'{self.base}{url}', json=data)

        if response.status_code >= 400:
            raise SystemExit(f'{method} {url} -> {response.status_code}: {response.text[:400]}')

        return response.json() if response.content else {}

    def post(self, url: str, data=None):
        return self.call('POST', url, data or {})

    def get(self, url: str):
        return self.call('GET', url)

    def patch(self, url: str, data=None):
        return self.call('PATCH', url, data or {})

    def delete(self, url: str, data=None):
        return self.call('DELETE', url, data)


def main(base: str, token: str) -> dict:
    api = Api(base, token)
    api.get('/plugin/apns/config/')

    cats = {
        name: api.post('/api/part/category/', {'name': name})['pk']
        for name in ('Capacitors', 'Resistors', 'Regulators', 'Diodes', 'Hardware', 'Assemblies')
    }

    templates = {
        name: api.post('/api/parameter/template/', {'name': name, 'units': units})['pk']
        for name, units in (
            ('Capacitance', 'F'),
            ('Resistance', 'ohm'),
            ('Package', ''),
            ('Tolerance', '%'),
            ('Voltage Rating', 'V'),
            ('Dielectric', ''),
            ('Power', 'W'),
            ('Voltage - Output', 'V'),
            ('Current - Output', 'A'),
            ('Qualification', ''),
        )
    }

    makers = {
        name: api.post('/api/company/', {'name': name, 'is_manufacturer': True, 'is_supplier': False})['pk']
        for name in ('Samsung', 'Murata', 'Yageo', 'UniOhm', 'Diodes Inc', 'Nexperia', 'TI', 'Microchip')
    }
    lcsc = api.post('/api/company/', {'name': 'LCSC', 'is_supplier': True})['pk']
    location = api.post('/api/stock/location/', {'name': 'Parts store'})['pk']

    parts = {}

    def part(key, name, category, description='', mpn=None, sku=None, stock=0, params=None, **flags):
        pk = api.post(
            '/api/part/',
            {
                'name': name,
                'description': description,
                'category': cats[category],
                'component': True,
                'purchaseable': True,
                **flags,
            },
        )['pk']
        parts[key] = pk

        for template, value in (params or {}).items():
            api.post(
                '/api/parameter/',
                {'template': templates[template], 'model_type': 'part.part', 'model_id': pk, 'data': value},
            )

        if mpn:
            maker, number = mpn
            api.post('/api/company/part/manufacturer/', {'part': pk, 'manufacturer': makers[maker], 'MPN': number})

        if sku:
            api.post('/api/company/part/', {'part': pk, 'supplier': lcsc, 'SKU': sku})

        if stock:
            api.post('/api/stock/', {'part': pk, 'quantity': stock, 'location': location})

        return pk

    def cap(key, name, maker, mpn, value='100nF', package='0402', voltage='16V', tolerance='10%', dielectric='X7R', qualification=None, **kwargs):
        return part(
            key,
            name,
            'Capacitors',
            f'Ceramic capacitor {value} {voltage} {dielectric} {package}',
            mpn=(maker, mpn),
            params={
                'Capacitance': value,
                'Package': package,
                'Voltage Rating': voltage,
                'Tolerance': tolerance,
                'Dielectric': dielectric,
                **({'Qualification': qualification} if qualification else {}),
            },
            **kwargs,
        )

    # Capacitors: C1 and C2 are the same from two makers, C3 has a higher
    # voltage rating, C4 a poorer dielectric, C5 and C6 are different parts,
    # C8 is AEC-Q200 qualified
    cap('C1', 'CAP 100nF 16V X7R 0402 Samsung', 'Samsung', 'CL05B104KO5NNNC', stock=4200)
    cap('C2', 'CAP 100nF 16V X7R 0402 Murata', 'Murata', 'GRM155R71C104KA88D', value='0.1 uF', stock=900)
    cap('C3', 'CAP 100nF 50V X7R 0402', 'Murata', 'GRM155R71H104KE14D', voltage='50V', stock=150)
    cap('C4', 'CAP 100nF 16V Y5V 0402', 'Yageo', 'CC0402ZRY5V7BB104', dielectric='Y5V', tolerance='20%')
    cap('C5', 'CAP 1uF 16V X5R 0402', 'Samsung', 'CL05A105KO5NNNC', value='1uF', dielectric='X5R', stock=2500)
    cap('C6', 'CAP 100nF 16V X7R 0603', 'Samsung', 'CL10B104KO8NNNC', package='0603', stock=800)

    # The automotive version of C1: it can replace C1, C1 cannot replace it
    cap('C8', 'CAP 100nF 16V X7R 0402 AEC-Q200', 'Murata', 'GCM155R71C104KA55D', qualification='AEC-Q200', stock=400)

    # No parameters at all: only a description, and an LCSC number
    part('C7', 'CAP CER 0.1uF 16V X7R 0402 10%', 'Capacitors', 'Generic MLCC', sku='C1525', stock=300)

    def res(key, name, maker, mpn, value='10k', tolerance='1%', power='1/16 W', **kwargs):
        return part(
            key,
            name,
            'Resistors',
            f'Thick film resistor {value} {tolerance} 0402',
            mpn=(maker, mpn),
            params={'Resistance': value, 'Package': '0402', 'Tolerance': tolerance, 'Power': power},
            **kwargs,
        )

    res('R1', 'RES 10k 1% 0402 Yageo', 'Yageo', 'RC0402FR-0710KL', stock=9000)
    res('R2', 'RES 10k 5% 0402', 'UniOhm', '0402WGJ0103TCE', tolerance='5%', stock=3000)
    res('R3', 'RES 10k 1% 0402 UniOhm', 'UniOhm', '0402WGF1002TCE', value='10 kohm', power='62.5 mW', stock=500)
    res('R4', 'RES 4k7 1% 0402', 'Yageo', 'RC0402FR-074K7L', value='4.7k')

    def ldo(key, name, maker, mpn, output, **kwargs):
        return part(
            key,
            name,
            'Regulators',
            f'LDO regulator {output} 500mA SOT-23-5',
            mpn=(maker, mpn),
            params={'Package': 'SOT-23-5', 'Voltage - Output': output, 'Current - Output': '500 mA'},
            **kwargs,
        )

    ldo('U1', 'LDO 3.3V 500mA TI', 'TI', 'TLV75533PDBVR', '3.3V', stock=120)
    ldo('U2', 'LDO 3.3V 500mA Microchip', 'Microchip', 'MIC5504-3.3YM5-TR', '3.3 V', stock=40)
    ldo('U3', 'LDO 5.0V 500mA TI', 'TI', 'TLV75550PDBVR', '5V')

    # The same manufacturer part number held under two parts
    part('D1', 'Schottky diode BAT54S', 'Diodes', 'Dual Schottky SOT-23', mpn=('Diodes Inc', 'BAT54S-7-F'), stock=600)
    part('D2', 'BAT54S dual diode', 'Diodes', 'SOT-23 30V 200mA', mpn=('Diodes Inc', 'BAT54S-7-F'), stock=75)

    # Hardware: no parameters, matched on the name alone
    part('H1', 'Screw M2x5 Phillips pan head', 'Hardware')
    part('H2', 'Screw M2x8 Phillips pan head', 'Hardware')
    part('H3', 'Membrane vent adhesive IP67', 'Hardware', stock=200)
    part('H4', 'Membrane vent adhesive IP67 black', 'Hardware', stock=50)

    def assembly(key, name):
        parts[key] = api.post(
            '/api/part/',
            {'name': name, 'category': cats['Assemblies'], 'assembly': True, 'component': True, 'purchaseable': False},
        )['pk']
        return parts[key]

    lines = {}

    def line(key, parent, sub, quantity, reference=''):
        lines[key] = api.post(
            '/api/bom/',
            {'part': parts[parent], 'sub_part': parts[sub], 'quantity': quantity, 'reference': reference},
        )['pk']
        return lines[key]

    assembly('A1', 'Sensor board PCBA')
    line('A1.C1', 'A1', 'C1', 10, 'C1-C10')
    line('A1.R1', 'A1', 'R1', 4, 'R1-R4')
    line('A1.U1', 'A1', 'U1', 1, 'U1')
    line('A1.D1', 'A1', 'D1', 2, 'D1 D2')

    assembly('A2', 'Power board PCBA')
    line('A2.C1', 'A2', 'C1', 4, 'C1-C4')
    line('A2.C3', 'A2', 'C3', 2, 'C5 C6')
    line('A2.R2', 'A2', 'R2', 6, 'R1-R6')
    line('A2.R3', 'A2', 'R3', 2, 'R7 R8')
    line('A2.U1', 'A2', 'U1', 1, 'U1')

    # A substitute set by hand on one of the two BOMs which use C1
    api.post('/api/bom/substitute/', {'bom_item': lines['A1.C1'], 'part': parts['C2']})

    print(f'Created {len(parts)} parts and {len(lines)} BOM lines')

    return {'parts': parts, 'lines': lines, 'cats': cats, 'templates': templates}


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)

    main(sys.argv[1], sys.argv[2])
