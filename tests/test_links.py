"""One-way and two-way links, and the BOM substitutes they lead to."""

from inventree_apns.links import Link, Links, desired_substitutes, plan_line


def links(*items):
    return Links(links=[Link(part, alternate, two_way) for part, alternate, two_way in items])


def test_one_way_link_holds_in_one_direction():
    book = links((1, 2, False))

    assert set(book.replacements(1)) == {2}
    assert set(book.replacements(2)) == set()
    assert set(book.replaces(2)) == {1}
    assert set(book.replaces(1)) == set()


def test_two_way_link_holds_in_both_directions():
    book = links((1, 2, True))

    assert set(book.replacements(1)) == {2}
    assert set(book.replacements(2)) == {1}


def test_links_are_not_chained():
    book = links((1, 2, True), (2, 3, True))

    assert set(book.replacements(1)) == {2}
    assert set(book.replacements(2)) == {1, 3}
    assert set(book.replacements(3)) == {2}


def test_relation_is_read_from_either_part():
    book = links((1, 2, False), (1, 3, True))

    assert sorted((other, relation) for other, relation, _link in book.of(1)) == [(2, 'forward'), (3, 'both')]
    assert [(other, relation) for other, relation, _link in book.of(2)] == [(1, 'reverse')]
    assert [(other, relation) for other, relation, _link in book.of(3)] == [(1, 'both')]
    assert book.of(4) == []


def test_find_and_dismissed_ignore_the_order():
    book = links((1, 2, False))
    book.dismissed.add(frozenset((3, 4)))

    assert book.find(2, 1) is book.links[0]
    assert book.find(1, 3) is None
    assert book.is_dismissed(4, 3)
    assert not book.is_dismissed(1, 2)
    assert book.linked_pairs() == {frozenset((1, 2))}
    assert book.parts() == {1, 2}


def test_desired_substitutes():
    book = links((1, 2, False), (1, 3, True), (4, 1, True))

    assert desired_substitutes(book, 1) == {2, 3, 4}
    # Only parts which may be substitutes, and never the assembly itself
    assert desired_substitutes(book, 1, usable={2, 4}) == {2, 4}
    assert desired_substitutes(book, 1, skip={3}) == {2, 4}
    assert desired_substitutes(book, 2) == set()
    assert desired_substitutes(book, 3) == {1}


def test_plan_line_adds_what_is_missing():
    assert plan_line({2, 3}, {}) == ({2, 3}, set())
    assert plan_line({2, 3}, {2: True}) == ({3}, set())


def test_plan_line_removes_only_what_the_plugin_added():
    # 5 was added from a link which is gone; 6 was added by hand
    assert plan_line({2}, {2: True, 5: True, 6: False}) == (set(), {5})


def test_plan_line_leaves_a_hand_set_substitute_which_is_also_linked():
    assert plan_line({2}, {2: False}) == (set(), set())
    assert plan_line(set(), {2: False}) == (set(), set())
