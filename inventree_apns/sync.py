"""Keeping BOM substitutes in step with the links.

A link 'B can be used in place of A' becomes a substitute B on every BOM
line whose part is A. Substitutes added by this plugin are marked in their
metadata, so that only those are removed again when a link goes away;
substitutes which were added by hand are never touched.
"""

from __future__ import annotations

from .links import Links, desired_substitutes, plan_line
from .loader import Data, load_bom_lines
from .store import META_KEY


def usable(data: Data, include_inactive: bool = False) -> set:
    """Parts which may be added to a BOM line as a substitute."""
    return {
        pk
        for pk, part in data.info.items()
        if part['component'] and (part['active'] or include_inactive)
    }


def plan(data: Data, links: Links, settings: dict, sub_parts=None, line: int | None = None) -> dict:
    """Work out which substitutes have to be added and removed.

    Returns {'lines': [...], 'add': n, 'remove': n, 'skipped': n}. Each line
    lists the BOM line, the substitutes to add and the substitute records to
    remove.
    """
    allowed = usable(data, settings.get('include_inactive', False))
    changes = []
    add_total = remove_total = skipped = 0

    for bom_line in load_bom_lines(sub_parts=sub_parts, line=line):
        wanted = desired_substitutes(links, bom_line.sub_part, allowed, skip={bom_line.assembly})
        existing = {part: managed for part, (_record, managed) in bom_line.substitutes.items()}
        add, remove = plan_line(wanted, existing)

        if not add and not remove:
            continue

        locked = bool(bom_line.locked and settings.get('skip_locked'))

        if locked:
            skipped += 1
        else:
            add_total += len(add)
            remove_total += len(remove)

        changes.append({
            'line': bom_line.pk,
            'assembly': bom_line.assembly,
            'sub_part': bom_line.sub_part,
            'reference': bom_line.reference,
            'add': sorted(add),
            'remove': sorted(remove),
            'remove_records': sorted(bom_line.substitutes[part][0] for part in remove),
            'skipped': locked,
        })

    changes.sort(key=lambda change: (change['assembly'], change['line']))

    return {'lines': changes, 'add': add_total, 'remove': remove_total, 'skipped': skipped}


def apply(changes: dict) -> dict:
    """Carry out a plan. Returns what was done, and what could not be."""
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from part.models import BomItemSubstitute

    added = removed = 0
    errors = []

    for change in changes['lines']:
        if change['skipped']:
            continue

        with transaction.atomic():
            if change['remove_records']:
                # Only ever records which this plugin added
                for record in BomItemSubstitute.objects.filter(
                    pk__in=change['remove_records'], bom_item_id=change['line']
                ):
                    if (record.metadata or {}).get(META_KEY, {}).get('managed'):
                        record.delete()
                        removed += 1

            for part in change['add']:
                try:
                    with transaction.atomic():
                        BomItemSubstitute(
                            bom_item_id=change['line'],
                            part_id=part,
                            metadata={META_KEY: {'managed': True}},
                        ).save()

                    added += 1
                except ValidationError as error:
                    errors.append({
                        'line': change['line'],
                        'part': part,
                        'error': '; '.join(error.messages),
                    })

    return {'added': added, 'removed': removed, 'errors': errors}


def sync(data: Data, links: Links, settings: dict, sub_parts=None, line: int | None = None) -> dict:
    """Plan and apply in one go."""
    changes = plan(data, links, settings, sub_parts=sub_parts, line=line)
    result = apply(changes)

    return {**result, 'skipped': changes['skipped']}
