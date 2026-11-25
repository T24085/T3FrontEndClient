"""Compare isolated flag-volume contacts in solo and concurrent native route passes."""
import argparse
import errno
import json
import math
import msvcrt
from pathlib import Path
import random
import time

from batch import Campaign, select
from route_transfer import exploratory_routes, route_evidence
from practice import HERE, MAP, MAX_TRAINING_BOTS, NativeMemoryBusy, check_between_matches, start, training_wait
from train import METRICS, Trainer, fixed_training_teams, publish, read_ready, replace_once


TRIALS = (59, 53)
WAVES = ((0,), (1,), (0, 1))
SCREEN_ROUTES = (
    'left_95m_100m_low_lift', 'left_125m_80m_high_lift', 'right_85m_100m_low_lift',
    'left_85m_100m_low_lift', 'right_95m_100m_low_lift',
)
SCREEN_STARTS = (
    ((1,-90),(1,90),(2,-90),(2,90),(3,-90)),
    ((1,-45),(1,95),(2,-45),(2,95),(3,-45)),
)
MAX_SCREEN_BOTS = MAX_TRAINING_BOTS
CAP_SPEED_OBJECTIVE = 'stand-speed-penalty-v4'
TARGET_STAND_SPEED_KMH = 100


class ScreenTrainer(Trainer):
    template_bot_count = 1

    def __init__(self, rows, *, teams=None, waves_per_launch=1, next_wave=None, save_wave=None):
        super().__init__(0, 76, 2026, False)
        self.rows = rows
        self.results = []
        self.bot_count = len(rows)
        self.teams = tuple(teams) if teams is not None else (1,) * self.bot_count
        self.largest_team = max(self.teams.count(team) for team in (1, 2))
        self.match = None
        self.ready = False
        self.waves_per_launch = waves_per_launch
        self.next_wave = next_wave
        self.save_wave = save_wave
        self.completed_waves = 0
        self.began = time.monotonic()
        self.wave_began = self.began

    def instrument(self, text, out):
        text = super().instrument(text, out)
        text = replace_once(text, 'bots=1,capture_point=', f'bots={self.bot_count},capture_point=')
        if self.bot_count > 10:
            text = replace_once(text, 'deadline=os.time()+45', 'deadline=os.time()+120')
        text = replace_once(text, json.dumps((HERE/'native_trials.lua').as_posix()),
                            json.dumps((HERE/'paired_flag_screen.lua').as_posix()))
        text = replace_once(text, '  path=', '  route_script='+json.dumps((HERE/'native_trials.lua').as_posix())
                            +',approach_reward=true,'
                            +(f'screen_reuse=true,verify_reuse=true,reuse_script={json.dumps((HERE/"verify_trial_reset.lua").as_posix())},'
                              if self.waves_per_launch > 1 else '')+'path=')
        text = fixed_training_teams(text, self.teams)
        text = replace_once(text, '  local data_path=', f"""
  local capper=assert(loadfile({json.dumps((HERE/'role_assets.lua').as_posix())}))()(valid,report)[1]
  local data_path=""")
        text = replace_once(text, '   engine_valid=engine_valid}', '   engine_valid=engine_valid,screen_capper=capper}')
        text = replace_once(text, 'SpawnBotFromDataWithTeamId(gm,state.data,team',
                            'SpawnBotFromDataWithTeamId(gm,state.screen_capper,team')
        text = replace_once(text, "   assert(owned(bot,gm:GetWorld()),'match_rules_bot_world_mismatch')",
                            '   if not owned(bot,gm:GetWorld()) then return end')
        return replace_once(text, """   local entry=assert(entries[1])
   assert(#entries==1 and entry.team==1 and entry.pawn and entry.controller,'training_single_blue_bot')
   training_started=true
   local ok, why=pcall(train,gm,gs,entry.pawn,entry.controller)""", f"""   assert(#entries=={self.bot_count},'screen_bot_count')
   training_started=true
   local ok, why=pcall(train,gm,gs,entries)""")

    def run(self, out, process):
        self.match = out
        for lane in range(1, self.bot_count+1):
            self.wait(out, process, lambda log: any(
                line.startswith(f'BOT_SCREEN_READY|{lane}|') for line in log.splitlines()), 420)
        self.ready = True
        print(f'Native flag screening ready with {self.bot_count} capper(s).', flush=True)
        began = self.began
        for trial in range(1, self.waves_per_launch + 1):
            check_between_matches()
            if trial > 1:
                self.rows = self.next_wave()
                if len(self.rows) != self.bot_count:
                    raise ValueError('Screening roster changed during a launch.')
            self.run_wave(out, process, trial)
            wall_seconds = time.monotonic() - began
            self.completed_waves += 1
            if self.save_wave:
                self.save_wave(self.rows, self.results, wall_seconds, trial, out)
            began = time.monotonic()
            self.wave_began = began
            check_between_matches()

    def run_wave(self, out, process, trial):
        for lane, row in enumerate(self.rows, 1):
            fields = [row['spawn'],row['offset_cm'],self.seconds,*row['policy'].values(),
                      0,row['pass_runup_cm'],row['guidance']]
            publish(out/f'lane-{lane}-trial-{trial}.csv', ','.join(map(str, fields))+'\n')
        results = []
        for lane, source in enumerate(self.rows, 1):
            prefix = f'lane-{lane}-'
            raw = self.wait(out, process, lambda _: read_ready(out/f'{prefix}result-{trial}.csv'), 180)
            outcome = dict(zip(METRICS,map(float,raw.split(',')),strict=True))
            contact = list(map(float,(out/f'{prefix}contact-{trial}.csv').read_text().split(',')))
            passage = list(map(float,(out/f'{prefix}pass-{trial}.csv').read_text().split(',')))
            if trial > 1 and read_ready(out/f'{prefix}verified-reset-{trial}.csv') != '1\n':
                raise RuntimeError('training_reuse_unverified|missing_reset_receipt')
            if (outcome['id']!=trial or outcome['start_energy'] < 98 or outcome['pickup'] or outcome['capture']
                    or not all(map(math.isfinite, [*outcome.values(),*contact,*passage]))
                    or (contact!=[0] and (len(contact) not in (5,7) or contact[0]!=1 or contact[4] not in (0,1)))
                    or (len(contact)==7 and not 0 <= contact[5] <= contact[6])
                    or (len(passage) not in (5,10))):
                raise ValueError('Invalid screening evidence.')
            row = {'source_trial':source.get('campaign_attempt'),'route':source['approach_route'],
                   'spawn':source['spawn'],'offset_cm':source['offset_cm'],
                   'lane':lane,'team':self.teams[lane-1],'contact':contact[0]==1,'peak_kmh':outcome['peak_kmh'],
                   'seconds':outcome['seconds'],'trace':str(out/f'{prefix}trace-{trial}.csv'),
                   'average_kmh':outcome['average_kmh'], 'jet_frames':int(outcome['jet_frames']),
                   'ski_frames':int(outcome['ski_frames'])}
            if len(passage)==10:
                row.update(pass_gap_m=passage[5]/100, pass_speed_kmh=passage[6],
                           homeward_kmh=passage[7],cross_track_m=passage[8]/100,vertical_m=passage[9]/100)
            if row['contact']:
                row.update(contact_kmh=math.hypot(contact[1],contact[2]), skiing=bool(contact[4]))
                if len(contact)==7:
                    row.update(approach_entry_kmh=contact[5], approach_peak_kmh=contact[6])
            results.append(row)
        self.results = results


