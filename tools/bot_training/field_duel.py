"""Mirrored capper versus chaser trials in the native CTF host."""
import csv
import json
from collections import defaultdict
import math
from statistics import mean

from dashboard_run import TeamTrainer
from learning_history import past_runs
from practice import HERE, MAP, NativeMemoryBusy, check_between_matches, start, training_wait
from team_waves import evidence_path
from train import publish, replace_once


CHASE_PROFILES = {'short-lead': .35, 'balanced-lead': .65, 'long-lead': .9}


def pursuit_summary(rows):
    profiles = defaultdict(lambda: {1: [], 2: []})
    for row in rows:
        duel = row['duel']
        name = duel.get('chase_profile')
        if name not in CHASE_PROFILES or not duel['combat_complete'] or duel['airborne_launches'] < 1:
            continue
        team = 3-duel['capper']
        damage = duel['carrier_damage']
        quality = (.5*(duel['outcome'] == 'intercepted' and damage > 0)
                   + .3*min(1,damage/1000) + .2*duel['airborne_hits']/duel['airborne_launches'])
        profiles[name][team].append((quality,duel['airborne_hits']))
    summaries = []
    for name, sides in profiles.items():
        scores = [mean(value for value,_ in sides[team]) if sides[team] else 0 for team in (1,2)]
        qualified = all(len(games) >= 2 and any(hits > 0 for _,hits in games) for games in sides.values())
        summaries.append(dict(profile=name,blue_samples=len(sides[1]),red_samples=len(sides[2]),
                              score=round(min(scores),4),qualified=qualified))
    return sorted(summaries,key=lambda row: (-row['score'],row['profile']))


def qualified_pursuit_lead(output, map_id, provenance=None):
    candidates = []
    for source, _, report in past_runs(output,'duel',map_id,provenance=provenance):
        candidates.extend((row['score'],source,row['profile']) for row in report.get('pursuit_profiles', ())
                          if row['qualified'] and row['profile'] in CHASE_PROFILES)
    if not candidates:
        return {}
    score, source, name = max(candidates)
    return dict(profile=name,source=source,lead=CHASE_PROFILES[name],score=score)


def capper_recovery(trace, pickup, hits):
    with open(trace,newline='') as source:
        frames = [(float(row['seconds']),float(row['home_flag_cm'])/100,
                   .036*math.hypot(float(row['vx_cm_s']),float(row['vy_cm_s'])),row['carrying']=='1',
                   row['ski']=='1' or row['grounded']=='0') for row in csv.DictReader(source)
                  if float(row['seconds']) >= pickup]
    carrying = [frame for frame in frames if frame[3]]
    if not carrying:
        return dict(homeward_advance_m=0,escape_seconds=None,hit_recovery_seconds=None)
    begin, home, *_ = carrying[0]
    advance = max(0,home-min(frame[1] for frame in carrying))
    escape = next((round(frame[0]-begin,2) for frame in carrying if home-frame[1] >= 35),None)
    recoveries = []
    for hit in sorted(hits):
        hit_frame = next((frame for frame in carrying if frame[0] >= hit),None)
        if hit_frame is None or hit_frame[2] >= 45:
            continue
        restored = next((frame[0]-hit for frame in carrying if hit+.25 <= frame[0] <= hit+8
                         and frame[2] >= 45 and frame[4] and hit_frame[1]-frame[1] >= 5),None)
        if restored is not None:
            recoveries.append(restored)
    return dict(homeward_advance_m=round(advance,1),escape_seconds=escape,
                hit_recovery_seconds=round(mean(recoveries),2) if recoveries else None)


