"""Check the Alternate Parts plugin against a live InvenTree development instance.

Run this after dev/seed_demo.py, against a throwaway database - it creates
and changes records.

    python dev/integration_check.py http://localhost:8000 <api token> [--no-worker]

New BOM lines are picked up through an InvenTree event, which needs the
background worker to be running; give --no-worker to leave that check out.

It checks that:

- the candidates found in the demo catalogue are the expected ones, in the
  expected direction and order
- making, changing and removing links adds and removes exactly the right
  BOM substitutes, and never touches a substitute which was set by hand
- a new BOM line picks up the substitutes of its part
- parameters read from a description are stored, and improve the match
- settings behave as documented, invalid input is refused and a user who may
  only view cannot change anything
"""

from __future__ import annotations

import sys
import time

import requests
from seed_demo import Api

results = []


def check(name: str, ok: bool, detail: str = ''):
    results.append(bool(ok))
    print('PASS' if ok else 'FAIL', name, detail if not ok else '')


class Client(Api):
    """API client which can also return the status of a refused request."""

    def status(self, method: str, url: str, data=None) -> int:
        return self.session.request(method, f'{self.base}{url}', json=data).status_code

    def all(self, url: str) -> list:
        joiner = '&' if '?' in url else '?'
        data = self.get(f'{url}{joiner}limit=5000')

        return data['results'] if isinstance(data, dict) else data

    def setting(self, key: str, value):
        self.patch(f'/api/plugins/apns/settings/{key}/', {'value': value})

    def part(self, pk: int, fresh: bool = True) -> dict:
        return self.get(f'/plugin/apns/part/{pk}/' + ('?fresh=1' if fresh else ''))

    def overview(self) -> dict:
        return self.get('/plugin/apns/overview/?fresh=1')

    def link(self, part: int, alternate: int, two_way: bool = False, note: str = '') -> dict:
        return self.post('/plugin/apns/links/', {'part': part, 'alternate': alternate, 'two_way': two_way, 'note': note})

    def unlink(self, part: int, alternate: int) -> dict:
        return self.delete('/plugin/apns/links/', {'part': part, 'alternate': alternate})

    def substitutes(self, line: int) -> set:
        return {row['part'] for row in self.all(f'/api/bom/substitute/?bom_item={line}')}


