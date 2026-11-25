"""Fixed dashboard launch options and persisted campaign state."""
from datetime import datetime
import json
import msvcrt
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

from paired_flag_screen import MAX_SCREEN_BOTS
from dashboard_run import MAX_TEAM_BOTS
from flight_training import COURSE_LABELS, LEGACY_SCENARIO as LEGACY_FLIGHT_SCENARIO, SCENARIO as FLIGHT_SCENARIO, validate_flight
from learning_history import MOVEMENT, request_provenance
from train import publish
from practice import MAP, MAX_TRAINING_BOTS, training_maps

MODES = {'solo': 'Solo capper', 'defended': 'Capper vs. two defenders',
         'screen': 'Route screening', 'explore': 'Route exploration', 'teams': 'Team CTF',
         'scrimmage': '7v7 role scrimmage', 'offdef': '4v3 offense vs. defense',
         'season': 'Super training season', 'flight': 'Flight fundamentals', 'duel': 'Capper vs. Chaser'}
RUN_ID = re.compile(r'run\d{14}[a-f0-9]{8}')
RESUMABLE = {'Paused', 'Stopped', 'Failed', 'Interrupted'}
SEASON_EVALUATION_MATCHES = 4


def has_remaining_matches(request, checkpoint):
    if checkpoint is None:
        return True
    mode = request['mode']
    if mode == 'flight':
        if checkpoint.get('scenario') not in (FLIGHT_SCENARIO, LEGACY_FLIGHT_SCENARIO):
            return False
        completed = len(checkpoint['waves'])
    elif mode == 'screen':
        if checkpoint.get('scenario') not in ('five-capper-screen-v1', 'adaptive-flag-screen-v1', 'adaptive-flag-screen-both-v1'):
            return False
        completed = len(checkpoint['waves'])
    elif 'matches' in checkpoint:
        completed = len(checkpoint['matches'])
    else:
        if checkpoint['configuration'].get('movement') != MOVEMENT:
            return False
        completed = checkpoint['completed']
    return completed < request['matches']


def worker_busy(directory):
    with (directory/'worker.lock').open('a+b') as lock:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        return False


def run_status(path):
    try:
        return json.loads((path/'status.json').read_bytes())
    except FileNotFoundError:
        return {}