def screen_plan(sweep, matches=10, bots=5, start_index=0):
    catalog = sweep['configuration']['routes']
    routes = []
    for name in SCREEN_ROUTES:
        route = catalog[name]
        routes.append({'approach_route':name, 'policy':route['policy'], 'pass_runup_cm':route['runup_cm'],
                       'guidance':route['guidance']})
    waves = []
    for index in range(start_index, start_index + matches):
        shift, group = divmod(index % 10, 2)
        starts = SCREEN_STARTS[group]
        if bots > 10:
            starts = tuple((spawn, offset + group * 15)
                           for offset in (-210, -150, -90, -30, 30, 90, 150, 210)
                           for spawn in (1, 2, 3))
        elif bots > 5:
            starts = ((1, -220), (1, -75), (1, 75), (1, 220), (2, -145),
                      (2, 0), (2, 145), (3, -145), (3, 0), (3, 145))
            if group:
                starts = tuple((spawn, offset + 20) for spawn, offset in starts)
        if bots < 5:
            starts = starts[index % 5:] + starts[:index % 5]
            shift = index
        waves.append([dict(routes[(lane+shift) % len(routes)],spawn=spawn,offset_cm=offset)
                      for lane,(spawn,offset) in enumerate(starts[:bots])])
    return waves


def stand_speed_score(speed):
    """Reward every speed gain, with a steeper ramp up to 100 km/h."""
    speed = max(0, speed)
    return min(speed, 100) / 25 + max(speed - 100, 0) / 50


def stand_speed_penalty(pickup, entry, peak):
    # Older results can still be penalized for slow flag contact.
    slow = .9 * max(0, 1 - pickup / TARGET_STAND_SPEED_KMH)
    if entry is None or peak is None:
        return slow
    lost = min(1.5, max(0, peak - pickup - 5) / 35)
    gain_target = min(12, max(0, TARGET_STAND_SPEED_KMH - entry))
    stalled = .6 * min(1, max(0, gain_target - max(0, pickup - entry)) / 12)
    return slow + lost + (stalled if pickup < TARGET_STAND_SPEED_KMH else 0)


