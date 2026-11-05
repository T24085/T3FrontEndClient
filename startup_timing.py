"""Small bounded startup phase observations, not a runtime-readiness signal."""
from contextlib import contextmanager
import json
import time

from verified_file_cache import metrics


class StartupTiming:
    PHASES = frozenset(('package-verification', 'map-verification', 'original-verification',
                        'original-staging', 'runtime-staging', 'map-staging', 'native-launch',
                        'client-preparation', 'prepared-validation'))

    def __init__(self, emit=None):
        self.emit = emit or (lambda line: print(line, flush=True))
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        self.records = []

    @contextmanager
    def phase(self, name):
        if name not in self.PHASES or len(self.records) >= len(self.PHASES) or any(x['phase'] == name for x in self.records):
            raise ValueError('Unknown, duplicate or excessive startup phase.')
        record = {'phase': name, 'state': 'started'}
        self.records.append(record)
        before, cpu, counters = time.perf_counter(), time.process_time(), metrics()
        self.emit('STARTUP_PHASE|' + json.dumps(record, separators=(',', ':')))
        try:
            yield
        except BaseException:
            record['state'] = 'failed'
            raise
        else:
            record['state'] = 'complete'
        finally:
            after = metrics()
            record.update(elapsed_seconds=time.perf_counter() - before,
                          cpu_seconds=time.process_time() - cpu,
                          bytes_hashed=after['bytes_hashed'] - counters['bytes_hashed'],
                          digest_cache_hits=after['cache_hits'] - counters['cache_hits'])
            self.emit('STARTUP_PHASE|' + json.dumps(record, separators=(',', ':')))

    def snapshot(self):
        return {'phases': [dict(x) for x in self.records],
                'elapsed_seconds': time.perf_counter() - self.started,
                'cpu_seconds': time.process_time() - self.cpu_started,
                'peak_process_family_memory': 'unmeasured',
                'scope': 'launcher work only; excludes native game initialization'}
