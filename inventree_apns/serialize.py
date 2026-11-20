"""Building the API responses."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from . import PLUGIN_VERSION, store, sync
from .links import Links
from .loader import Data, load, load_bom_lines, plugin_settings
from .matching import Match, compare

# How many rows the overview returns of each kind
MAX_CANDIDATES = 300
MAX_THIN = 500
MAX_SYNC_LINES = 300

# A pair which is already a substitute on a BOM is a strong candidate
SUBSTITUTE_STRENGTH = 90


def part_label(data: Data, pk: int) -> dict:
    """The details of a part which the interface shows next to its name."""
    part = data.info.get(pk)

    if part is None:
        return {'pk': pk, 'name': f'Part {pk}', 'ipn': '', 'description': '', 'missing': True}

    return {
        'pk': pk,
        'name': part['name'],
        'ipn': part['ipn'],
        'description': part['description'],
        'category_name': part['category_name'],
        'active': part['active'],
        'component': part['component'],
        'stock': part['stock'],
        'units': part['units'],
        'mpns': part['mpns'][:4],
        'known': part['known'],
        'derived': part['derived'],
    }


def match_dict(match: Match | None) -> dict | None:
    if match is None:
        return None

    return {
        'strength': match.strength,
        'direction': match.direction,
        'basis': match.basis,
        'coverage': match.coverage,
        'same_mpn': match.same_mpn,
        'rows': match.rows,
    }


def _compare(data: Data, a: int, b: int, force: bool = False) -> Match | None:
    left, right = data.features.get(a), data.features.get(b)

    if left is None or right is None:
        return None

    return compare(left, right, force=force)


def manual_substitutes(lines) -> dict:
    """Substitutes which were added to BOM lines by hand.

    Returns {(part, substitute): [BOM line ids]}.
    """
    found = defaultdict(list)

    for line in lines:
        for substitute, (_record, managed) in line.substitutes.items():
            if not managed:
                found[(line.sub_part, substitute)].append(line.pk)

    return found


def link_dict(data: Data, part: int, other: int, relation: str, link) -> dict:
    """A link, read from one of its two parts."""
    target = data.info.get(other)
    problems = []

    if target is None:
        problems.append('The part no longer exists')
    else:
        if not target['active']:
            problems.append('Inactive')

        if relation != 'reverse' and not target['component']:
            problems.append('Not a component, so it cannot be a BOM substitute')

    return {
        'other': other,
        'relation': relation,
        'two_way': link.two_way,
        'note': link.note,
        'by': link.by,
        'at': link.at,
        'stored_on': link.part,
        'match': match_dict(_compare(data, part, other, force=True)),
        'problems': problems,
    }


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def part_payload(plugin, pk: int, use_cache: bool = True) -> dict | None:
    """Everything the part panel shows."""
    data = load(plugin, use_cache=use_cache)

    if pk not in data.info:
        return None

    settings = plugin_settings(plugin)
    links = store.load(valid=data.info.keys())
    mentioned = {pk}

    linked = []

    for other, relation, link in links.of(pk):
        linked.append(link_dict(data, pk, other, relation, link))
        mentioned.add(other)

    linked.sort(key=lambda item: (item['relation'] != 'both', data.info.get(item['other'], {}).get('name', '')))
    linked_parts = {item['other'] for item in linked}

    # BOM lines which use this part, and what a sync would change on them
    lines = load_bom_lines(sub_parts=[pk])
    changes = {change['line']: change for change in sync.plan(data, links, settings, sub_parts=[pk])['lines']}
    usage = []

    for line in lines:
        change = changes.get(line.pk, {})
        mentioned.add(line.assembly)
        mentioned.update(line.substitutes)
        usage.append({
            'line': line.pk,
            'assembly': line.assembly,
            'reference': line.reference,
            'locked': line.locked,
            'substitutes': [
                {'part': part, 'managed': managed}
                for part, (_record, managed) in sorted(line.substitutes.items())
            ],
            'add': change.get('add', []),
            'remove': change.get('remove', []),
            'skipped': change.get('skipped', False),
        })

    usage.sort(key=lambda item: data.info.get(item['assembly'], {}).get('name', ''))

    # Substitutes set by hand on some of those lines
    manual = defaultdict(int)

    for line in lines:
        for substitute, (_record, managed) in line.substitutes.items():
            if not managed:
                manual[substitute] += 1

    candidates = []
    dismissed = []
    seen = set()

    if pk in data.eligible:
        for match in data.catalogue.candidates(pk, minimum=0, limit=200, exclude=linked_parts):
            seen.add(match.other)
            entry = {'other': match.other, **match_dict(match), 'substitute_on': manual.get(match.other, 0)}

            if entry['substitute_on']:
                entry['strength'] = max(entry['strength'], SUBSTITUTE_STRENGTH)

            if links.is_dismissed(pk, match.other):
                dismissed.append(entry)
            elif entry['strength'] >= settings['min_strength']:
                candidates.append(entry)

    # A substitute set by hand is a candidate, whatever its parameters say
    for substitute, count in manual.items():
        if substitute in seen or substitute in linked_parts or substitute not in data.info:
            continue

        match = _compare(data, pk, substitute, force=True)
        entry = {
            'other': substitute,
            **(match_dict(match) or {}),
            'strength': SUBSTITUTE_STRENGTH,
            'direction': 'forward',
            'basis': 'bom',
            'substitute_on': count,
        }
        (dismissed if links.is_dismissed(pk, substitute) else candidates).append(entry)

    # Substitutes already in use first, then by strength
    candidates.sort(
        key=lambda item: (
            item['substitute_on'] == 0,
            -item['strength'],
            item.get('direction') != 'both',
            -item.get('coverage', 0),
            item['other'],
        )
    )
    candidates = candidates[:50]

    for entry in candidates + dismissed:
        mentioned.add(entry['other'])

    feature = data.features.get(pk)

    return {
        'version': PLUGIN_VERSION,
        'generated': _stamp(),
        'part': {**part_label(data, pk), 'eligible': pk in data.eligible, 'skus': data.info[pk]['skus'][:6]},
        'attributes': [
            {'key': attr.key, 'label': attr.label, 'text': attr.text, 'derived': attr.derived}
            for attr in (feature.attrs.values() if feature else [])
        ],
        'links': linked,
        'candidates': candidates,
        'dismissed': dismissed,
        'usage': usage,
        'pending': sum(len(item['add']) + len(item['remove']) for item in usage if not item['skipped']),
        'bom_lines': len(lines),
        'parts': {str(key): part_label(data, key) for key in mentioned},
        'settings': settings,
    }


def overview_payload(plugin, use_cache: bool = True) -> dict:
    """Everything the overview page shows."""
    data = load(plugin, use_cache=use_cache)
    settings = plugin_settings(plugin)
    links = store.load(valid=data.info.keys())
    mentioned = set()

    all_links = []

    for link in links.links:
        all_links.append({
            'part': link.part,
            **link_dict(data, link.part, link.alternate, 'both' if link.two_way else 'forward', link),
        })
        mentioned.update((link.part, link.alternate))

    all_links.sort(key=lambda item: data.info.get(item['part'], {}).get('name', ''))

    linked = links.linked_pairs()
    skip = linked | links.dismissed

    lines = load_bom_lines()
    usage = defaultdict(int)

    for line in lines:
        usage[line.sub_part] += 1

    manual = manual_substitutes(lines)
    candidates = {}

    # Room is left for the pairs which are already linked or were turned down
    for match in data.pairs(settings['min_strength'], MAX_CANDIDATES + 4 * len(skip) + 100):
        if frozenset((match.part, match.other)) in skip:
            continue

        if len(candidates) >= MAX_CANDIDATES:
            break

        candidates[frozenset((match.part, match.other))] = {
            'part': match.part,
            'other': match.other,
            **match_dict(match),
            'substitute_on': 0,
        }

    # Substitutes which were set by hand, and are not yet links
    by_hand = []

    for (part, substitute), where in sorted(manual.items()):
        pair = frozenset((part, substitute))

        if pair in linked or part not in data.info or substitute not in data.info:
            continue

        missing = usage[part] - len(where)
        by_hand.append({
            'part': part,
            'other': substitute,
            'lines': len(where),
            'missing': missing,
            'dismissed': pair in links.dismissed,
        })
        mentioned.update((part, substitute))

        if pair in links.dismissed:
            continue

        entry = candidates.get(pair)

        if entry is None:
            match = _compare(data, part, substitute, force=True)
            entry = {
                'part': part,
                'other': substitute,
                **(match_dict(match) or {}),
                'direction': 'forward',
                'basis': 'bom',
                'strength': SUBSTITUTE_STRENGTH,
                'substitute_on': 0,
            }
            candidates[pair] = entry

        if entry['part'] == part:
            entry['substitute_on'] += len(where)

        entry['strength'] = max(entry['strength'], SUBSTITUTE_STRENGTH)

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -item['strength'],
            item.get('direction') != 'both',
            -item.get('coverage', 0),
            item['part'],
            item['other'],
        ),
    )[:MAX_CANDIDATES]

    for entry in ranked:
        entry['used_in'] = usage.get(entry['part'], 0) + usage.get(entry['other'], 0)
        mentioned.update((entry['part'], entry['other']))

    duplicates = []

    for mpn, parts in data.catalogue.duplicates():
        duplicates.append({'mpn': mpn, 'parts': parts})
        mentioned.update(parts)

    plan = sync.plan(data, links, settings)

    for change in plan['lines'][:MAX_SYNC_LINES]:
        mentioned.update((change['assembly'], change['sub_part'], *change['add'], *change['remove']))

    # Parts which are used in a BOM but have little for the matching to go on
    thin = sorted(
        (pk for pk in data.eligible if data.info[pk]['known'] < 2),
        key=lambda pk: (-usage.get(pk, 0), data.info[pk]['name']),
    )
    mentioned.update(thin[:MAX_THIN])

    return {
        'version': PLUGIN_VERSION,
        'generated': _stamp(),
        'summary': {
            'parts': len(data.info),
            'eligible': len(data.eligible),
            'links': len(all_links),
            'candidates': len(ranked),
            'duplicates': len(duplicates),
            'pending': plan['add'] + plan['remove'],
            'thin': len(thin),
            'bom_lines': len(lines),
        },
        'links': all_links,
        'candidates': ranked,
        'by_hand': by_hand,
        'duplicates': duplicates,
        'sync': {
            'add': plan['add'],
            'remove': plan['remove'],
            'skipped': plan['skipped'],
            'lines': [
                {key: value for key, value in change.items() if key != 'remove_records'}
                for change in plan['lines'][:MAX_SYNC_LINES]
            ],
            'more': max(0, len(plan['lines']) - MAX_SYNC_LINES),
        },
        'thin': [{'part': pk, 'used_in': usage.get(pk, 0)} for pk in thin[:MAX_THIN]],
        'usage': {str(pk): count for pk, count in usage.items() if pk in mentioned},
        'parts': {str(pk): part_label(data, pk) for pk in mentioned},
        'settings': settings,
    }


def sync_parts(plugin, parts=None) -> dict:
    """Bring the BOM substitutes in step with the links (for some parts, or all)."""
    # Always from the parts as they are now: one may just have been made inactive
    data = load(plugin, use_cache=False)
    links: Links = store.load(valid=data.info.keys())

    return sync.sync(data, links, plugin_settings(plugin), sub_parts=parts)
