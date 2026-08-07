from adapters.konsole import KonsoleAdapter

# One adapter instance per supported app - shared between NavigationEngine
# (which needs to resolve "what tab is this, right now" by app name while
# recording history) and NavigatorService (which needs to restore a
# previously-resolved tab by its restore_type when acting on a back/forward
# request), without either of those knowing about the other's lookup.
_ADAPTERS = (KonsoleAdapter(),)

ADAPTERS_BY_APP = {adapter.app_name: adapter for adapter in _ADAPTERS}
ADAPTERS_BY_RESTORE_TYPE = {adapter.restore_type: adapter for adapter in _ADAPTERS}
