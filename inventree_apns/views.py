"""API views for the Alternative Parts plugin.

All endpoints are served below /plugin/apns/ and accept session or token
authentication, so they can also be used from scripts.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import PLUGIN_VERSION, enrich, loader, serialize, store, sync


def _plugin():
    from plugin.registry import registry

    plugin = registry.get_plugin(store.SLUG)

    if plugin is None:
        raise NotFound('The Alternative Parts plugin is not active')

    return plugin


def _can(user, role: str, permission: str) -> bool:
    from users.permissions import check_user_role

    return bool(user and check_user_role(user, role, permission))


def user_permissions(user) -> dict:
    """What the user may do."""
    return {
        'view': _can(user, 'part', 'view'),
        # Links and dismissed candidates are stored against the part
        'link': _can(user, 'part', 'change'),
        # Syncing changes the substitutes of BOM lines
        'sync': _can(user, 'bom', 'change'),
        # Enriching adds parameters to parts
        'enrich': _can(user, 'part', 'change'),
    }


def _flag(value) -> bool:
    return value is True or str(value).lower() in ('1', 'true', 'yes')


def _parts(value) -> list[int] | None:
    if value in (None, ''):
        return None

    if not isinstance(value, (list, tuple)):
        raise ValidationError({'parts': 'Expected a list of part ids'})

    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        raise ValidationError({'parts': 'Expected a list of part ids'})


class ApnsView(APIView):
    """Base class: every endpoint needs at least permission to view parts."""

    permission_classes = [permissions.IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        """Check the role permissions before handling the request."""
        super().initial(request, *args, **kwargs)

        if not _can(request.user, 'part', 'view'):
            raise PermissionDenied()

    def require(self, request, name: str):
        """Raise an error unless the user has the named permission."""
        if not user_permissions(request.user).get(name):
            raise PermissionDenied()

    def sync_after(self, request, plugin, parts) -> dict | None:
        """Bring the BOMs in step after a link changed, if that is wanted and allowed."""
        settings = loader.plugin_settings(plugin)

        if not settings['auto_sync'] or not user_permissions(request.user)['sync']:
            return None

        return serialize.sync_parts(plugin, parts=parts)


class ConfigView(ApnsView):
    """GET /plugin/apns/config/ - the settings and the user's permissions."""

    def get(self, request, *args, **kwargs):
        """Return the settings."""
        return Response({
            'version': PLUGIN_VERSION,
            'settings': loader.plugin_settings(_plugin()),
            'permissions': user_permissions(request.user),
        })


class PartView(ApnsView):
    """GET /plugin/apns/part/<part id>/ - links, candidates and BOM use of a part.

    Part data is read at most once a minute, unless ?fresh=1 is given.
    """

    def get(self, request, pk: int, *args, **kwargs):
        """Return the alternates of the part."""
        payload = serialize.part_payload(
            _plugin(), pk, use_cache=not _flag(request.query_params.get('fresh'))
        )

        if not payload:
            raise NotFound()

        return Response({**payload, 'permissions': user_permissions(request.user)})


class OverviewView(ApnsView):
    """GET /plugin/apns/overview/ - links, candidates, duplicates and pending BOM changes."""

    def get(self, request, *args, **kwargs):
        """Return the overview of the whole catalogue."""
        payload = serialize.overview_payload(
            _plugin(), use_cache=not _flag(request.query_params.get('fresh'))
        )

        return Response({**payload, 'permissions': user_permissions(request.user)})