def screening_score(row):
    if not row.get('contact'):
        return 0
    pickup = max(0, row.get('contact_kmh') or 0)
    entry = row.get('approach_entry_kmh')
    peak = row.get('approach_peak_kmh')
    retained = .25 * min(1, min(entry, pickup) / 100) * min(1, pickup / peak) if entry and peak else 0
    movement = max(.05, .5 + stand_speed_score(pickup) + retained - stand_speed_penalty(pickup, entry, peak))
    return (movement
            + 0.5 * bool(row.get('captured'))
            + 0.25 * bool(row.get('skiing'))
            + 0.25 * min(max(0, row.get('homeward_kmh') or 0) / 100, 1))


def adaptive_wave(starts, routes, evidence, match):
    by_route = {row['approach_route']: row for row in routes}
    history = {key: [] for key in by_route}
    for row in evidence:
        if row['route'] in history:
            history[row['route']].append(row)
    rng = random.Random(f'flag-screen:{len(evidence)}:{match}')
    chosen = []
    probes = [row['approach_route'] for row in routes if row.get('exploratory')]
    probe_slots = ({(match+offset) % len(starts) for offset in range(0, len(starts), 5)}
                   if probes and (len(starts) > 1 or match % 5 == 0) else set())
    eligible = {name: rows for name, rows in history.items() if name not in probes or len(rows) >= 3}
    # Count each assignment as a pending sample when distributing this wave.
    for slot, start in enumerate(starts):
        if slot in probe_slots:
            fewest = min(len(history[name]) for name in probes)
            route = rng.choice([name for name in probes if len(history[name]) == fewest])
        else:
            route = select(eligible, rng, routes[0]['approach_route'], screening_score)
        chosen.append(dict(by_route[route], spawn=start['spawn'], offset_cm=start['offset_cm']))
        history[route].append({})
    return chosen


def balanced_screening_teams(bots, waves):
    teams = [row.get('team', 1) for wave in waves for row in wave['results']]
    first = 2 if teams.count(2) < teams.count(1) else 1
    return tuple(first if slot % 2 == 0 else 3 - first for slot in range(bots))


