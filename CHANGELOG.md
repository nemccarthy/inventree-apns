# Changelog

All notable changes to this plugin are recorded here.
Versions follow [semantic versioning](https://semver.org).

## 0.1.0 - 2026-11-20

First release. Built and tested against InvenTree 1.7.3.

- Candidates: parts matched on their parameters, ranked by strength, with the
  direction in which one can replace the other and an attribute by attribute
  comparison
- Values compared whatever the notation; package and dielectric names
  normalised; attributes read from names and descriptions where a parameter
  is missing
- One-way and two-way links between parts, stored in part metadata
- BOM substitutes kept in step with the links, on a link change, on a new BOM
  line and on demand; substitutes set by hand are never changed
- Duplicate manufacturer part numbers, and hand-set substitutes which are
  missing on other BOMs
- Parameters filled in from DigiKey, LCSC and part descriptions
- Overview page and an Alternatives panel on part pages
- Qualification (AEC-Q, MIL, automotive grade) and operating temperature
  range are matched on: a qualified or wider-range part can replace one which
  is not, and not the reverse
- Comparison of two parts lists every field of both, not only the ones used
  for matching; parts are headed by manufacturer and MPN; two-way and one-way
  link buttons on every candidate
