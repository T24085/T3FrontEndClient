"""Play against the learned CTF tactics in an isolated local match."""

import argparse
import json
from pathlib import Path
from statistics import mean

from dashboard_run import TeamTrainer
from defense_learning import BASELINE, DEFENSE_ROLES, DefenseLearning
from field_duel import qualified_pursuit_lead
from flight_training import qualified_flight_transfer
from human_reference import load_reference
from learning_history import request_provenance
from offense_learning import OFFENSE_ROLES, OffenseLearning
from paired_flag_screen import screening_score
from practice import MAP, start
from route_transfer import exploratory_routes, flank_routes, ranked_routes, route_evidence, screening_candidates


class PlayableMatch(TeamTrainer):
    live_player = True
    strict_movement = True
    adaptive_movement = True


def best_tactics(roster, history):
    selected = {}
    for role, candidates in history.items():
        qualified = [name for name, scores in candidates.items() if len(scores) >= 3]
        selected[role] = max(qualified, key=lambda name: mean(candidates[name])) if qualified else BASELINE
    return {slot: (role, selected[role]) for slot, (_, role) in enumerate(roster, 1) if role in selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--map', default=MAP)
    parser.add_argument('--side', choices=('blue','red'), default='blue')
    parser.add_argument('--record', action='store_true', help='Save your movement during this match.')
    parser.add_argument('--smoke', action='store_true', help='Check local player and bot readiness in a headless match.')
    args = parser.parse_args()
    config = dict(json.loads(args.config.read_bytes()), training_map=args.map)
    root = args.config.resolve().parent
    history = root/'DashboardRuns'/'local-play'
    roster = OFFENSE_ROLES+DEFENSE_ROLES
    teams = (roster[1:],roster) if args.side == 'blue' else (roster,roster[1:])
    match = PlayableMatch(*teams, 1800)
    match.human_team = 1 if args.side == 'blue' else 2
    match.record_player = args.record
    match.human_reference = load_reference(config,args.map)
    provenance = request_provenance(config,args.map,'teams')
    match.flight_transfer = qualified_flight_transfer(history,args.map,provenance)
    match.pursuit = qualified_pursuit_lead(history,args.map,provenance)
    match.defense_tactics = best_tactics(match.roster, DefenseLearning(history, args.map, []).history)
    match.offense_tactics = best_tactics(match.roster, OffenseLearning.for_run(history, args.map, []).history)
    candidates = list(exploratory_routes()) + list(flank_routes())
    if (root/'Campaign-FlagPassSpeed500/progress.json').is_file():
        candidates = screening_candidates(root) + candidates
    routes = ranked_routes(candidates, route_evidence(history, args.map, candidates), screening_score)
    for team in (1, 2):
        slot = match.roster.index((team, 'Capper')) + 1
        if routes:
            match.guided[slot] = routes[(team-1) % len(routes)]
    start(config, smoke=args.smoke, trainer=match)


if __name__ == '__main__':
    main()