def balanced_adaptive_wave(wave, teams, candidates, evidence, index):
    settings = wave[:]
    for team in (1, 2):
        slots = [slot for slot, selected in enumerate(teams) if selected == team]
        if not slots:
            continue
        own = [row for row in evidence if row.get('team', 1) == team]
        selection = adaptive_wave([wave[slot] for slot in slots], candidates, own, index)
        for slot, setup in zip(slots, selection, strict=True):
            settings[slot] = setup
    return settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    parser.add_argument('prior',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--five-bots',action='store_true',help='Screen five cappers across ten matched waves.')
    parser.add_argument('--map', default=MAP)
    parser.add_argument('--matches', type=int, default=10)
    parser.add_argument('--bots', type=int, default=5)
    parser.add_argument('--waves-per-launch', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--after', type=Path, help='Wait for this earlier screening campaign to release its lock.')
    args=parser.parse_args()
    if args.after:
        if args.after.resolve() == args.output.resolve():
            parser.error('--after requires a different campaign directory.')
        print('Waiting for the earlier screening campaign to finish.', flush=True)
        with (args.after/'campaign.lock').open('r+b') as predecessor:
            while True:
                predecessor.seek(0)
                try:
                    msvcrt.locking(predecessor.fileno(),msvcrt.LK_NBLCK,1)
                    break
                except OSError as exc:
                    if exc.errno != errno.EACCES:
                        raise
                    time.sleep(5)
    config = dict(json.loads(args.config.read_bytes()), training_map=args.map)
    sweep=json.loads(args.prior.read_bytes())
    prior={r['campaign_attempt']:r for r in sweep['attempts']}
    if args.five_bots:
        if not 1 <= args.matches <= 1000:
            parser.error('--matches must be between 1 and 1000')
        if not 1 <= args.bots <= MAX_SCREEN_BOTS:
            parser.error(f'--bots must be between 1 and {MAX_SCREEN_BOTS}')
        plan = screen_plan(sweep, args.matches, args.bots)
        routes = plan
        scenario = 'five-capper-screen-v1'
    else:
        routes = [dict(prior[i], guidance=sweep['configuration']['routes'][prior[i]['approach_route']]['guidance'])
                  for i in TRIALS]
        if len({(r['spawn'],r['offset_cm']) for r in routes})<len(routes):
            routes[1]=dict(routes[1],spawn=2)
        plan = [[routes[i] for i in wave] for wave in WAVES]
        scenario = 'independent-flag-volume-v1'
    args.output.mkdir(parents=True,exist_ok=True)
    checkpoint=args.output/'progress.json'
    adaptive = args.five_bots and args.output.parent.name == 'DashboardRuns'
    balanced = adaptive
    if adaptive and checkpoint.is_file():
        prior_scenario = json.loads(checkpoint.read_bytes())['scenario']
        adaptive = prior_scenario != 'five-capper-screen-v1'
        balanced = prior_scenario == 'adaptive-flag-screen-both-v1'
    prior_results = []
    if adaptive:
        candidates = screen_plan(sweep, 1, 5)[0]
        candidates += [
            dict(approach_route=name, policy=route['policy'], pass_runup_cm=route['runup_cm'],
                 guidance=route['guidance'], campaign_attempt=None)
            for name, route in sweep['configuration']['routes'].items()
            if name not in SCREEN_ROUTES
        ]
        candidates.extend(exploratory_routes())
        prior_results = route_evidence(args.output, args.map, candidates)
        scenario = 'adaptive-flag-screen-both-v1' if balanced else 'adaptive-flag-screen-v1'
    with (args.output/'campaign.lock').open('a+b') as lock:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        report=json.loads(checkpoint.read_bytes()) if checkpoint.exists() else {
            'scenario':scenario,'map':args.map,'routes':routes,'waves':[]}
        if (report['routes'] != routes or report['scenario'] != scenario
                or report.get('map', MAP) != args.map):
            raise ValueError('Screening checkpoint uses different route settings.')
        if adaptive:
            report['carried_forward'] = len(prior_results)
            plan = screen_plan(sweep, args.matches, args.bots, len(prior_results)//args.bots)
        if not checkpoint.exists():
            publish(checkpoint,json.dumps(report,indent=2)+'\n')
        def next_wave(teams):
            index = len(report['waves'])
            wave = plan[index]
            if adaptive:
                seen = [row for saved in report['waves'] for row in saved['results']]
                if balanced:
                    wave = balanced_adaptive_wave(wave, teams, candidates, prior_results + seen, index)
                else:
                    wave = adaptive_wave(wave, candidates, prior_results + seen, index)
            return wave

        def save_wave(wave, measured, wall_seconds, trial, session):
            record = {'bots':len(wave), 'wall_seconds':round(wall_seconds,2), 'results':measured,
                      'session':session.name, 'session_wave':trial, 'verified_reuse':trial > 1}
            if adaptive:
                record.update(settings=wave, objective=CAP_SPEED_OBJECTIVE)
            report['waves'].append(record)
            publish(checkpoint,json.dumps(report,indent=2)+'\n')
            print(f"Finished wave {len(report['waves'])}/{len(plan)}: {json.dumps(measured)}",flush=True)

        session_limit = 1 if report.get('reset_fallbacks') else args.waves_per_launch
        if balanced and args.bots == 1:
            session_limit = 1
        while len(report['waves']) < len(plan):
            check_between_matches()
            startup_retry = False
            while True:
                teams = balanced_screening_teams(args.bots, report['waves']) if balanced else (1,) * args.bots
                trainer = ScreenTrainer(next_wave(teams), teams=teams,
                                        waves_per_launch=min(session_limit, len(plan)-len(report['waves'])),
                                        next_wave=lambda: next_wave(teams), save_wave=save_wave)
                reset_failed = False
                try:
                    start(config, trainer=trainer)
                except RuntimeError as exc:
                    if isinstance(exc, NativeMemoryBusy) or type(exc).__name__ == 'NativeResourceBusy':
                        print(f'{exc} Retrying in 20 seconds.', flush=True)
                        training_wait(20)
                        continue
                    if not startup_retry and not trainer.ready and str(exc) == 'Timed out waiting for native training evidence.':
                        startup_retry = True
                        print('Native match did not reach bot readiness. Retrying this unsaved match once.', flush=True)
                        training_wait(5)
                        continue
                    if trainer.completed_waves and 'training_reuse_unverified|' in str(exc):
                        session_limit = 1
                        reset_failed = True
                        failed_wall_seconds = time.monotonic() - trainer.wave_began
                        print(f'{exc} Saved waves are intact. Remaining waves use fresh hosts.', flush=True)
                    else:
                        raise
                finally:
                    if trainer.match:
                        receipt = json.loads((trainer.match/'host/execution/execution.json').read_bytes())
                        remaining = receipt.get('job_active_processes_after_cleanup',receipt.get('job_active_processes_at_parent_exit'))
                        if remaining != 0:
                            raise RuntimeError('Screening host cleanup could not be verified.')
                        cleanup=Campaign.__new__(Campaign)
                        cleanup.last_match=trainer.match
                        cleanup.runs=Path(config['runs']).resolve()
                        cleanup.retire_game_copy()
                break
            if reset_failed:
                report.setdefault('reset_fallbacks', []).append({'after_wave':len(report['waves']),
                    'session':trainer.match.name, 'wall_seconds':round(failed_wall_seconds,2)})
                publish(checkpoint,json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