class LinksView(ApnsView):
    """The alternate links.

    GET    /plugin/apns/links/  every link
    POST   /plugin/apns/links/  {"part": 12, "alternate": 34, "two_way": true, "note": "..."}
    DELETE /plugin/apns/links/  {"part": 12, "alternate": 34}

    A link says that 'alternate' can be used in place of 'part'. With
    "two_way" the two are interchangeable. Posting a pair which is already
    linked replaces that link.
    """

    def get(self, request, *args, **kwargs):
        """Return every link."""
        return Response({'links': [link.as_dict() for link in store.load().links]})

    def post(self, request, *args, **kwargs):
        """Make or change a link."""
        self.require(request, 'link')
        plugin = _plugin()

        link = store.set_link(
            request.data.get('part'),
            request.data.get('alternate'),
            two_way=_flag(request.data.get('two_way')),
            note=request.data.get('note') or '',
            user=request.user,
        )

        return Response({
            'link': link.as_dict(),
            'sync': self.sync_after(request, plugin, [link.part, link.alternate]),
        })

    def delete(self, request, *args, **kwargs):
        """Remove the link between two parts."""
        self.require(request, 'link')
        plugin = _plugin()

        source = request.data if request.data else request.query_params
        part, alternate = store.check_parts(source.get('part'), source.get('alternate'))
        store.remove_link(part, alternate)

        return Response({'removed': True, 'sync': self.sync_after(request, plugin, [part, alternate])})


class DismissView(ApnsView):
    """POST /plugin/apns/dismiss/ - turn a candidate down, or bring it back.

    {"part": 12, "other": 34, "dismissed": true}
    """

    def post(self, request, *args, **kwargs):
        """Record the decision."""
        self.require(request, 'link')

        dismissed = request.data.get('dismissed', True)
        store.set_dismissed(request.data.get('part'), request.data.get('other'), _flag(dismissed))

        return Response({'dismissed': _flag(dismissed)})


class SyncView(ApnsView):
    """BOM substitutes.

    GET  /plugin/apns/sync/  what a sync would add and remove
    POST /plugin/apns/sync/  do it; {"parts": [12, 34]} limits it to BOM lines for those parts
    """

    def get(self, request, *args, **kwargs):
        """Return the changes a sync would make."""
        plugin = _plugin()
        data = loader.load(plugin)
        plan = sync.plan(data, store.load(valid=data.info.keys()), loader.plugin_settings(plugin))

        return Response({
            **plan,
            'lines': [
                {key: value for key, value in change.items() if key != 'remove_records'}
                for change in plan['lines']
            ],
        })

    def post(self, request, *args, **kwargs):
        """Add and remove substitutes so that the BOMs match the links."""
        self.require(request, 'sync')

        return Response(serialize.sync_parts(_plugin(), parts=_parts(request.data.get('parts'))))


class EnrichView(ApnsView):
    """POST /plugin/apns/enrich/ - find parameter values for a part.

    {"part": 12}                     what would be added
    {"part": 12, "apply": true}      add them
    {"part": 12, "apply": true, "only": ["Capacitance", "Package"]}
    {"part": 12, "sources": ["digikey", "lcsc", "description"]}

    Parameters which the part already has are never changed.
    """

    def post(self, request, *args, **kwargs):
        """Propose (and optionally store) parameters."""
        self.require(request, 'enrich')
        plugin = _plugin()

        try:
            pk = int(request.data.get('part'))
        except (TypeError, ValueError):
            raise ValidationError({'part': 'A part is required'})

        sources = request.data.get('sources')

        if sources is not None:
            if not isinstance(sources, (list, tuple)) or any(item not in enrich.SOURCES for item in sources):
                raise ValidationError({'sources': f'Choose from {", ".join(enrich.SOURCES)}'})

        data = loader.load(plugin)

        if pk not in data.info:
            raise NotFound()

        settings = loader.plugin_settings(plugin)
        result = enrich.propose(plugin, data, pk, sources=sources, create=settings['create_templates'])

        if _flag(request.data.get('apply')):
            only = request.data.get('only')

            if only is not None and not isinstance(only, (list, tuple)):
                raise ValidationError({'only': 'Expected a list of parameter names'})

            result['applied'] = enrich.apply(pk, result['proposals'], user=request.user, only=only)

            if result['applied']['added']:
                loader.clear_cache()

        return Response(result)