class DashboardJobs:
    def __init__(self, root, runner):
        self.root = root
        self.directory = root/'DashboardRuns'
        self.runner = runner
        self.guard = threading.Lock()
        self.process = None
        self.directory.mkdir(exist_ok=True)
        self.active_marker = self.directory/'active-run.txt'

    def maps(self):
        config = json.loads((self.root/'practice.json').read_bytes())
        return {name: definition.label for name, definition in training_maps(config).items()}

    def active_run(self):
        busy = ((self.process is not None and self.process.poll() is None)
                or worker_busy(self.directory))
        if not busy:
            return None
        if self.active_marker.is_file():
            return self.active_marker.read_text(encoding='ascii').strip()
        # A worker started by the previous dashboard service can still exit cooperatively.
        return next((path.name for path in sorted(self.directory.iterdir(), reverse=True)
                     if RUN_ID.fullmatch(path.name) and (path/'request.json').is_file()
                     and not (path/'status.json').is_file() and (path/'cooperative-stop').is_file()), '')

    def queued_runs(self):
        queued = []
        for path in self.directory.iterdir():
            if not RUN_ID.fullmatch(path.name):
                continue
            state = run_status(path)
            if state.get('status') == 'Queued':
                queued.append((state['queued_at'], path))
        return [path for _, path in sorted(queued)]

    def queue_loop(self):
        while True:
            time.sleep(1)
            try:
                self.advance_queue()
            except OSError:
                continue

    def advance_queue(self):
        with self.guard:
            if self.active_run() is not None:
                return
            # Pausing, stopping or failing leaves the queue waiting for the owner.
            if self.active_marker.is_file():
                previous = self.active_marker.read_text(encoding='ascii').strip()
                if run_status(self.directory/previous).get('status') != 'Complete':
                    return
                request = self.directory/previous/'request.json'
                if request.is_file() and json.loads(request.read_bytes()).get('leave_queue_waiting'):
                    return
            queued = self.queued_runs()
            if queued:
                self.dispatch(queued[0])

    def dispatch(self, path):
        self.start_worker(path, json.loads((path/'request.json').read_bytes()))

    def clear_queue(self):
        with self.guard:
            active = self.active_run()
            waiting = [path for path in self.queued_runs() if path.name != active]
            for path in waiting:
                publish(path/'status.json', '{"status":"Cancelled"}\n')
            return len(waiting)

    def queue_action(self, identifier, action):
        if not RUN_ID.fullmatch(identifier):
            raise ValueError('Invalid training run.')
        with self.guard:
            path = self.directory/identifier
            active = self.active_run()
            queued = self.queued_runs()
            if path not in queued or active == identifier:
                raise BlockingIOError('This run is no longer queued.')
            if action == 'cancel':
                publish(path/'status.json', '{"status":"Cancelled"}\n')
            elif active is None and path == queued[0]:
                self.dispatch(path)
            else:
                raise BlockingIOError('The next queued run can start when the trainer is idle.')

    def runs(self):
        with self.guard:
            active = self.active_run()
            runs = []
            for path in sorted(self.directory.iterdir(), reverse=True):
                if not RUN_ID.fullmatch(path.name):
                    continue
                manifest = path/'request.json'
                if not manifest.is_file():
                    continue
                row = json.loads(manifest.read_bytes())
                state = run_status(path)
                running = path.name == active and state.get('status') in (None, 'Queued')
                row['stoppable'] = running and (path/'cooperative-stop').is_file()
                waiting = 'Stopping' if (path/'stop.request').is_file() else (
                    'Pausing' if (path/'pause.request').is_file() else 'Running')
                row['status'] = waiting if running else state.get('status', 'Interrupted')
                if row['status'] == 'Queued':
                    row['queued_at'] = state['queued_at']
                row['message'] = state.get('message')
                row['repeatable'] = not running and row['status'] not in ('Queued', 'Cancelled')
                checkpoint = path/'progress.json'
                row['resumable'] = row['status'] in RESUMABLE and has_remaining_matches(
                    row, json.loads(checkpoint.read_bytes()) if checkpoint.is_file() else None)
                runs.append(row)
            return active is not None, runs

    def stop(self, identifier, *, after_match=False):
        if not RUN_ID.fullmatch(identifier):
            raise ValueError('Invalid training run.')
        with self.guard:
            path = self.directory/identifier
            if self.active_run() != identifier or run_status(path).get('status') not in (None, 'Queued'):
                raise BlockingIOError('This run is no longer active.')
            if not (path/'cooperative-stop').is_file():
                raise BlockingIOError('This run started before the stop control was installed.')
            request = path/('pause.request' if after_match else 'stop.request')
            if not request.is_file():
                publish(request, 'Requested from dashboard.\n')

    def repeat(self, identifier):
        if not RUN_ID.fullmatch(identifier):
            raise ValueError('Invalid training run.')
        manifest = self.directory/identifier/'request.json'
        if not manifest.is_file():
            raise ValueError('Training run was not found.')
        request = json.loads(manifest.read_bytes())
        fields = ('mode', 'matches', 'seconds', 'bots', 'attackers', 'defenders', 'team_size', 'map', 'course',
                  'waves_per_launch', 'evaluation', 'aim_calibration')
        options = {key: request[key] for key in fields if key in request}
        if options['mode'] == 'season':
            options.pop('map', None)
            options.pop('bots', None)
        if options['mode'] == 'solo':
            options.pop('defenders', None)
        return self.launch(options)

    def launch(self, data):
        required = {'mode', 'matches', 'seconds'}
        if not isinstance(data, dict) or not required <= data.keys():
            raise ValueError('Choose a training mode and match count.')
        mode, matches, seconds = data['mode'], data['matches'], data['seconds']
        if (not isinstance(mode, str) or mode not in MODES or type(matches) is not int or not 1 <= matches <= 1000
                or type(seconds) is not int or not 30 <= seconds <= 600):
            raise ValueError('Enter 1–1,000 matches and a match length of 30–600 seconds.')
        if mode == 'season':
            if data.keys() - required - {'team_size', 'waves_per_launch'}:
                raise ValueError('A season uses all installed training maps.')
            return self.launch_season(matches, seconds, data.get('team_size', 7), data.get('waves_per_launch', 5))
        map_id = data.get('map', MAP)
        if not isinstance(map_id, str) or map_id not in self.maps():
            raise ValueError('Choose an installed training map.')
        options = {'flight': {'bots', 'course'}, 'duel': {'bots'}, 'screen': {'bots', 'waves_per_launch'}, 'solo': {'bots', 'attackers'}, 'defended': {'bots', 'attackers', 'defenders'},
                   'explore': {'bots', 'attackers', 'defenders'}, 'teams': {'bots', 'team_size'},
                   'offdef': {'bots'}, 'scrimmage': {'bots', 'team_size', 'evaluation', 'aim_calibration'}}
        if data.keys() - required - options[mode] - {'map', 'waves_per_launch'}:
            raise ValueError('Unexpected roster settings for this mode.')
        defaults = {'solo': 1, 'defended': 3, 'explore': 4, 'teams': 14, 'screen': 5, 'offdef': 7, 'scrimmage': 14, 'flight': 10, 'duel': 2}
        bots = data.get('bots', defaults[mode])
        if type(bots) is not int:
            raise ValueError('Enter a whole number of bots.')
        roster = {}
        waves_per_launch = data.get('waves_per_launch', 5)
        if type(waves_per_launch) is not int or not 1 <= waves_per_launch <= 5:
            raise ValueError('Choose 1–5 waves per game launch.')
        evaluation = data.get('evaluation', False)
        if type(evaluation) is not bool or (evaluation and (mode != 'scrimmage' or matches % 2 or matches < 2)):
            raise ValueError('A benchmark needs two matches per mirrored pair.')
        aim_calibration = data.get('aim_calibration', False)
        if type(aim_calibration) is not bool or (aim_calibration and (evaluation or matches % 2 or matches < 2)):
            raise ValueError('Aim calibration needs two games per mirrored pair.')
        label = MODES[mode]
        if mode == 'flight':
            course = data.get('course', 'straight')
            validate_flight(bots, seconds, course)
            if course != 'straight':
                roster['course'] = course
                label = COURSE_LABELS[course]
            label = f'{label} · {bots} bots'
        elif mode == 'duel':
            if bots != 2 or matches % 2 or not 30 <= seconds <= 90:
                raise ValueError('Choose 30–90 seconds and a complete pair with one capper and one chaser.')
            waves_per_launch = 1
        elif mode == 'screen':
            if not 1 <= bots <= MAX_SCREEN_BOTS:
                raise ValueError(f'Enter 1–{MAX_SCREEN_BOTS} bots per screening match.')
            label = f'Route screening · {bots} bots'
        elif mode in ('solo', 'defended', 'explore'):
            attackers = data.get('attackers', bots if mode == 'solo' else 2 if mode == 'explore' else 1)
            defenders = data.get('defenders', 0 if mode == 'solo' else 2)
            if (type(attackers) is not int or attackers < 1 or type(defenders) is not int or defenders < 0
                    or attackers + defenders > MAX_TRAINING_BOTS):
                raise ValueError(f'Choose at least one capper and at most {MAX_TRAINING_BOTS} total bots.')
            bots = attackers + defenders
            roster = dict(attackers=attackers, defenders=defenders)
            label = (f'{MODES[mode]} · {attackers}v{defenders}' if mode == 'explore'
                     else f'Cappers vs. defense · {attackers}v{defenders}' if mode == 'defended'
                     else 'Solo capper' if attackers == 1 else f'Unopposed · {attackers} cappers')
        elif mode in ('teams', 'scrimmage'):
            size = data.get('team_size', 7)
            minimum = (2 if evaluation or aim_calibration else 7) if mode == 'scrimmage' else 1
            if type(size) is not int or not minimum <= size <= MAX_TEAM_BOTS:
                raise ValueError(f'Enter {minimum}–{MAX_TEAM_BOTS} bots per team.')
            bots = 2 * size
            roster = dict(team_size=size)
            label = f'{size}v{size} role scrimmage' if mode == 'scrimmage' else f'{size}v{size} CTF'
            if evaluation:
                label = f'{size}v{size} mirrored role benchmark'
                waves_per_launch = 1
            if aim_calibration:
                label = f'{size}v{size} aim calibration'
        else:
            bots = defaults[mode]
        manifest = dict(label=label, mode=mode, matches=matches, seconds=seconds, bots=bots, map=map_id,
                        waves_per_launch=waves_per_launch, **roster)
        if evaluation:
            manifest['evaluation'] = True
        if aim_calibration:
            manifest['aim_calibration'] = True
        with self.guard:
            active = self.active_run() is not None
            pending = bool(self.queued_runs())
            queued = active or (pending and mode != 'flight')
            if pending and not queued:
                manifest['leave_queue_waiting'] = True
            config = (self.root/'practice.json').read_text(encoding='utf-8')
            settings = json.loads(config)
            paired_ctf_rules = bool((evaluation or aim_calibration) and settings.get('season_runtime'))
            if paired_ctf_rules:
                settings['paired_ctf_rules'] = True
                manifest['capture_limit'] = 5
                config = json.dumps(settings, indent=2)+'\n'
            manifest['provenance'] = request_provenance(settings, map_id, mode, paired_ctf_rules=paired_ctf_rules)
            identifier = datetime.now().strftime('run%Y%m%d%H%M%S')+uuid4().hex[:8]
            path = self.directory/identifier
            path.mkdir()
            manifest['id'] = identifier
            publish(path/'practice.json', config)
            publish(path/'request.json', json.dumps(manifest)+'\n')
            if queued:
                publish(path/'status.json', json.dumps(dict(status='Queued', queued_at=time.time_ns()))+'\n')
            else:
                self.start_worker(path, manifest)
            return identifier

    def launch_season(self, matches, seconds, size, waves):
        if type(size) is not int or not 2 <= size <= MAX_TEAM_BOTS or type(waves) is not int or not 1 <= waves <= 5:
            raise ValueError(f'Choose 2–{MAX_TEAM_BOTS} bots per team and 1–5 waves per game launch.')
        maps = list(self.maps())
        if not maps:
            raise ValueError('Install a training map catalog before starting a season.')
        with self.guard:
            active = self.active_run() is not None or bool(self.queued_runs())
            config = (self.root/'practice.json').read_text(encoding='utf-8')
            settings = json.loads(config)
            queued_at = time.time_ns()
            first = None
            staged = [(map_id, evaluation) for evaluation in (False, True) for map_id in maps]
            for sequence, (map_id, evaluation) in enumerate(staged):
                index = sequence % len(maps) + 1
                identifier = datetime.now().strftime('run%Y%m%d%H%M%S')+uuid4().hex[:8]
                path = self.directory/identifier
                path.mkdir()
                if first is None:
                    first = path
                stage = 'Evaluation' if evaluation else 'Training'
                request = dict(id=identifier, mode='season', season=first.name, map=map_id,
                               matches=SEASON_EVALUATION_MATCHES if evaluation else matches,
                               seconds=seconds, team_size=size, bots=2*size, waves_per_launch=1 if evaluation else waves,
                               evaluation=evaluation, season_map=index, season_maps=len(maps),
                               label=f'Season · {stage} · Map {index}/{len(maps)} · {size}v{size}',
                               provenance=request_provenance(settings, map_id, 'season'))
                publish(path/'request.json', json.dumps(request)+'\n')
                publish(path/'practice.json', config)
                publish(path/'status.json', json.dumps(dict(status='Queued', queued_at=queued_at+sequence))+'\n')
            if not active:
                self.dispatch(first)
            return first.name

    def resume(self, identifier):
        if not RUN_ID.fullmatch(identifier):
            raise ValueError('Invalid training run.')
        with self.guard:
            if self.active_run() is not None:
                raise BlockingIOError('Stop the active run before resuming another one.')
            path = self.directory/identifier
            manifest = path/'request.json'
            if not manifest.is_file():
                raise ValueError('Training run was not found.')
            request = json.loads(manifest.read_bytes())
            status = path/'status.json'
            state = run_status(path).get('status', 'Interrupted')
            checkpoint = path/'progress.json'
            if state not in RESUMABLE or not has_remaining_matches(
                    request, json.loads(checkpoint.read_bytes()) if checkpoint.is_file() else None):
                raise BlockingIOError('This run has no compatible unfinished matches to resume.')
            (path/'stop.request').unlink(missing_ok=True)
            (path/'pause.request').unlink(missing_ok=True)
            status.unlink(missing_ok=True)
            self.start_worker(path, request)

    def start_worker(self, path, request):
        args = [part for key, option in (('attackers', '--attackers'), ('defenders', '--defenders'),
                ('team_size', '--team-size'), ('waves_per_launch', '--waves-per-launch'), ('course', '--flight-course'))
                if key in request for part in (option, str(request[key]))]
        if request.get('evaluation'):
            args.append('--evaluation')
        if request.get('aim_calibration'):
            args.append('--aim-calibration')
        try:
            config = path/'practice.json'
            if not config.is_file():
                publish(config, (self.root/'practice.json').read_text(encoding='utf-8'))
            (path/'cooperative-stop').touch()
            publish(self.active_marker, path.name+'\n')
            with (path/'stdout.log').open('ab') as stdout, (path/'stderr.log').open('ab') as stderr:
                self.process = subprocess.Popen([sys.executable, '-B', '-u', str(self.runner),
                    str(config), str(path), '--mode', request['mode'],
                    '--matches', str(request['matches']), '--seconds', str(request['seconds']),
                    '--bots', str(request.get('bots', 5)), '--map', request.get('map', MAP), *args], cwd=self.runner.parent,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:
            publish(path/'status.json', '{"status":"Failed"}\n')
            raise
