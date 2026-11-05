"""Failure events emitted by the shared game runtime modules."""
RUNTIME_FAILURE_PREFIXES=(
    'RUNTIME_ERROR|','ERROR ','ENERGY_RECHARGE_ERROR|','JETPACK_INPUT_ERROR|',
    'FLAG_MARKER_ERROR|','PAWN_LIFECYCLE_ERROR|','SELF_DAMAGE_ERROR|',
    'FLAG_CAPTURE_ERROR|','SNOWFALL_ERROR|','PROJECTILE_LISTEN_COMPAT_ERROR|','TURRET_RECOVERY_ERROR|',
)


def runtime_failure(lines):
    return next((line for line in lines if line.startswith(RUNTIME_FAILURE_PREFIXES)),None)
