"""Reading parts, parameters, BOM lines and substitutes from InvenTree."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from .matching import Catalogue, build_features, role_for
from .store import META_KEY, SLUG

CACHE_SECONDS = 60

_cache: dict = {}


def clear_cache() -> None:
    """Forget the loaded parts (after parameters have been changed)."""
    _cache.clear()


def plugin_settings(plugin) -> dict:
    """The plugin settings, as plain values."""

    def number(key: str, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(plugin.get_setting(key))))
        except (TypeError, ValueError):
            return default

    def flag(key: str) -> bool:
        return bool(plugin.get_setting(key))

    return {
        'min_strength': number('MIN_STRENGTH', 60, 0, 99),
        'use_description': flag('USE_DESCRIPTION'),
        'include_assemblies': flag('INCLUDE_ASSEMBLIES'),
        'include_inactive': flag('INCLUDE_INACTIVE'),
        'auto_sync': flag('AUTO_SYNC'),
        'skip_locked': flag('SKIP_LOCKED'),
        'create_templates': flag('CREATE_TEMPLATES'),
        'digikey': bool(plugin.get_setting('DIGIKEY_CLIENT_ID') and plugin.get_setting('DIGIKEY_CLIENT_SECRET')),
        'lcsc': flag('LCSC_ENABLED'),
    }


@dataclass
class Data:
    """Everything the plugin reads about the parts."""

    catalogue: Catalogue
    # Display details of every part: {pk: {...}}
    info: dict = field(default_factory=dict)
    # Parts which may be offered as candidates
    eligible: set = field(default_factory=set)
    # Attributes of every part, including those not offered as candidates
    features: dict = field(default_factory=dict)
    generated: float = 0.0
    # The strongest pairs of the whole catalogue, worked out once per load
    _pairs: dict = field(default_factory=dict)

    def pairs(self, minimum: int, limit: int) -> list:
        """The strongest matches across the catalogue (kept until the parts are re-read)."""
        key = (minimum, limit)

        if key not in self._pairs:
            self._pairs[key] = self.catalogue.pairs(minimum=minimum, limit=limit)

        return self._pairs[key]


def _category_paths() -> tuple[dict, dict]:
    """{category: (ids from the top down to it)} and {category: path string}."""
    from part.models import PartCategory

    rows = list(PartCategory.objects.values_list('pk', 'parent_id', 'pathstring', 'name'))
    parents = {pk: parent for pk, parent, _path, _name in rows}
    names = {pk: path or name for pk, _parent, path, name in rows}
    paths = {}

    for pk in parents:
        path = []
        node = pk
        guard = 0

        while node is not None and guard < 50:
            path.append(node)
            node = parents.get(node)
            guard += 1

        paths[pk] = tuple(reversed(path))

    return paths, names


def load(plugin, use_cache: bool = True) -> Data:
    """Load every part with its parameters and part numbers."""
    settings = plugin_settings(plugin)
    key = (settings['use_description'], settings['include_assemblies'], settings['include_inactive'])
    cached = _cache.get('data')

    if use_cache and cached and cached[0] == key and time.time() - cached[1].generated < CACHE_SECONDS:
        return cached[1]

    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Sum

    from common.models import Parameter
    from company.models import ManufacturerPart, SupplierPart
    from part.models import Part
    from stock.models import StockItem

    paths, category_names = _category_paths()

    parameters = defaultdict(list)
    part_type = ContentType.objects.get_for_model(Part)

    for row in Parameter.objects.filter(model_type=part_type).values(
        'model_id', 'template_id', 'template__name', 'template__units', 'data', 'data_numeric'
    ):
        parameters[row['model_id']].append({
            'template': row['template_id'],
            'name': row['template__name'],
            'units': row['template__units'] or '',
            'data': row['data'],
            'numeric': row['data_numeric'],
        })

    mpns = defaultdict(list)

    for part, manufacturer, mpn in ManufacturerPart.objects.exclude(MPN=None).exclude(MPN='').values_list(
        'part_id', 'manufacturer__name', 'MPN'
    ):
        mpns[part].append({'manufacturer': manufacturer or '', 'mpn': mpn})

    skus = defaultdict(list)

    for part, supplier, sku in SupplierPart.objects.exclude(SKU=None).exclude(SKU='').values_list(
        'part_id', 'supplier__name', 'SKU'
    ):
        skus[part].append({'supplier': supplier or '', 'sku': sku})

    stock = {
        row['part']: float(row['total'] or 0)
        for row in StockItem.objects.filter(StockItem.IN_STOCK_FILTER)
        .values('part')
        .annotate(total=Sum('quantity'))
    }

    features = []
    info = {}
    eligible = set()

    rows = Part.objects.values(
        'pk',
        'name',
        'IPN',
        'description',
        'revision',
        'category_id',
        'active',
        'component',
        'assembly',
        'virtual',
        'is_template',
        'locked',
        'units',
    )

    for row in rows:
        pk = row['pk']
        params = parameters.get(pk, [])

        feature = build_features(
            pk,
            name=row['name'] or '',
            ipn=row['IPN'] or '',
            description=row['description'] or '',
            category=row['category_id'],
            category_path=paths.get(row['category_id'], ()),
            mpns=[item['mpn'] for item in mpns.get(pk, [])],
            parameters=params,
            active=bool(row['active']),
            use_description=settings['use_description'],
        )
        features.append(feature)

        # How much the matching has to go on, from real parameters
        known = [attr for attr in feature.attrs.values() if not attr.derived]

        info[pk] = {
            'pk': pk,
            'name': row['name'] or '',
            'ipn': row['IPN'] or '',
            'description': row['description'] or '',
            'revision': row['revision'] or '',
            'category': row['category_id'],
            'category_name': category_names.get(row['category_id'], ''),
            'active': bool(row['active']),
            'component': bool(row['component']),
            'assembly': bool(row['assembly']),
            'locked': bool(row['locked']),
            'units': row['units'] or '',
            'stock': stock.get(pk, 0.0),
            'mpns': mpns.get(pk, []),
            'skus': skus.get(pk, []),
            'parameters': len(params),
            'known': len(known),
            'derived': len(feature.attrs) - len(known),
        }

        if (
            row['component']
            and not row['virtual']
            and not row['is_template']
            and (row['active'] or settings['include_inactive'])
            and (not row['assembly'] or settings['include_assemblies'])
        ):
            eligible.add(pk)

    data = Data(
        catalogue=Catalogue(feature for feature in features if feature.pk in eligible),
        info=info,
        eligible=eligible,
        features={feature.pk: feature for feature in features},
        generated=time.time(),
    )

    _cache['data'] = (key, data)

    return data


@dataclass
class BomLine:
    """A BOM line, with its substitutes."""

    pk: int
    assembly: int
    sub_part: int
    reference: str = ''
    locked: bool = False
    # {substitute part: (substitute record id, added by this plugin)}
    substitutes: dict = field(default_factory=dict)


def is_managed(metadata) -> bool:
    """True if a substitute record was added by this plugin."""
    data = (metadata or {}).get(META_KEY)

    return bool(isinstance(data, dict) and data.get('managed'))


def load_bom_lines(sub_parts=None, line: int | None = None) -> list[BomLine]:
    """BOM lines (for the given component parts, or all of them)."""
    from part.models import BomItem, BomItemSubstitute

    items = BomItem.objects.all()

    if line is not None:
        items = items.filter(pk=line)
    elif sub_parts is not None:
        items = items.filter(sub_part_id__in=list(sub_parts))

    lines = {
        row['pk']: BomLine(
            pk=row['pk'],
            assembly=row['part_id'],
            sub_part=row['sub_part_id'],
            reference=row['reference'] or '',
            locked=bool(row['part__locked']),
        )
        for row in items.values('pk', 'part_id', 'sub_part_id', 'reference', 'part__locked')
    }

    substitutes = BomItemSubstitute.objects.all()

    if line is not None or sub_parts is not None:
        substitutes = substitutes.filter(bom_item_id__in=list(lines))

    for row in substitutes.values('pk', 'bom_item_id', 'part_id', 'metadata'):
        target = lines.get(row['bom_item_id'])

        if target:
            target.substitutes[row['part_id']] = (row['pk'], is_managed(row['metadata']))

    return list(lines.values())


def parameter_templates() -> list[dict]:
    """The parameter templates which can be used on parts."""
    from django.contrib.contenttypes.models import ContentType
    from django.db.models import Q

    from common.models import ParameterTemplate
    from part.models import Part

    part_type = ContentType.objects.get_for_model(Part)

    return [
        {
            'pk': row['pk'],
            'name': row['name'],
            'units': row['units'] or '',
            'checkbox': bool(row['checkbox']),
            'choices': bool(row['choices'] or row['selectionlist_id']),
            'role': role_for(row['name']),
        }
        for row in ParameterTemplate.objects.filter(Q(model_type=None) | Q(model_type=part_type))
        .filter(enabled=True)
        .values('pk', 'name', 'units', 'checkbox', 'choices', 'selectionlist_id')
    ]


__all__ = [
    'SLUG',
    'BomLine',
    'Data',
    'clear_cache',
    'load',
    'load_bom_lines',
    'parameter_templates',
    'plugin_settings',
]