def main(base: str, token: str, worker: bool = True):
    api = Client(base, token)

    parts = {row['name']: row['pk'] for row in api.all('/api/part/')}
    c1 = parts['CAP 100nF 16V X7R 0402 Samsung']
    c2 = parts['CAP 100nF 16V X7R 0402 Murata']
    c3 = parts['CAP 100nF 50V X7R 0402']
    c4 = parts['CAP 100nF 16V Y5V 0402']
    c5 = parts['CAP 1uF 16V X5R 0402']
    c6 = parts['CAP 100nF 16V X7R 0603']
    c7 = parts['CAP CER 0.1uF 16V X7R 0402 10%']
    c8 = parts['CAP 100nF 16V X7R 0402 AEC-Q200']
    r1 = parts['RES 10k 1% 0402 Yageo']
    r2 = parts['RES 10k 5% 0402']
    r3 = parts['RES 10k 1% 0402 UniOhm']
    r4 = parts['RES 4k7 1% 0402']
    u1 = parts['LDO 3.3V 500mA TI']
    u2 = parts['LDO 3.3V 500mA Microchip']
    u3 = parts['LDO 5.0V 500mA TI']
    d1 = parts['Schottky diode BAT54S']
    d2 = parts['BAT54S dual diode']
    h1 = parts['Screw M2x5 Phillips pan head']
    h2 = parts['Screw M2x8 Phillips pan head']
    h3 = parts['Membrane vent adhesive IP67']
    h4 = parts['Membrane vent adhesive IP67 black']
    a1 = parts['Sensor board PCBA']
    a2 = parts['Power board PCBA']

    lines = {(row['part'], row['sub_part']): row['pk'] for row in api.all('/api/bom/')}
    a1_c1, a2_c1, a2_c3 = lines[(a1, c1)], lines[(a2, c1)], lines[(a2, c3)]
    a1_r1, a2_r2, a2_r3 = lines[(a1, r1)], lines[(a2, r2)], lines[(a2, r3)]

    # --- Candidates -------------------------------------------------------

    view = api.part(c1)
    found = {item['other']: item for item in view['candidates']}

    check('same part from another maker is a two-way candidate', found.get(c2, {}).get('direction') == 'both', str(found.get(c2)))
    check('higher voltage rating is a one-way candidate', found.get(c3, {}).get('direction') == 'forward', str(found.get(c3)))
    check('a different value is not a candidate', c5 not in found)
    check('a different package is not a candidate', c6 not in found)
    check('a part with only a description is matched', c7 in found and all(row['derived'] for row in found[c7]['rows']))
    check('a poorer dielectric cannot replace the part', found.get(c4, {}).get('direction') == 'reverse', str(found.get(c4)))
    check('candidates are sorted by strength', [item['strength'] for item in view['candidates']] == sorted((item['strength'] for item in view['candidates']), reverse=True))
    check('the hand-set substitute is flagged', found.get(c2, {}).get('substitute_on') == 1)
    check('the hand-set substitute ranks first', view['candidates'][0]['other'] == c2, str([item['other'] for item in view['candidates']]))
    check('the part is used on two BOM lines', view['bom_lines'] == 2 and {item['assembly'] for item in view['usage']} == {a1, a2})
    check('nothing is pending before any link', view['pending'] == 0)

    qualified = {row['key']: row for row in found.get(c8, {}).get('rows', [])}.get('qualification', {})
    check(
        'an AEC-Q200 part is still a candidate for the unqualified one, as a weaker match',
        found.get(c8, {}).get('direction') == 'both'
        and found[c8]['strength'] < found[c2]['strength'] - 3
        and (qualified.get('a'), qualified.get('b'), qualified.get('verdict')) == ('None stated', 'AEC-Q200', 'better'),
        f"{found.get(c8, {}).get('direction')} {found.get(c8, {}).get('strength')} vs {found.get(c2, {}).get('strength')} {qualified}",
    )
    back = {item['other']: item['direction'] for item in api.part(c8)['candidates']}
    check('and the other way round', back.get(c1) == 'both' and back.get(c2) == 'both', str(back))

    api.setting('QUALIFICATION_STRICT', True)
    strict = {item['other']: item['direction'] for item in api.part(c1)['candidates']}
    back = {item['other']: item['direction'] for item in api.part(c8)['candidates']}
    check(
        'held to strictly, the AEC-Q200 part can replace the other and not the reverse',
        strict.get(c8) == 'forward' and back.get(c1) == 'reverse' and back.get(c2) == 'reverse',
        f'{strict.get(c8)} {back}',
    )
    api.setting('QUALIFICATION_STRICT', False)
    check('and back again', {item['other']: item['direction'] for item in api.part(c1)['candidates']}.get(c8) == 'both')

    rows = {row['key']: row for row in found[c3]['rows']}
    check('the comparison shows why it is one-way', rows['voltage']['verdict'] == 'better' and rows['capacitance']['verdict'] == 'match')
    listed = {row['label'] for row in found[c3]['rows'] if row['verdict'] == 'info'}
    check('parts which state no qualification are not compared on it', 'qualification' not in rows and listed == set(), str(listed))
    check('values match whatever the notation', {row['key']: row['verdict'] for row in found[c2]['rows']}['capacitance'] == 'match')

    view = api.part(r2)
    found = {item['other']: item for item in view['candidates']}
    check('1% resistors can replace the 5% one', found.get(r1, {}).get('direction') == 'forward' and found.get(r3, {}).get('direction') == 'forward')
    check('a different resistance is not a candidate', r4 not in found)

    view = api.part(u1)
    found = {item['other']: item for item in view['candidates']}
    check('same regulator from another maker is a candidate', found.get(u2, {}).get('direction') == 'both', str(found.get(u2)))
    check('a different output voltage is not a candidate', u3 not in found, str(found.get(u3)))

    found = {item['other'] for item in api.part(h1)['candidates']}
    check('screws of different length are not candidates', h2 not in found)
    found = {item['other']: item for item in api.part(h3)['candidates']}
    check('near-identical names are a weak candidate', found.get(h4, {}).get('basis') == 'name' and found[h4]['strength'] < 80, str(found.get(h4)))

    view = api.part(d1)
    check('the same MPN is a duplicate', view['candidates'][0]['other'] == d2 and view['candidates'][0]['same_mpn'] and view['candidates'][0]['strength'] == 100)

    overview = api.overview()
    pairs = {frozenset((item['part'], item['other'])): item for item in overview['candidates']}
    check('overview lists each pair once', len(pairs) == len(overview['candidates']))
    check('overview finds the capacitor pair', frozenset((c1, c2)) in pairs)
    check('overview lists the duplicate MPN', [set(item['parts']) for item in overview['duplicates']] == [{d1, d2}])
    by_hand = [(item['part'], item['other'], item['lines'], item['missing']) for item in overview['by_hand']]
    check('overview lists the hand-set substitute and where it is missing', by_hand == [(c1, c2, 1, 1)], str(by_hand))
    check('overview lists parts with little data', c7 in {item['part'] for item in overview['thin']} and c1 not in {item['part'] for item in overview['thin']})
    check('overview summary counts', overview['summary']['links'] == 0 and overview['summary']['pending'] == 0 and overview['summary']['bom_lines'] == 9)

    # --- One-way link -----------------------------------------------------

    before = api.substitutes(a1_c1)
    result = api.link(c1, c3, two_way=False, note='Higher voltage rating')
    check('linking reports the BOM changes', result['sync'] == {'added': 2, 'removed': 0, 'errors': [], 'skipped': 0}, str(result['sync']))
    check('one-way link adds the alternate to every line of the part', api.substitutes(a1_c1) == before | {c3} and api.substitutes(a2_c1) == {c3})
    check('one-way link adds nothing to lines of the alternate', api.substitutes(a2_c3) == set())

    view = api.part(c1)
    linked = {item['other']: item for item in view['links']}
    check('the link shows on the part', linked.get(c3, {}).get('relation') == 'forward' and linked[c3]['note'] == 'Higher voltage rating' and linked[c3]['by'] == 'admin')
    check('a linked part is no longer a candidate', c3 not in {item['other'] for item in view['candidates']})
    check('the link shows from the other side', {item['other']: item['relation'] for item in api.part(c3)['links']} == {c1: 'reverse'})
    managed = {item['part']: item['managed'] for item in next(row for row in view['usage'] if row['line'] == a1_c1)['substitutes']}
    check('substitutes are marked as added by the plugin or by hand', managed == {c2: False, c3: True}, str(managed))
    check('the link is stored in the part metadata', api.get(f'/api/part/{c1}/metadata/')['metadata']['apns']['alternates'][0]['part'] == c3)
    check('links are listed', [(item['part'], item['alternate'], item['two_way']) for item in api.get('/plugin/apns/links/')['links']] == [(c1, c3, False)])

    # --- Two-way link -----------------------------------------------------

    api.link(r1, r3, two_way=True)
    check('two-way link adds substitutes in both directions', api.substitutes(a1_r1) == {r3} and api.substitutes(a2_r3) == {r1})
    check('two-way link shows as interchangeable on both parts', api.part(r1)['links'][0]['relation'] == 'both' and api.part(r3)['links'][0]['relation'] == 'both')

    # Turn it into a one-way link the other way round: R1 can replace R3 only
    result = api.link(r3, r1, two_way=False)
    check('changing a link to one-way removes the reverse substitute', api.substitutes(a1_r1) == set() and api.substitutes(a2_r3) == {r1}, str(result['sync']))
    check('there is still only one link between the two', len([item for item in api.get('/plugin/apns/links/')['links'] if {item['part'], item['alternate']} == {r1, r3}]) == 1)

    api.link(r2, r1, two_way=False)
    api.link(r2, r3, two_way=False)
    check('a part can have several alternates', api.substitutes(a2_r2) == {r1, r3})
    check('links are not chained', api.substitutes(a2_r3) == {r1})

    # --- Hand-set substitutes are left alone --------------------------------

    api.link(c1, c2, two_way=True)
    check('linking a hand-set substitute fills in the other BOMs', api.substitutes(a2_c1) == {c2, c3} and api.substitutes(a1_c1) == {c2, c3})
    check('the hand-set substitute is no longer listed as unlinked', api.overview()['by_hand'] == [])

    api.unlink(c1, c2)
    check('removing the link removes only what the plugin added', api.substitutes(a2_c1) == {c3} and api.substitutes(a1_c1) == {c2, c3})

    api.unlink(c3, c1)
    check('a link can be removed from either side', api.substitutes(a2_c1) == set() and api.substitutes(a1_c1) == {c2})
    check('the metadata is cleaned up', 'apns' not in api.get(f'/api/part/{c1}/metadata/')['metadata'])

    # --- New BOM lines ----------------------------------------------------

    api.link(c1, c3)
    a3 = api.post('/api/part/', {'name': 'Radio board PCBA', 'assembly': True, 'component': True})['pk']
    new_line = api.post('/api/bom/', {'part': a3, 'sub_part': c1, 'quantity': 3})['pk']

    if worker:
        for _ in range(60):
            if api.substitutes(new_line):
                break
            time.sleep(0.5)

        check('a new BOM line picks up the alternates of its part', api.substitutes(new_line) == {c3}, str(api.substitutes(new_line)))
    else:
        api.post('/plugin/apns/sync/', {'parts': [c1]})
        check('a sync fills in a new BOM line', api.substitutes(new_line) == {c3}, str(api.substitutes(new_line)))

    # --- Parts which cannot be substitutes ----------------------------------

    api.patch(f'/api/part/{c3}/', {'active': False})
    api.post('/plugin/apns/sync/', {})
    check('an inactive alternate is taken off the BOMs', api.substitutes(a2_c1) == set() and api.substitutes(new_line) == set())
    check('the link says why', 'Inactive' in api.part(c1)['links'][0]['problems'])
    api.setting('INCLUDE_INACTIVE', True)
    api.post('/plugin/apns/sync/', {})
    check('unless inactive parts are included', api.substitutes(a2_c1) == {c3})
    api.setting('INCLUDE_INACTIVE', False)
    api.patch(f'/api/part/{c3}/', {'active': True})
    api.post('/plugin/apns/sync/', {})

    check('a part is never made a substitute in its own BOM', api.status('POST', '/plugin/apns/links/', {'part': c1, 'alternate': a1}) == 200 and a1 not in api.substitutes(a1_c1) and api.substitutes(a2_c1) == {a1, c3})
    api.unlink(c1, a1)

    # --- Sync on demand ---------------------------------------------------

    api.setting('AUTO_SYNC', False)
    result = api.link(u1, u2, two_way=True)
    a1_u1, a2_u1 = lines[(a1, u1)], lines[(a2, u1)]
    check('with auto sync off a link does not change the BOMs', result['sync'] is None and api.substitutes(a1_u1) == set())
    plan = api.get('/plugin/apns/sync/')
    check('the pending changes are listed', plan['add'] == 2 and {change['line'] for change in plan['lines']} == {a1_u1, a2_u1}, str(plan))
    check('the part shows what is pending', api.part(u1)['pending'] == 2)
    check('the overview counts what is pending', api.overview()['summary']['pending'] == 2)
    result = api.post('/plugin/apns/sync/', {'parts': [u1]})
    check('sync applies them', result['added'] == 2 and api.substitutes(a1_u1) == {u2} and api.substitutes(a2_u1) == {u2}, str(result))
    check('a second sync changes nothing', api.post('/plugin/apns/sync/', {}) == {'added': 0, 'removed': 0, 'errors': [], 'skipped': 0})
    api.setting('AUTO_SYNC', True)

    # --- Locked assemblies ------------------------------------------------

    api.patch(f'/api/part/{a2}/', {'locked': True})
    api.setting('SKIP_LOCKED', True)
    result = api.unlink(u1, u2)
    check('locked assemblies are skipped when asked', result['sync']['skipped'] == 1 and api.substitutes(a1_u1) == set() and api.substitutes(a2_u1) == {u2}, str(result['sync']))
    api.setting('SKIP_LOCKED', False)
    api.post('/plugin/apns/sync/', {})
    check('and changed otherwise', api.substitutes(a2_u1) == set())
    api.patch(f'/api/part/{a2}/', {'locked': False})

    # --- Dismissing candidates ----------------------------------------------

    api.post('/plugin/apns/dismiss/', {'part': c1, 'other': c4})
    view = api.part(c1)
    check('a dismissed candidate moves to the dismissed list', c4 not in {item['other'] for item in view['candidates']} and c4 in {item['other'] for item in view['dismissed']})
    check('it is dismissed from the other side too', c1 in {item['other'] for item in api.part(c4)['dismissed']})
    check('and left out of the overview', frozenset((c1, c4)) not in {frozenset((item['part'], item['other'])) for item in api.overview()['candidates']})
    api.post('/plugin/apns/dismiss/', {'part': c4, 'other': c1, 'dismissed': False})
    check('it can be brought back', c4 in {item['other'] for item in api.part(c1)['candidates']})
    api.post('/plugin/apns/dismiss/', {'part': c1, 'other': c4})
    api.link(c4, c1)
    check('linking clears a dismissal', api.part(c1)['dismissed'] == [] and c4 in {item['other'] for item in api.part(c1)['links']})
    api.unlink(c4, c1)

    # --- Parameters from the description ------------------------------------

    before = {item['other']: item for item in api.part(c1)['candidates']}[c7]
    proposal = api.post('/plugin/apns/enrich/', {'part': c7, 'sources': ['description']})
    actions = {item['template_name']: (item['action'], item['value']) for item in proposal['proposals']}
    check(
        'values are read from the description into the existing templates',
        actions == {
            'Capacitance': ('add', '100 nF'),
            'Package': ('add', '0402'),
            'Voltage Rating': ('add', '16 V'),
            'Tolerance': ('add', '10 %'),
            'Dielectric': ('add', 'X7R'),
        },
        str(actions),
    )
    check('proposing changes nothing', api.all(f'/api/parameter/?model_type=part.part&model_id={c7}') == [])

    applied = api.post('/plugin/apns/enrich/', {'part': c7, 'sources': ['description'], 'apply': True, 'only': ['Capacitance', 'Package']})
    stored = {row['template_detail']['name']: row['data'] for row in api.all(f'/api/parameter/?model_type=part.part&model_id={c7}')}
    check('only the chosen parameters are stored', stored == {'Capacitance': '100 nF', 'Package': '0402'} and applied['applied']['errors'] == [], str(stored))

    applied = api.post('/plugin/apns/enrich/', {'part': c7, 'apply': True})
    stored = {row['template_detail']['name']: row['data'] for row in api.all(f'/api/parameter/?model_type=part.part&model_id={c7}')}
    check('the rest is stored on the next run', len(stored) == 5 and stored['Voltage Rating'] == '16 V', str(stored))
    again = api.post('/plugin/apns/enrich/', {'part': c7, 'apply': True})
    check('existing parameters are kept', {item['action'] for item in again['proposals']} == {'keep'} and again['applied']['added'] == [])
    report = {item['source']: item['status'] for item in again['report']}
    check('sources which are not set up are reported', report == {'digikey': 'off', 'lcsc': 'off', 'description': 'found'}, str(report))

    after = {item['other']: item for item in api.part(c1)['candidates']}[c7]
    check('real parameters make a stronger match than a description', after['strength'] > before['strength'] and not any(row['derived'] for row in after['rows']), f'{before["strength"]} -> {after["strength"]}')
    check('the part is no longer short of data', c7 not in {item['part'] for item in api.overview()['thin']})

    # A value which does not fit a template with units is not stored
    proposal = api.post('/plugin/apns/enrich/', {'part': h1, 'sources': ['description']})
    check('a part with nothing to read gets no proposals', proposal['proposals'] == [])

    derived = [(item['key'], item['derived']) for item in api.part(d1)['attributes']]
    api.setting('USE_DESCRIPTION', False)
    check('descriptions can be ignored', derived == [('package', True)] and api.part(d1)['attributes'] == [], str(derived))
    api.setting('USE_DESCRIPTION', True)

    api.setting('MIN_STRENGTH', 99)
    check('the weakest candidate to show can be set', all(item['strength'] >= 99 for item in api.part(c1)['candidates']))
    api.setting('MIN_STRENGTH', 60)

    # --- Invalid input ----------------------------------------------------

    check('a part cannot be its own alternate', api.status('POST', '/plugin/apns/links/', {'part': c1, 'alternate': c1}) == 400)
    check('an unknown part is refused', api.status('POST', '/plugin/apns/links/', {'part': c1, 'alternate': 999999}) == 400)
    check('a missing part is refused', api.status('POST', '/plugin/apns/links/', {'alternate': c1}) == 400)
    check('an unknown part page is not found', api.status('GET', '/plugin/apns/part/999999/') == 404)
    check('an unknown source is refused', api.status('POST', '/plugin/apns/enrich/', {'part': c1, 'sources': ['nowhere']}) == 400)
    check('a bad list of parts is refused', api.status('POST', '/plugin/apns/sync/', {'parts': 'all'}) == 400)

    # --- Permissions ------------------------------------------------------

    group = api.post('/api/user/group/', {'name': 'apns-viewers'})
    for role in group['roles']:
        if role['name'] in ('part', 'bom'):
            api.patch(f'/api/user/ruleset/{role["pk"]}/', {'can_view': True})

    user = api.post('/api/user/', {'username': 'apns-viewer', 'email': 'viewer@example.com', 'first_name': 'View', 'last_name': 'Only', 'group_ids': [group['pk']], 'is_active': True})
    api.call('PUT', f'/api/user/{user["pk"]}/set-password/', {'password': 'Viewer-pass-9482', 'override_warning': True})
    viewer_token = requests.get(f'{api.base}/api/user/token/?name=check', auth=('apns-viewer', 'Viewer-pass-9482')).json()['token']
    viewer = Client(base, viewer_token)

    permissions = viewer.part(c1)['permissions']
    check('a view-only user can read', permissions == {'view': True, 'link': False, 'sync': False, 'enrich': False}, str(permissions))
    check('but not link', viewer.status('POST', '/plugin/apns/links/', {'part': c1, 'alternate': c2}) == 403)
    check('nor unlink', viewer.status('DELETE', '/plugin/apns/links/', {'part': c1, 'alternate': c3}) == 403)
    check('nor dismiss', viewer.status('POST', '/plugin/apns/dismiss/', {'part': c1, 'other': c2}) == 403)
    check('nor sync', viewer.status('POST', '/plugin/apns/sync/', {}) == 403)
    check('nor add parameters', viewer.status('POST', '/plugin/apns/enrich/', {'part': c1}) == 403)
    check('the links are unchanged', {item['other'] for item in api.part(c1)['links']} == {c3})

    nobody = requests.get(f'{api.base}/plugin/apns/overview/')
    check('an anonymous request is refused', nobody.status_code in (401, 403))

    # A user who may change parts but not BOMs can link; the BOMs wait for a sync
    for role in group['roles']:
        if role['name'] == 'part':
            api.patch(f'/api/user/ruleset/{role["pk"]}/', {'can_view': True, 'can_change': True})

    result = viewer.post('/plugin/apns/links/', {'part': u1, 'alternate': u2, 'two_way': True})
    check('without BOM permission a link is saved but the BOMs wait', result['sync'] is None and api.substitutes(a1_u1) == set() and api.part(u1)['pending'] == 2)
    api.unlink(u1, u2)

    print()
    print(f'{sum(results)} of {len(results)} checks passed')

    if not all(results):
        raise SystemExit(1)


if __name__ == '__main__':
    arguments = [item for item in sys.argv[1:] if item != '--no-worker']

    if len(arguments) != 2:
        raise SystemExit(__doc__)

    main(arguments[0], arguments[1], worker='--no-worker' not in sys.argv)
