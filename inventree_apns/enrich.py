"""Filling in the parameters the matching depends on.

Matching is only as good as the parameters of the parts. This module finds
values for a part from:

- 'digikey': the DigiKey Product Information API (v4), by manufacturer part
  number or DigiKey part number. Needs a client id and secret.
- 'lcsc': the product page data of lcsc.com, by LCSC part number (C12345).
  This is not a documented API and may change without notice.
- 'description': values which can be read out of the part name and
  description ('CAP 100nF 16V X7R 0402').

and proposes them as InvenTree parameters. A parameter which the part
already has is never changed.

The mapping (map_parameters, clean_value, format_quantity) is plain Python.
"""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import quote

from .matching import ROLES, normalise_mpn, normalise_name, role_for
from .parse import Quantity, derive_attributes, normalise_dielectric, parse_quantity

SOURCES = ('digikey', 'lcsc', 'description')
TIMEOUT = 15

# Units for the parameter templates this plugin creates
TEMPLATE_UNITS = {'F': 'F', 'Ω': 'ohm', 'H': 'H', 'Hz': 'Hz', 'V': 'V', 'W': 'W', 'A': 'A', '%': '%'}

_STEPS = ((1e9, 'G'), (1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p'))

# Capacitors are not given in mF, nor resistors in mΩ steps above 1 Ω, by convention
_NO_MILLI = ('F',)


def format_quantity(quantity: Quantity) -> str:
    """'100 nF', '10 kΩ', '62.5 mW', '10 %'."""
    value, unit = quantity.value, quantity.unit

    if unit in ('%', 'ppm', '°C', 'dB', 'bit', 'B', 'mm') or value == 0:
        return f'{value:.6g} {unit}'.strip()

    for scale, prefix in _STEPS:
        if prefix == 'm' and unit in _NO_MILLI:
            continue

        if abs(value) >= scale * 0.9999999:
            return f'{value / scale:.6g} {prefix}{unit}'.strip()

    return f'{value:.6g} {unit}'.strip()


def clean_value(value, role: Optional[str], units: str = '') -> Optional[str]:
    """The text to store for a found value. None if it cannot be stored.

    'units' is the unit of the parameter template; a value for a template
    with a unit has to be a quantity in that unit.
    """
    text = re.sub(r'\s+', ' ', str(value or '')).strip()

    if not text or text in ('-', '--', 'N/A', 'n/a', '*'):
        return None

    spec = ROLES.get(role or '')

    if spec and spec.kind == 'dielectric' and not units:
        return normalise_dielectric(text) or text

    quantity = parse_quantity(text)

    if units:
        wanted = parse_quantity(1, units)

        if quantity is None or wanted is None:
            return None

        if quantity.unit and quantity.unit != wanted.unit:
            return None

        return format_quantity(Quantity(quantity.value, wanted.unit))

    if spec and spec.kind == 'number' and quantity:
        if quantity.unit in ('', spec.unit):
            return format_quantity(Quantity(quantity.value, spec.unit))

    return text[:500]


def find_template(name: str, role: Optional[str], templates: list[dict]) -> Optional[dict]:
    """The existing parameter template a found value belongs to, if any."""
    usable = [template for template in templates if not template.get('checkbox') and not template.get('choices')]
    norm = normalise_name(name)

    for template in usable:
        if normalise_name(template['name']) == norm:
            return template

    if role in ROLES:
        same = [template for template in usable if template.get('role') == role]
        label = normalise_name(ROLES[role].label)

        for template in same:
            if normalise_name(template['name']) == label:
                return template

        if same:
            return same[0]

        # A value is never put into a template with a different meaning
        return None

    for template in usable:
        if template.get('role') in ROLES:
            continue

        if SequenceMatcher(None, normalise_name(template['name']), norm).ratio() >= 0.9:
            return template

    return None


def map_parameters(found: list[dict], templates: list[dict], existing: dict, create: bool = True) -> list[dict]:
    """Turn found values into proposed parameters.

    'found' is [{'name', 'value', 'source'}], best source first. 'existing'
    is {template id: value} for the parameters the part already has.

    Each proposal has an 'action': 'add' (to an existing template), 'create'
    (a new template is needed), 'keep' (the part already has a value) or
    'skip' (the value cannot be stored), and says why.
    """
    proposals = []
    taken = set()
    existing_roles = {}

    for template in templates:
        if template['pk'] in existing and template.get('role') in ROLES:
            existing_roles[template['role']] = template

    for item in found:
        name = str(item.get('name') or '').strip()
        role = role_for(name)

        if not name or role is None:
            continue

        template = find_template(name, role, templates)

        # The part may hold this attribute under another template of the same kind
        if template is None and role in existing_roles:
            template = existing_roles[role]

        key = ('t', template['pk']) if template else ('n', role if role in ROLES else normalise_name(name))

        if key in taken:
            continue

        taken.add(key)

        proposal = {
            'source': item.get('source', ''),
            'name': name,
            'found': str(item.get('value') or ''),
            'role': role if role in ROLES else None,
            'template': template['pk'] if template else None,
            'template_name': template['name'] if template else (ROLES[role].label if role in ROLES else name[:100]),
            'units': template['units'] if template else '',
            'value': None,
            'current': None,
        }

        if template and template['pk'] in existing:
            proposal.update(action='keep', current=existing[template['pk']], reason='Already set')
            proposals.append(proposal)
            continue

        if template is None:
            spec = ROLES.get(role)
            proposal['units'] = TEMPLATE_UNITS.get(spec.unit, '') if spec and spec.kind == 'number' else ''

        value = clean_value(item.get('value'), role, proposal['units'])

        if value is None:
            proposal.update(
                action='skip',
                reason=f'Not a value in {proposal["units"]}' if proposal['units'] else 'Empty',
            )
        elif template is None and not create:
            proposal.update(action='skip', value=value, reason='No matching parameter template')
        else:
            proposal.update(action='add' if template else 'create', value=value, reason='')

        proposals.append(proposal)

    return proposals


# --- Sources ---------------------------------------------------------------


class SourceError(Exception):
    """A source could not be reached, or refused the request."""


_tokens: dict = {}


class DigiKey:
    """DigiKey Product Information API v4 (2-legged OAuth)."""

    BASE = 'https://api.digikey.com'

    def __init__(self, client_id: str, client_secret: str, site: str = 'AU', currency: str = 'AUD'):
        self.client_id = client_id
        self.client_secret = client_secret
        self.site = site or 'US'
        self.currency = currency or 'USD'

    def _token(self) -> str:
        import requests

        cached = _tokens.get(self.client_id)

        if cached and cached[1] > time.time() + 30:
            return cached[0]

        response = requests.post(
            f'{self.BASE}/v1/oauth2/token',
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials',
            },
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            raise SourceError(f'DigiKey refused the client id and secret ({response.status_code})')

        data = response.json()
        token = data.get('access_token')

        if not token:
            raise SourceError('DigiKey did not return an access token')

        _tokens[self.client_id] = (token, time.time() + float(data.get('expires_in') or 600))

        return token

    def _headers(self) -> dict:
        return {
            'Authorization': f'Bearer {self._token()}',
            'X-DIGIKEY-Client-Id': self.client_id,
            'X-DIGIKEY-Locale-Site': self.site,
            'X-DIGIKEY-Locale-Language': 'en',
            'X-DIGIKEY-Locale-Currency': self.currency,
            'Accept': 'application/json',
        }

    def lookup(self, number: str) -> Optional[dict]:
        """Product details for a manufacturer or DigiKey part number."""
        import requests

        response = requests.get(
            f'{self.BASE}/products/v4/search/{quote(number, safe="")}/productdetails',
            headers=self._headers(),
            timeout=TIMEOUT,
        )

        if response.status_code == 404:
            return None

        if response.status_code == 429:
            raise SourceError('DigiKey rate limit reached; try again later')

        if response.status_code != 200:
            raise SourceError(f'DigiKey returned {response.status_code} for {number}')

        return parse_digikey(response.json(), number)


def parse_digikey(payload: dict, number: str = '') -> Optional[dict]:
    """Pick the parameters out of a DigiKey 'productdetails' response."""
    product = (payload or {}).get('Product') if isinstance(payload, dict) else None

    if not isinstance(product, dict):
        return None

    parameters = []

    for item in product.get('Parameters') or []:
        name = item.get('ParameterText') or item.get('Parameter')
        value = item.get('ValueText') or item.get('Value')

        if name and value and str(value).strip() not in ('-', ''):
            parameters.append({'name': str(name), 'value': str(value), 'source': 'digikey'})

    manufacturer = product.get('Manufacturer') or {}
    description = product.get('Description') or {}

    return {
        'source': 'digikey',
        'number': number,
        'mpn': product.get('ManufacturerProductNumber') or '',
        'manufacturer': manufacturer.get('Name') if isinstance(manufacturer, dict) else '',
        'description': description.get('ProductDescription') if isinstance(description, dict) else '',
        'url': product.get('ProductUrl') or '',
        'parameters': parameters,
    }


class Lcsc:
    """Product data from lcsc.com, by LCSC part number. Not a documented API."""

    URL = 'https://wmsc.lcsc.com/ftps/wm/product/detail'

    def lookup(self, number: str) -> Optional[dict]:
        import requests

        response = requests.get(
            self.URL,
            params={'productCode': number},
            headers={'User-Agent': 'Mozilla/5.0 (inventree-apns)', 'Accept': 'application/json'},
            timeout=TIMEOUT,
        )

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            raise SourceError(f'LCSC returned {response.status_code} for {number}')

        try:
            payload = response.json()
        except ValueError:
            raise SourceError('LCSC did not return product data')

        return parse_lcsc(payload, number)


def parse_lcsc(payload: dict, number: str = '') -> Optional[dict]:
    """Pick the parameters out of an LCSC product detail response."""
    result = (payload or {}).get('result') if isinstance(payload, dict) else None

    if not isinstance(result, dict) or not result:
        return None

    parameters = []

    package = result.get('encapStandard')

    if package and str(package).strip() not in ('-', ''):
        parameters.append({'name': 'Package', 'value': str(package), 'source': 'lcsc'})

    for item in result.get('paramVOList') or []:
        name = item.get('paramNameEn')
        value = item.get('paramValueEn')

        if name and value and str(value).strip() not in ('-', ''):
            parameters.append({'name': str(name), 'value': str(value), 'source': 'lcsc'})

    return {
        'source': 'lcsc',
        'number': number,
        'mpn': result.get('productModel') or '',
        'manufacturer': result.get('brandNameEn') or '',
        'description': result.get('productIntroEn') or '',
        'url': f'https://www.lcsc.com/product-detail/{number}.html' if number else '',
        'parameters': parameters,
    }


_LCSC_NUMBER = re.compile(r'^C\d{3,}$', re.IGNORECASE)


def lcsc_numbers(skus: list[dict]) -> list[str]:
    """The LCSC part numbers among the supplier part numbers of a part."""
    found = []

    for item in skus:
        sku = str(item.get('sku') or '').strip()
        supplier = str(item.get('supplier') or '').lower()

        if _LCSC_NUMBER.match(sku) and ('lcsc' in supplier or 'jlc' in supplier or not supplier):
            found.append(sku.upper())

    return list(dict.fromkeys(found))


def digikey_numbers(mpns: list[dict], skus: list[dict]) -> list[str]:
    """Numbers to look up at DigiKey: its own part numbers first, then MPNs."""
    found = [
        str(item.get('sku')).strip()
        for item in skus
        if 'digi' in str(item.get('supplier') or '').lower() and item.get('sku')
    ]
    found += [str(item.get('mpn')).strip() for item in mpns if item.get('mpn')]

    return list(dict.fromkeys(filter(None, found)))


def description_source(name: str, description: str) -> dict:
    """Values read out of the name and description of the part."""
    return {
        'source': 'description',
        'number': '',
        'parameters': [
            {'name': ROLES[role].label, 'value': value, 'source': 'description'}
            for role, value in derive_attributes(name, description).items()
        ],
    }


def gather(plugin, part: dict, sources=None) -> tuple[list[dict], list[dict]]:
    """Ask each source about a part.

    Returns (found values, best source first) and a report per source:
    [{'source', 'status': 'found' | 'none' | 'off' | 'error', 'detail'}].
    """
    wanted = [source for source in SOURCES if sources is None or source in sources]
    found: list[dict] = []
    report = []

    if 'digikey' in wanted:
        client_id = plugin.get_setting('DIGIKEY_CLIENT_ID')
        secret = plugin.get_setting('DIGIKEY_CLIENT_SECRET')
        numbers = digikey_numbers(part.get('mpns') or [], part.get('skus') or [])

        if not (client_id and secret):
            report.append({'source': 'digikey', 'status': 'off', 'detail': 'No client id and secret set'})
        elif not numbers:
            report.append({'source': 'digikey', 'status': 'none', 'detail': 'The part has no manufacturer part number'})
        else:
            client = DigiKey(
                client_id,
                secret,
                str(plugin.get_setting('DIGIKEY_SITE') or 'AU'),
                str(plugin.get_setting('DIGIKEY_CURRENCY') or 'AUD'),
            )
            report.append(_ask(client, numbers[:3], 'digikey', found, check_mpn=part.get('mpns') or []))

    if 'lcsc' in wanted:
        numbers = lcsc_numbers(part.get('skus') or [])

        if not plugin.get_setting('LCSC_ENABLED'):
            report.append({'source': 'lcsc', 'status': 'off', 'detail': 'Turned off in the plugin settings'})
        elif not numbers:
            report.append({'source': 'lcsc', 'status': 'none', 'detail': 'The part has no LCSC part number'})
        else:
            report.append(_ask(Lcsc(), numbers[:2], 'lcsc', found))

    if 'description' in wanted:
        result = description_source(part.get('name') or '', part.get('description') or '')
        found.extend(result['parameters'])
        report.append({
            'source': 'description',
            'status': 'found' if result['parameters'] else 'none',
            'detail': f'{len(result["parameters"])} values read from the name and description',
        })

    return found, report


def _ask(client, numbers: list[str], source: str, found: list[dict], check_mpn=()) -> dict:
    known = {normalise_mpn(item.get('mpn')) for item in check_mpn if item.get('mpn')}

    try:
        for number in numbers:
            result = client.lookup(number)

            if not result or not result['parameters']:
                continue

            # Looked up by MPN: make sure the answer is for that part
            if known and result.get('mpn') and normalise_mpn(result['mpn']) not in known:
                if normalise_mpn(number) in known:
                    continue

            found.extend(result['parameters'])

            return {
                'source': source,
                'status': 'found',
                'detail': f'{len(result["parameters"])} values for {result.get("mpn") or number}',
                'url': result.get('url') or '',
            }
    except SourceError as error:
        return {'source': source, 'status': 'error', 'detail': str(error)}
    except Exception as error:  # network errors, unexpected data
        return {'source': source, 'status': 'error', 'detail': f'{type(error).__name__}: {error}'[:200]}

    return {'source': source, 'status': 'none', 'detail': f'Nothing found for {", ".join(numbers)}'}


def propose(plugin, data, pk: int, sources=None, create: bool = True) -> dict:
    """Proposed parameters for one part."""
    from django.contrib.contenttypes.models import ContentType

    from common.models import Parameter
    from part.models import Part

    from .loader import parameter_templates

    part = data.info.get(pk)

    if part is None:
        return {'part': pk, 'proposals': [], 'report': [], 'error': 'Part not found'}

    found, report = gather(plugin, part, sources)
    part_type = ContentType.objects.get_for_model(Part)

    existing = dict(
        Parameter.objects.filter(model_type=part_type, model_id=pk).values_list('template_id', 'data')
    )

    return {
        'part': pk,
        'proposals': map_parameters(found, parameter_templates(), existing, create=create),
        'report': report,
    }


def apply(pk: int, proposals: list[dict], user=None, only=None) -> dict:
    """Store the proposed parameters. Returns what was added, and what failed."""
    from django.contrib.contenttypes.models import ContentType
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from common.models import Parameter, ParameterTemplate
    from part.models import Part

    part_type = ContentType.objects.get_for_model(Part)
    added = []
    errors = []
    chosen = set(only) if only is not None else None

    for proposal in proposals:
        if proposal.get('action') not in ('add', 'create') or proposal.get('value') is None:
            continue

        if chosen is not None and proposal['template_name'] not in chosen:
            continue

        try:
            with transaction.atomic():
                if proposal['action'] == 'create':
                    template = ParameterTemplate.objects.filter(
                        name__iexact=proposal['template_name']
                    ).first()

                    if template is None:
                        template = ParameterTemplate(
                            name=proposal['template_name'],
                            units=proposal.get('units') or '',
                            description='Added by the Alternate Parts plugin',
                        )
                        template.full_clean()
                        template.save()
                else:
                    template = ParameterTemplate.objects.get(pk=proposal['template'])

                if Parameter.objects.filter(
                    model_type=part_type, model_id=pk, template=template
                ).exists():
                    continue

                parameter = Parameter(
                    template=template,
                    model_type=part_type,
                    model_id=pk,
                    data=proposal['value'],
                    note=f'From {proposal.get("source")}'[:500] if proposal.get('source') else '',
                )

                if user is not None and hasattr(parameter, 'updated_by'):
                    parameter.updated_by = user

                parameter.full_clean()
                parameter.save()

            added.append({'name': template.name, 'value': proposal['value']})
        except ValidationError as error:
            errors.append({'name': proposal['template_name'], 'error': '; '.join(error.messages)})
        except Exception as error:
            errors.append({'name': proposal['template_name'], 'error': f'{type(error).__name__}: {error}'[:200]})

    return {'added': added, 'errors': errors}
