"""Owned development client session started from an authenticated lobby state."""
import importlib.util
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import uuid

from community_transport import CommunityError
from map_catalog import verified_catalog
from runtime_health import runtime_failure
from startup_progress import PHASES, observed_phase, observed_failure, runtime_phase


class CommunityGame:
    def __init__(self, lobby, package, game_source, workspace, artifacts, *, catalog_loader=verified_catalog, map_sync=None):
        self.lobby = lobby
        self.catalog_loader = catalog_loader
        self.map_sync = map_sync
        self.package = Path(package).resolve(strict=True)
        self.game_source = Path(game_source).resolve(strict=True)
        self.workspace = Path(workspace).resolve()
        self.artifacts = Path(artifacts).resolve()
        if self.workspace == self.game_source or self.game_source in self.workspace.parents:
            raise ValueError('Client workspace must be outside the original game.')
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        spec = importlib.util.spec_from_file_location('client_job_owner', self.package / 'lib/owned_native_session.py')
        self.owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.owner)
        self.lock = threading.RLock()
        self.status = 'idle'
        self.error = None
        self.run = None
        self.current_artifacts = None
        self.thread = None
        self.stop_requested = False
        self.failure_reason = None
        self.cancellation_written = False
        self.startup_phase = None
        self.startup_failure = None
        self.preparation_status = 'idle'
        self.preparation_error = None
        self.preparation_artifacts = None
        self.preparation_thread = None
        self.preparation_descriptor = None
        self.preparation_stop_requested = False
        self.preparation_revision = None
        self.role = 'player'
        self.watch_id = None
        self.match_id = None
        self.watch_releasing = False

    def _release_watch(self):
        """Retain the grant until both process cleanup and server release succeed."""
        with self.lock:
            if self.status in ('starting', 'playing', 'stopping', 'quarantined'):
                return False
            watch_id = self.watch_id
            if watch_id is None:
                return True
            if self.watch_releasing:
                return False
            self.watch_releasing = True
        try:
            self.lobby.release_spectator(watch_id)
            with self.lock:
                if self.watch_id == watch_id:
                    self.watch_id = None
            return True
        finally:
            with self.lock:
                self.watch_releasing = False

    def start_spectating(self, watch_id):
        if not isinstance(watch_id, str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}', watch_id):
            raise CommunityError('Invalid spectator session identity.')
        return self._start(watch_id=watch_id)

    def stop_spectating(self):
        with self.lock:
            if self.role != 'spectator':
                return
        self.stop()
        self._release_watch()

    def _startup_contract(self):
        path=self.package/'package-manifest.json'
        return json.loads(path.read_text(encoding='utf-8')).get('startup_contract') if path.is_file() else None

    def prepare(self, *, for_start=False, revision=None):
        """Prepare files only; no match endpoint, profile or native game yet."""
        if self._startup_contract() != 'prepared-client-v1': return False
        with self.lock:
            if self.preparation_status=='quarantined':return False
            if not for_start and self.preparation_status in ('failed','stopped'):return False
            if self.status not in ('idle','stopped','finished','failed') and not (for_start and self.status=='starting'):
                return False
            if self.preparation_status in ('preparing','ready'): return True
            if self.preparation_thread and self.preparation_thread.is_alive(): return False
            if self.map_sync is not None and not for_start:
                revision = self.map_sync.current[0]
            artifacts=self.artifacts/('prepare-'+uuid.uuid4().hex)
            artifacts.mkdir(exist_ok=False)
            self.preparation_artifacts=artifacts
            self.preparation_status,self.preparation_error='preparing',None
            self.preparation_descriptor=None
            self.preparation_stop_requested=False
            self.preparation_revision=revision
            argv=[str(self.package/'python/python.exe'),'-B','-u',str(self.package/'client.py'),
                  '--prepare-only','--game-dir',str(self.game_source),'--workspace',str(self.workspace)]
            if revision is not None:
                argv += ['--map-revision', revision]
            self.preparation_thread=threading.Thread(target=self._prepare,args=(argv,artifacts),name='client-preparation',daemon=True)
            self.preparation_thread.start()
            return True

    def _prepare(self, argv, artifacts):
        failure_status='quarantined'
        try:
            result=self.owner.run_owned_job(argv,self.package,dict(os.environ),artifacts/'owner',
                                           budget=900,cancellation_path=artifacts/'stop.json')
            active=result.get('job_active_processes_after_cleanup',result.get('job_active_processes_at_parent_exit'))
            log=artifacts/'owner/stdout.log'
            if log.is_file() and log.stat().st_size>1048576: raise CommunityError('Preparation output exceeded its bound.')
            lines=log.read_text(errors='replace').splitlines() if log.is_file() else []
            descriptors=[line[len('CLIENT_PREPARED|'):]for line in lines if line.startswith('CLIENT_PREPARED|')]
            if active!=0: raise CommunityError('Client preparation cleanup could not be confirmed.')
            failure_status='failed'
            with self.lock:
                if self.preparation_stop_requested:
                    self.preparation_status='stopped';return
            if result.get('status')!='terminal' or result.get('exit_code')!=0 or len(descriptors)!=1:
                raise CommunityError(observed_failure(lines) or 'Client file preparation did not finish.')
            descriptor=json.loads(descriptors[0]);path=Path(descriptor['path'])
            if (path.name!='prepared.json' or path.parent.parent!=self.workspace or not path.parent.name.startswith('client-')
                    or path.resolve(strict=True)!=path or path.stat().st_size>4*1024*1024
                    or hashlib.sha256(path.read_bytes()).hexdigest()!=descriptor['sha256']):
                raise CommunityError('Client preparation returned an invalid owned descriptor.')
            with self.lock:
                if self.preparation_stop_requested:self.preparation_status='stopped'
                else:self.preparation_descriptor=descriptor;self.preparation_status='ready'
        except Exception as exc:
            with self.lock:self.preparation_status=failure_status;self.preparation_error=str(exc)

    def _prepared_for_join(self, revision=None):
        with self.lock:
            stale = self.preparation_revision != revision
            previous = self.preparation_thread if stale else None
            if stale:
                self._cancel_preparation()
        if previous:
            previous.join()
        with self.lock:
            if self.stop_requested:
                return None
            if stale and self.preparation_status != 'quarantined':
                self.preparation_status = 'idle'
            if not self.prepare(for_start=True, revision=revision):
                raise CommunityError(self.preparation_error or 'Client preparation is unavailable.')
        with self.lock:thread=self.preparation_thread
        if thread:thread.join()
        with self.lock:
            if self.stop_requested:return None
            if self.preparation_status!='ready' or not self.preparation_descriptor:
                raise CommunityError(self.preparation_error or 'Client preparation is not ready.')
            result=self.preparation_descriptor
            self.preparation_descriptor=None;self.preparation_status='spent'
            return result

    def start(self, *, expected_map=None, expected_match_id=None):
        return self._start(expected_map=expected_map, expected_match_id=expected_match_id)

    def _start(self, *, watch_id=None, expected_map=None, expected_match_id=None):
        self._release_watch()
        # Desktop calls this on a worker. Reserve the session briefly, then keep
        # expensive verification outside the snapshot lock used by the Tk loop.
        with self.lock:
            if self.status not in ('idle', 'stopped', 'finished', 'failed') or self.watch_id is not None:
                raise CommunityError('A game session is already active.')
            self.role = 'spectator' if watch_id is not None else 'player'
            self.watch_id, self.match_id = watch_id, None
            self.status, self.error, self.run = 'starting', None, None
            self.current_artifacts, self.thread = None, None
            self.stop_requested = False
            self.failure_reason, self.cancellation_written = None, False
            self.startup_phase = 'checking_match'
            self.startup_failure = None
        try:
            begin_attempt = getattr(self.lobby, 'begin_game_attempt', None)
            if begin_attempt is not None:
                begin_attempt()
            target_loader = (lambda: self.lobby.spectator_target(watch_id)) if watch_id is not None else self.lobby.match_target
            target = target_loader()
            if expected_match_id is not None and target.get('matchId') != expected_match_id:
                raise CommunityError('The match changed. Refresh the lobby before joining.')
            if expected_map is not None and target.get('map') != expected_map:
                raise CommunityError('The selected map changed. Refresh the lobby before joining.')
            if watch_id is not None:
                if (target.get('role') != 'spectator' or target.get('watchId') != watch_id
                        or not re.fullmatch('[0-9a-f]{32}', target.get('matchId', ''))):
                    raise CommunityError('The spectator target is invalid.')
                self.match_id = target['matchId']
            manifest = json.loads((self.package / 'package-manifest.json').read_text(encoding='utf-8')) if (self.package / 'package-manifest.json').is_file() else {}
            startup_contract = manifest.get('startup_contract')
            if watch_id is not None and manifest.get('spectator_contract') != 'native-spectator-v1':
                raise CommunityError('Update the community client to spectate this match.')
            if startup_contract not in (None, 'verified-child-map-v1', 'prepared-client-v1'):
                raise CommunityError('Unsupported client startup contract. Update the community client.')
            if startup_contract is None:
                with self.lock: self.startup_phase = 'verifying_maps'
                try: catalog = self.catalog_loader(self.package)
                except (OSError,ValueError,TypeError) as exc:
                    raise CommunityError('Client map files could not be verified.') from exc
                if catalog.get(target['map']) != target['contentHash']:
                    raise CommunityError('Your map files do not match this match. Update the community client.')
            prepared=None
            if startup_contract=='prepared-client-v1':
                revision = None
                if self.map_sync is not None:
                    with self.lock:self.startup_phase='checking_maps'
                    revision = self.map_sync.revision_for(target['map'], target['contentHash'])
                with self.lock:self.startup_phase='preparing_client'
                prepared=self._prepared_for_join(revision)
                if prepared is None:
                    with self.lock:self.status='stopped'
                    self._release_watch()
                    return self.status
            if target_loader() != target:
                raise CommunityError('The match changed while verifying your map. Please try again.')
            endpoint = target['endpoint']
            ident = uuid.uuid4().hex
            argv = [str(self.package / 'python/python.exe'), '-B', '-u', str(self.package / 'client.py'),
                    '--endpoint', endpoint, '--game-dir', str(self.game_source), '--workspace', str(self.workspace)]
            if startup_contract in ('verified-child-map-v1','prepared-client-v1') or watch_id is not None:
                argv += ['--expected-map', target['map'], '--expected-content-hash', target['contentHash']]
            if watch_id is not None:
                argv += ['--spectate', '--match-id', target['matchId'], '--watch-id=' + watch_id]
            if prepared is not None:
                argv += ['--prepared',prepared['path'],'--prepared-sha256',prepared['sha256']]
            if self.lobby.test_source:
                argv += ['--headless', '--test-source', self.lobby.test_source]
            with self.lock:
                if self.stop_requested:
                    self.status = 'stopped'
                    cancelled = True
                else:
                    cancelled = False
                if not cancelled:
                    artifacts = self.artifacts / ident
                    artifacts.mkdir(exist_ok=False)
                    self.current_artifacts = artifacts
                    self.startup_phase = 'launching_client'
                    self.thread = threading.Thread(target=self._run, args=(argv, artifacts), name='community-client-' + ident[:8], daemon=True)
                    self.thread.start()
                    return self.status
            self._release_watch()
            return self.status
        except Exception as exc:
            with self.lock:
                self.status, self.error = ('stopped', None) if self.stop_requested else ('failed', str(exc))
            self._release_watch()
            raise

    def _session(self, artifacts):
        log = artifacts / 'owner/stdout.log'
        if log.is_file():
            if log.stat().st_size > 1048576:
                raise CommunityError('Client output exceeded its bound.')
            lines = log.read_text(errors='replace').splitlines()
            phase = observed_phase(lines)
            if phase is not None: self.startup_phase = phase
            failure = observed_failure(lines)
            if failure is not None: self.startup_failure = failure
            for line in lines:
                if line.startswith('Session: '):
                    path = Path(line[9:]).resolve()
                    if path.parent != self.workspace or not path.name.startswith('client-'):
                        raise CommunityError('Unexpected client session path.')
                    self.run = path
                    break
        return self.run

    def _run(self, argv, artifacts):
        try:
            result = self.owner.run_owned_job(argv, self.package, dict(os.environ), artifacts / 'owner',
                                              budget=None, cancellation_path=artifacts / 'stop.json')
            active = result.get('job_active_processes_after_cleanup', result.get('job_active_processes_at_parent_exit'))
            with self.lock:
                if active != 0:
                    self.status, self.error = 'quarantined', 'Client process cleanup could not be confirmed.'
                elif self.failure_reason is not None:
                    self.status, self.error = 'failed', self.failure_reason
                elif self.stop_requested and result['status'] == 'cancelled_by_owner_request':
                    self.status = 'stopped'
                else:
                    run = self._session(artifacts)
                    record_path = run / 'execution/execution.json' if run else None
                    record = json.loads(record_path.read_text()) if record_path and record_path.is_file() else {}
                    if (result['status'] == 'terminal' and result.get('exit_code') == 0
                            and record.get('status') == 'terminal' and record.get('exit_code') == 0):
                        self.status = 'finished'
                    else:
                        self.status, self.error = 'failed', self.startup_failure or 'The game client did not close normally.'
        except Exception as exc:
            with self.lock:
                self.status, self.error = 'quarantined', 'Client ownership or cleanup failed: ' + repr(exc)
        # A native Job with unknown cleanup keeps its watcher grant and ownership.
        try:
            self._release_watch()
        except Exception as exc:
            with self.lock:
                self.error = 'Spectator admission release will be retried: ' + str(exc)

    def snapshot(self):
        with self.lock:
            if self.status in ('starting','playing') and self.current_artifacts is not None:
                run = self._session(self.current_artifacts)
                event_file = run / 'events.txt' if run else None
                if event_file and event_file.is_file():
                    if event_file.stat().st_size > 1048576:
                        raise CommunityError('Client evidence exceeded its bound.')
                    lines = event_file.read_text(errors='replace').splitlines()
                    phase = runtime_phase(lines, role=self.role, match_id=self.match_id, watch_id=self.watch_id)
                    if phase is not None: self.startup_phase = phase
                    if runtime_failure(lines):
                        self.failure_reason = self.error = 'The game client runtime reported an error.'
                        self.status = 'stopping'
                    elif (self.status == 'playing' and self.role == 'player'
                          and getattr(self.lobby, 'reconnect_requires_new_game', False)
                          and next((line for line in reversed(lines) if line in
                                    ('REMOTE_PAWN_READY|role=client', 'RECONNECTING_TO_FIXED_SERVER')), None)
                          == 'RECONNECTING_TO_FIXED_SERVER'):
                        self.failure_reason = self.error = 'Disconnected from the match. Use Join game to reconnect.'
                        self.status = 'stopping'
                    elif self.status == 'starting' and phase == 'playing':
                        self.status = 'playing'
                        self.startup_phase = 'playing'
                elif self.status == 'playing':
                    raise CommunityError('Game client status evidence is unavailable.')
            if self.status == 'stopping' and self.current_artifacts is not None and not self.cancellation_written:
                self._request_cancel()
            preparation=self.preparation_snapshot()
            progress=PHASES.get(self.startup_phase) if self.status=='starting' else None
            if self.status=='starting' and self.startup_phase=='preparing_client' and preparation['status']=='preparing':
                progress=preparation['progress']
            if self.status=='starting' and self.startup_phase=='checking_maps':
                progress=self.map_sync.status or 'Checking map files…'
            return {'status':self.status, 'error':self.error, 'run':str(self.run) if self.run else None,
                    'role':self.role, 'watchId':self.watch_id,
                    'progress':progress,
                    'preparation':preparation}

    def preparation_snapshot(self):
        with self.lock:
            progress=None
            if self.preparation_status=='preparing' and self.preparation_artifacts:
                log=self.preparation_artifacts/'owner/stdout.log'
                if log.is_file():
                    if log.stat().st_size>1048576:raise CommunityError('Preparation output exceeded its bound.')
                    lines=log.read_text(errors='replace').splitlines()
                    progress=PHASES.get(observed_phase(lines))
                    for line in reversed(lines):
                        match=re.fullmatch(r'CLIENT_PREPARATION_PROGRESS\|([0-9]{1,5})/([0-9]{1,5})',line)
                        if match:
                            done,total=map(int,match.groups())
                            if 0<=done<=total<=10000 and total>0:
                                progress=f'Preparing game files: {done:,} / {total:,} files…'
                                break
            return {'status':self.preparation_status,'error':self.preparation_error,
                    'progress':progress or ('Game files ready.' if self.preparation_status=='ready' else 'Preparing game files in the background…')}

    def stop(self):
        with self.lock:
            self._cancel_preparation()
            if self.status not in ('starting', 'playing', 'stopping'):
                return
            self.stop_requested = True
            self.status = 'stopping'
            if self.current_artifacts is not None and not self.cancellation_written: self._request_cancel()

    def _cancel_preparation(self):
        self.preparation_stop_requested=True
        if self.preparation_status=='preparing' and self.preparation_artifacts:
            path=self.preparation_artifacts/'stop.json'
            temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps({'cancel':True,'reason':'Client preparation cancelled.'}))
            os.replace(temporary,path)

    def _request_cancel(self):
        path = self.current_artifacts / 'stop.json'
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'cancel':True,'reason':self.failure_reason or 'Player stopped the owned game session.'}))
            os.replace(temporary, path)
            self.cancellation_written = True
        except OSError as exc:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            raise CommunityError('The game could not yet be stopped; cleanup will be retried.') from exc

    def wait(self, timeout):
        with self.lock:
            thread = self.thread
        if thread:
            thread.join(timeout)
        return self.snapshot()