class DuelTrainer(TeamTrainer):
    verify_start = True
    strict_movement = True
    adaptive_movement = True

    def __init__(self, capper, lane, seconds, chase_profile='balanced-lead'):
        roles = [('Capper',), ('Light defense',)]
        super().__init__(*(roles if capper == 1 else roles[::-1]), seconds)
        self.capper = capper
        self.lane = lane
        self.chase_profile = chase_profile
        self.pursuit = dict(lead=CHASE_PROFILES[chase_profile])

    def instrument(self, text, out):
        rendered = super().instrument(text, out)
        script = json.dumps((HERE/'field_duel.lua').as_posix())
        return replace_once(rendered, '  seconds=',
                            f'  duel_script={script},duel_capper={self.capper},duel_lane={self.lane},seconds=')

    def read_match(self, out, process, wave=1):
        super().read_match(out, process, wave)
        with evidence_path(out, wave, 'team-duel.csv').open(newline='') as source:
            rows = list(csv.DictReader(source))
        if len(rows) != 1 or int(rows[0]['capper']) != self.capper:
            raise RuntimeError('The native duel did not record the expected roster.')
        raw = rows[0]
        outcome = raw['outcome']
        chaser = 3-self.capper
        if outcome == 'setup_failed':
            raise RuntimeError('field_duel_no_verified_pickup')
        if outcome not in ('captured', 'intercepted', 'flag_lost', 'timeout'):
            raise RuntimeError('The native duel returned an unknown outcome.')
        events = self.result.get('combat', [])
        start_time = float(raw['setup_seconds'])
        launches = [event for event in events if event['shooter'] == chaser and event['seconds'] >= start_time
                    and event['event'] == 'launch']
        hit_ids = {event['shot']: event for event in events if event['event'] == 'damage'
                   and event.get('target') == self.capper and event['shooter'] == chaser}
        air_launches = [event for event in launches if event.get('shooter_airborne')]
        confirmed = bool(self.result.get('combat_complete'))
        capper = self.result['bots'][self.capper-1]
        recovery = capper_recovery(capper['trace'],start_time,
            [event['seconds'] for event in hit_ids.values()] if confirmed else [])
        self.result['duel'] = dict(capper=self.capper, chaser=chaser, lane=self.lane, outcome=outcome, chase_profile=self.chase_profile,
            setup_seconds=start_time, seconds=float(raw['duel_seconds']), combat_complete=confirmed,
            chaser_launches=len(launches), airborne_launches=len(air_launches),
            airborne_hits=sum(event['shot'] in hit_ids for event in air_launches) if confirmed else None,
            carrier_damage=round(sum(hit_ids[shot['shot']]['damage'] for shot in launches if shot['shot'] in hit_ids),1)
                if confirmed else None, **recovery)


def duel_run(config, output, matches, seconds):
    if matches < 2 or matches % 2 or not 30 <= seconds <= 90:
        raise ValueError('Capper vs. Chaser needs two games per mirrored pair and 30–90 seconds per game.')
    path = output/'progress.json'
    expected = dict(scenario='capper-chaser-v1', map=config.get('training_map',MAP), target=matches, seconds=seconds)
    if path.exists():
        report = json.loads(path.read_bytes())
    else:
        from flight_training import qualified_flight_transfer
        from human_reference import load_reference
        report = expected | {'matches': [], 'flight_transfer': qualified_flight_transfer(output,expected['map']),
                             'human_reference': load_reference(config,expected['map'])}
    if any(report.get(name) != value for name, value in expected.items()):
        raise ValueError('Use the same map and rules to resume this duel.')

    def save():
        publish(path, json.dumps(report,indent=2)+'\n')

    save()
    while len(report['matches']) < matches:
        check_between_matches()
        index = len(report['matches'])
        pair = index//2
        profiles = tuple(CHASE_PROFILES)
        trainer = DuelTrainer(capper=1+((index+pair)%2), lane=1 if pair%2 == 0 else -1, seconds=seconds,
                              chase_profile=profiles[pair%len(profiles)])
        trainer.flight_transfer = report.get('flight_transfer',{})
        trainer.human_reference = report.get('human_reference',{})
        try:
            start(config,trainer=trainer)
        except RuntimeError as exc:
            if not isinstance(exc,NativeMemoryBusy) and type(exc).__name__ != 'NativeResourceBusy':
                raise
            print(exc,flush=True)
            training_wait(20)
            continue
        result = trainer.result
        labels = ('Capper', 'Chaser') if trainer.capper == 1 else ('Chaser', 'Capper')
        report['matches'].append(dict(result, policy='Mirrored pursuit', blue_policy=labels[0], red_policy=labels[1],
            margin=result['blue']-result['red'], drill_pair=pair+1, attack_team=trainer.capper))
        report['pursuit_profiles'] = pursuit_summary(report['matches'])
        save()
        print(f'Duel games saved: {index+1}/{matches}',flush=True)
