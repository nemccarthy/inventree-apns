"""Where the links are kept.

Nothing here needs its own database tables. A link is stored in the metadata
of the part it is made on, under the key 'apns':

    {"apns": {
        "alternates": [{"part": 45, "two_way": true, "note": "...",
                        "by": "nate", "at": "2026-11-20T10:00:00+00:00"}],
        "dismissed": [46, 47]
    }}

"alternates" lists the parts which can be used in place of this one.
"dismissed" lists candidates which were looked at and turned down; a pair is
recorded on the part with the lower id.
"""

from __future__ import annotations

from typing import Iterable, Optional

from rest_framework.exceptions import ValidationError

from .links import Link, Links

SLUG = 'apns'
META_KEY = 'apns'
MAX_NOTE = 250


def _clean(data) -> dict:
    data = data if isinstance(data, dict) else {}

    return {
        'alternates': [item for item in data.get('alternates') or [] if isinstance(item, dict)],
        'dismissed': [item for item in data.get('dismissed') or [] if isinstance(item, int)],
        **{key: value for key, value in data.items() if key not in ('alternates', 'dismissed')},
    }


def load(valid: Optional[Iterable[int]] = None) -> Links:
    """Read every link. Links to parts which no longer exist are left out."""
    from part.models import Part

    known = set(valid) if valid is not None else set(Part.objects.values_list('pk', flat=True))
    result = Links()
    seen = set()

    rows = Part.objects.filter(metadata__has_key=META_KEY).values_list('pk', 'metadata')

    for pk, metadata in rows:
        data = _clean((metadata or {}).get(META_KEY))

        for item in data['alternates']:
            try:
                other = int(item.get('part'))
            except (TypeError, ValueError):
                continue

            pair = frozenset((pk, other))

            if other == pk or other not in known or pair in seen:
                continue

            seen.add(pair)
            result.links.append(
                Link(
                    part=pk,
                    alternate=other,
                    two_way=bool(item.get('two_way')),
                    note=str(item.get('note') or ''),
                    by=str(item.get('by') or ''),
                    at=str(item.get('at') or ''),
                )
            )

        for other in data['dismissed']:
            if other in known and other != pk:
                result.dismissed.add(frozenset((pk, other)))

    return result


def _update(pk: int, change) -> None:
    """Change the stored data of one part, without touching anything else on it."""
    from django.db import transaction

    from part.models import Part

    with transaction.atomic():
        rows = list(
            Part.objects.select_for_update().filter(pk=pk).values_list('metadata', flat=True)
        )

        if not rows:
            raise ValidationError({'part': f'Part {pk} does not exist'})

        metadata = dict(rows[0] or {})
        data = _clean(metadata.get(META_KEY))
        change(data)

        if data['alternates'] or data['dismissed'] or len(data) > 2:
            metadata[META_KEY] = data
        else:
            metadata.pop(META_KEY, None)

        Part.objects.filter(pk=pk).update(metadata=metadata)


def _drop(pk: int, other: int) -> None:
    def change(data):
        data['alternates'] = [item for item in data['alternates'] if item.get('part') != other]

    _update(pk, change)


def check_parts(part, alternate) -> tuple[int, int]:
    """Validate the two ends of a link. Returns their ids."""
    from part.models import Part

    try:
        part, alternate = int(part), int(alternate)
    except (TypeError, ValueError):
        raise ValidationError({'part': 'A part and an alternate are required'})

    if part == alternate:
        raise ValidationError({'alternate': 'A part cannot be its own alternate'})

    found = set(Part.objects.filter(pk__in=(part, alternate)).values_list('pk', flat=True))

    if part not in found:
        raise ValidationError({'part': f'Part {part} does not exist'})

    if alternate not in found:
        raise ValidationError({'alternate': f'Part {alternate} does not exist'})

    return part, alternate


def set_link(part, alternate, two_way: bool = False, note: str = '', user=None) -> Link:
    """Make (or change) the link 'alternate can be used in place of part'.

    Any link already held between the two parts is replaced, whichever way
    round it was.
    """
    from django.utils import timezone

    part, alternate = check_parts(part, alternate)
    note = str(note or '').strip()[:MAX_NOTE]

    link = Link(
        part=part,
        alternate=alternate,
        two_way=bool(two_way),
        note=note,
        by=getattr(user, 'username', '') or '',
        at=timezone.now().replace(microsecond=0).isoformat(),
    )

    # Remove the reverse link, if there is one
    _drop(alternate, part)

    def change(data):
        data['alternates'] = [item for item in data['alternates'] if item.get('part') != alternate]
        data['alternates'].append({
            'part': alternate,
            'two_way': link.two_way,
            'note': link.note,
            'by': link.by,
            'at': link.at,
        })

    _update(part, change)

    # A pair which is linked is no longer dismissed
    set_dismissed(part, alternate, False)

    return link


def remove_link(part, alternate) -> None:
    """Remove the link between two parts, whichever way round it is stored."""
    part, alternate = check_parts(part, alternate)

    _drop(part, alternate)
    _drop(alternate, part)


def set_dismissed(part, other, dismissed: bool = True) -> None:
    """Turn a candidate down (or bring it back)."""
    part, other = check_parts(part, other)
    low, high = sorted((part, other))

    def change(data):
        data['dismissed'] = [item for item in data['dismissed'] if item != high]

        if dismissed:
            data['dismissed'].append(high)

    _update(low, change)
