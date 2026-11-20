"""Alternative Parts plugin for InvenTree.

Finds parts which could stand in for each other by comparing their
parameters, lets you link them one-way or two-way, and keeps the substitutes
of every BOM line in step with those links.
"""

from plugin import InvenTreePlugin
from plugin.mixins import EventMixin, SettingsMixin, UrlsMixin, UserInterfaceMixin

from . import PLUGIN_VERSION

# Compiled frontend: a single file which exports every entry point
FRONTEND = 'Apns.js'

# A BOM line was added or changed: give it the substitutes its part is linked to
BOM_EVENTS = ('part_bomitem.created', 'part_bomitem.saved')


class ApnsPlugin(EventMixin, SettingsMixin, UrlsMixin, UserInterfaceMixin, InvenTreePlugin):
    """Alternative part numbers for InvenTree."""

    # Plugin metadata
    TITLE = 'Alternative Parts'
    NAME = 'Alternative Parts'
    SLUG = 'apns'
    DESCRIPTION = 'Find, link and use alternative parts: ranked candidates, one-way and two-way links, BOM substitutes kept in step'
    VERSION = PLUGIN_VERSION

    AUTHOR = 'EdgeMachines'
    WEBSITE = 'https://github.com/nemccarthy/inventree-apns'
    LICENSE = 'MIT'

    # Developed and tested against InvenTree 1.7.3
    MIN_VERSION = '1.7.0'

    SETTINGS = {
        'MIN_STRENGTH': {
            'name': 'Weakest candidate to show (%)',
            'description': 'Candidates with a lower match strength are left out',
            'validator': int,
            'default': 60,
        },
        'USE_DESCRIPTION': {
            'name': 'Read values from names and descriptions',
            'description': 'Where a part has no parameter for it, read the value, package, tolerance and ratings from its name and description',
            'validator': bool,
            'default': True,
        },
        'INCLUDE_ASSEMBLIES': {
            'name': 'Look for alternatives of assemblies',
            'description': 'Off: only parts which are not assemblies are offered as candidates',
            'validator': bool,
            'default': False,
        },
        'INCLUDE_INACTIVE': {
            'name': 'Include inactive parts',
            'description': 'Offer inactive parts as candidates, and add them to BOMs as substitutes',
            'validator': bool,
            'default': False,
        },
        'AUTO_SYNC': {
            'name': 'Update BOMs when a link changes',
            'description': 'Add and remove BOM substitutes as soon as a link is made, changed or removed, and when a BOM line is added. Off: only when Sync is pressed',
            'validator': bool,
            'default': True,
        },
        'SKIP_LOCKED': {
            'name': 'Leave locked assemblies alone',
            'description': 'Do not change the substitutes of BOM lines whose assembly is locked',
            'validator': bool,
            'default': False,
        },
        'CREATE_TEMPLATES': {
            'name': 'Create parameter templates',
            'description': 'When adding parameters from a supplier, create a parameter template if none fits',
            'validator': bool,
            'default': True,
        },
        'DIGIKEY_CLIENT_ID': {
            'name': 'DigiKey client id',
            'description': 'Client id of a DigiKey API application with access to Product Information V4 (developer.digikey.com)',
            'default': '',
        },
        'DIGIKEY_CLIENT_SECRET': {
            'name': 'DigiKey client secret',
            'description': 'Client secret of the same DigiKey API application',
            'default': '',
            'protected': True,
        },
        'DIGIKEY_SITE': {
            'name': 'DigiKey site',
            'description': 'Two-letter country code of the DigiKey site to query',
            'default': 'AU',
        },
        'DIGIKEY_CURRENCY': {
            'name': 'DigiKey currency',
            'description': 'Currency code sent with DigiKey requests',
            'default': 'AUD',
        },
        'LCSC_ENABLED': {
            'name': 'Read parameters from LCSC',
            'description': 'Look parts up on lcsc.com by their LCSC part number (C12345). This uses the data behind the LCSC product pages, which is not a documented API',
            'validator': bool,
            'default': False,
        },
        'SHOW_NAVIGATION': {
            'name': 'Show in the navigation bar',
            'description': 'Add an Alternatives link to the main navigation bar',
            'validator': bool,
            'default': True,
        },
        'SHOW_PART_PANEL': {
            'name': 'Show on part pages',
            'description': 'Add an Alternatives panel to part pages',
            'validator': bool,
            'default': True,
        },
    }

    # Custom URL endpoints (from UrlsMixin), served below /plugin/apns/
    def setup_urls(self):
        """Register the API endpoints."""
        from django.urls import path

        from . import views

        return [
            path('config/', views.ConfigView.as_view(), name='apns-config'),
            path('overview/', views.OverviewView.as_view(), name='apns-overview'),
            path('part/<int:pk>/', views.PartView.as_view(), name='apns-part'),
            path('links/', views.LinksView.as_view(), name='apns-links'),
            path('dismiss/', views.DismissView.as_view(), name='apns-dismiss'),
            path('sync/', views.SyncView.as_view(), name='apns-sync'),
            path('enrich/', views.EnrichView.as_view(), name='apns-enrich'),
        ]

    # Events (from EventMixin)

    def wants_process_event(self, event: str) -> bool:
        """Only BOM lines being added or changed are of interest."""
        return event in BOM_EVENTS

    def process_event(self, event: str, *args, **kwargs) -> None:
        """Give a new or changed BOM line the substitutes its part is linked to."""
        if event not in BOM_EVENTS or not self.get_setting('AUTO_SYNC'):
            return

        try:
            line = int(kwargs.get('id'))
        except (TypeError, ValueError):
            return

        from . import loader, store, sync

        data = loader.load(self)
        links = store.load(valid=data.info.keys())

        if links.links:
            sync.sync(data, links, loader.plugin_settings(self), line=line)

    # User interface (from UserInterfaceMixin)

    @staticmethod
    def _can_view(request) -> bool:
        from users.permissions import check_user_role

        user = getattr(request, 'user', None)

        return bool(user and check_user_role(user, 'part', 'view'))

    def get_ui_routes(self, request, context, **kwargs):
        """The overview page, at /web/plugin/apns/overview."""
        return [
            {
                'key': 'apns-overview',
                'title': 'Alternative Parts',
                'source': self.plugin_static_file(f'{FRONTEND}:renderApnsPage'),
                'options': {'path': 'overview'},
            }
        ]

    def get_ui_navigation_items(self, request, context, **kwargs):
        """A link to the overview page in the main navigation bar."""
        if not self.get_setting('SHOW_NAVIGATION') or not self._can_view(request):
            return []

        return [
            {
                'key': 'apns-overview',
                'title': 'Alternatives',
                'icon': 'ti:arrows-exchange:outline',
                'options': {'url': f'plugin/{self.SLUG}/overview'},
            }
        ]

    def get_ui_panels(self, request, context: dict, **kwargs):
        """Add the Alternatives panel to part pages."""
        context = context or {}

        if context.get('target_model') != 'part':
            return []

        if not self.get_setting('SHOW_PART_PANEL') or not self._can_view(request):
            return []

        try:
            part_id = int(context.get('target_id'))
        except (TypeError, ValueError):
            return []

        return [
            {
                'key': 'apns',
                'title': 'Alternatives',
                'description': 'Alternative parts, candidates and the BOMs they apply to',
                'icon': 'ti:arrows-exchange:outline',
                'source': self.plugin_static_file(f'{FRONTEND}:renderApnsPartPanel'),
                'context': {'part_id': part_id, 'slug': self.SLUG},
            }
        ]
