"""Versioned selected-map bootstrap; legacy clients keep their existing boot."""
from community_maps import BY_ID
CONTRACT = 'selected-map-bootstrap-v1'


def apply(template, contract, selected_map=None, *, definitions=BY_ID):
    if contract is None:
        return template
    if contract != CONTRACT:
        raise ValueError('Unsupported client bootstrap contract.')
    if template.count('local joined=false') != 1 or template.count('/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:') != 2:
        raise ValueError('Unsupported client bootstrap runtime format.')
    package = map_name(contract, selected_map, definitions=definitions)
    definition = definitions[selected_map]
    world = package + '.' + definition.level + ':'
    # The selected level's packages stay warm through the native server travel.
    # Keep the exact standalone class/authority/world guards and original join.
    return template.replace('/Game/Maps/Active/Drydock/Arena_Drydock_P.Arena_Drydock_P:', world).replace(
        'initial_standalone_drydock_required', 'initial_standalone_selected_bootstrap_required')


def map_name(contract, selected_map=None, *, definitions=BY_ID):
    if contract is None:
        return '/Game/Maps/Active/Drydock/Arena_Drydock_P'
    if contract != CONTRACT:
        raise ValueError('Unsupported client bootstrap contract.')
    if not isinstance(selected_map, str) or selected_map not in definitions:
        raise ValueError('Selected-map bootstrap requires a known selected map.')
    return definitions[selected_map].package
