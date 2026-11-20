"""Alternate links between parts.

Plain Python, with no Django or InvenTree imports.

A link says that one part (the alternate) can be used in place of another
(the part). A one-way link only holds in that direction; a two-way link means
the two parts are interchangeable.

Links are not chained: if B can replace A and C can replace B, C is not taken
to replace A unless that link is made as well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class Link:
    """'alternate' can be used in place of 'part' (and the reverse, if two-way)."""

    part: int
    alternate: int
    two_way: bool = False
    note: str = ''
    by: str = ''
    at: str = ''

    def pair(self) -> frozenset:
        return frozenset((self.part, self.alternate))

    def as_dict(self) -> dict:
        return {
            'part': self.part,
            'alternate': self.alternate,
            'two_way': self.two_way,
            'note': self.note,
            'by': self.by,
            'at': self.at,
        }


@dataclass
class Links:
    """All the links, and the pairs which were dismissed as candidates."""

    links: list = field(default_factory=list)
    dismissed: set = field(default_factory=set)

    def find(self, a: int, b: int) -> Optional[Link]:
        """The link between two parts, whichever way round it is stored."""
        pair = frozenset((a, b))

        for link in self.links:
            if link.pair() == pair:
                return link

        return None

    def is_dismissed(self, a: int, b: int) -> bool:
        return frozenset((a, b)) in self.dismissed

    def replacements(self, pk: int) -> dict:
        """Parts which can be used in place of 'pk': {alternate: link}."""
        found = {}

        for link in self.links:
            if link.part == pk:
                found[link.alternate] = link
            elif link.two_way and link.alternate == pk:
                found[link.part] = link

        return found

    def replaces(self, pk: int) -> dict:
        """Parts which 'pk' can be used in place of: {part: link}."""
        found = {}

        for link in self.links:
            if link.alternate == pk:
                found[link.part] = link
            elif link.two_way and link.part == pk:
                found[link.alternate] = link

        return found

    def of(self, pk: int) -> list:
        """Every link which involves 'pk', with how it reads from that part.

        Returns [(other, relation, link)] where relation is 'both' (the two
        are interchangeable), 'forward' (the other part can replace this
        one) or 'reverse' (this part can replace the other).
        """
        found = []

        for link in self.links:
            if link.part == pk:
                found.append((link.alternate, 'both' if link.two_way else 'forward', link))
            elif link.alternate == pk:
                found.append((link.part, 'both' if link.two_way else 'reverse', link))

        return found

    def linked_pairs(self) -> set:
        return {link.pair() for link in self.links}

    def parts(self) -> set:
        """Every part which has a link."""
        found = set()

        for link in self.links:
            found.update((link.part, link.alternate))

        return found


def desired_substitutes(links: Links, sub_part: int, usable: Optional[Iterable[int]] = None, skip: Iterable[int] = ()) -> set:
    """The parts which should be substitutes on a BOM line for 'sub_part'."""
    wanted = set(links.replacements(sub_part)) - {sub_part} - set(skip)

    if usable is not None:
        wanted &= set(usable)

    return wanted


def plan_line(wanted: set, existing: dict) -> tuple[set, set]:
    """What to change on one BOM line.

    'existing' is {substitute part: managed}, where managed is True for a
    substitute this plugin added. Substitutes added by hand are never removed.

    Returns (parts to add, parts to remove).
    """
    add = wanted - set(existing)
    remove = {part for part, managed in existing.items() if managed and part not in wanted}

    return add, remove
