"""Measure fast airborne travel and the transition back to skiing."""

from statistics import median


FAST_KMH = 45
SCORING = 'sustained-flight-v1'
TEAM_FIELDS = ('fast_air_seconds', 'longest_fast_air_seconds', 'fast_glide_seconds',
               'landing_count', 'landing_speed_retained', 'landing_energy')


def match_key(match):
    session = match.get('session')
    return f"{session}/{match.get('session_wave', 1)}" if session else None


def momentum(frames, max_gap):
    """Frames are (seconds, speed km/h, airborne, jetting, energy, forward metres)."""
    fast_air = fast_forward = glide = streak = longest = 0
    landings, reserves = [], []
    for previous, current in zip(frames, frames[1:]):
        time, speed, air, jet, _, forward = previous
        next_time, next_speed, next_air, next_jet, energy, next_forward = current
        dt = next_time - time
        if not 0 < dt <= max_gap:
            streak = 0
            continue
        if air and next_air and min(speed, next_speed) >= FAST_KMH:
            fast_air += dt
            streak += dt
            longest = max(longest, streak)
            fast_forward += min(max(0, next_forward - forward), 110 * dt)
            if not jet and not next_jet:
                glide += dt
        else:
            streak = 0
        if air and not next_air and speed >= FAST_KMH:
            landings.append(next_speed / speed)
            reserves.append(energy)
    return dict(fast_air_seconds=round(fast_air, 2), longest_fast_air_seconds=round(longest, 2),
                fast_air_forward_m=round(fast_forward, 2), fast_glide_seconds=round(glide, 2),
                landing_count=len(landings), landing_speed_retained=round(median(landings), 3) if landings else None,
                landing_energy=round(median(reserves), 2) if reserves else None)


def sustained_score(progress, course_distance, metrics):
    """Rank in-game progress, sustained flight and a usable landing."""
    landing = min(metrics['landing_speed_retained'] or 0, 1)
    energy = max(0, metrics['landing_energy'] or 0)
    return (.25 * min(progress / course_distance, 1)
            + .35 * min(metrics['fast_air_forward_m'] / 100, 1)
            + .20 * min(metrics['longest_fast_air_seconds'] / 4, 1)
            + .10 * min(metrics['fast_glide_seconds'] / 2, 1)
            + .10 * landing * min(energy / 25, 1))
