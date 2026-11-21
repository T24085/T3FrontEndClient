"""Play optional map soundtracks through the Windows media player."""
from base64 import b64encode
from contextlib import contextmanager
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import threading


REMOTE_TRACKS = {}
T1_TRACKS = tuple(f't1-{number:02}.mp3' for number in range(1, 11))
T2_BIOMES = ('badlands', 'desert', 'ice', 'lush', 'volcano')
TRACKS = (*T1_TRACKS, *(f't2-{biome}.mp3' for biome in T2_BIOMES), 'rollercoaster.mp3')

def playlists():
    routes = {Path(track).stem.replace('-', '_'): (track,) for track in TRACKS}
    for first in range(1, len(T1_TRACKS) + 1):
        routes[f'playlist_t1_{first}'] = T1_TRACKS[first - 1:] + T1_TRACKS[:first - 1]
    return routes


def source_tracks(directory):
    """Locate the supplied MP3s in their two edition folders."""
    sources = {}
    for number, name in enumerate(T1_TRACKS, 1):
        found = list((directory / 'T1 Music').glob(f'* - Audio track {number}.mp3'))
        if len(found) != 1:
            raise ValueError(f'Expected one T1 audio track {number}.')
        sources[name] = found[0]
    for biome in T2_BIOMES:
        sources[f't2-{biome}.mp3'] = directory / 'T2 Music' / f'Tribes 2 {biome.title()} Music.mp3'
    sources['rollercoaster.mp3'] = directory / 'sands of the void.mp3'
    for source in sources.values():
        if not source.is_file() or not 0 < source.stat().st_size <= 16 * 1024 * 1024:
            raise ValueError(f'Missing or invalid soundtrack: {source.name}')
    return sources


def fetch_track(fetch, chunks, expected):
    data = bytearray()
    for pin, size in chunks:
        chunk = fetch('starter-file-' + pin + '.bin', size)
        if len(chunk) != size or sha256(chunk).hexdigest() != pin:
            raise ValueError('Soundtrack download failed chunk verification.')
        data.extend(chunk)
    if sha256(data).hexdigest() != expected:
        raise ValueError('Soundtrack download failed track verification.')
    return data


def download_tracks(root, run, workspace, routes, pending, stop):
    from starter_update import DIRECT_CHANNEL, atomic_write, fetcher, inside
    import time

    try:
        cache = inside(workspace, 'soundtrack-cache')
        cache.mkdir(exist_ok=True)
    except (OSError, ValueError):
        return
    request = run / 'map-soundtrack-request'
    retry = {}
    while pending and not stop.is_set():
        try:
            desired = request.read_text(encoding='ascii').split(' ', 1)[0]
        except (OSError, ValueError):
            desired = None
        name = next((track for track in routes.get(desired, ())
                     if track in pending and time.monotonic() >= retry.get(track, 0)), None)
        if name is None:
            stop.wait(0.25)
            continue
        pin, chunks = REMOTE_TRACKS[name]
        try:
            cached = inside(cache, pin + '.mp3')
            data = None
            size = sum(chunk_size for _, chunk_size in chunks)
            if cached.is_file() and cached.stat().st_size == size:
                with cached.open('rb') as stream:
                    data = stream.read(size + 1)
            if data is None or len(data) != size or sha256(data).hexdigest() != pin:
                download = fetcher(channel=DIRECT_CHANNEL, root=root)
                data = fetch_track(download, chunks, pin)
                atomic_write(cached, data)
            if stop.is_set():
                return
            atomic_write(pending[name], data)
            del pending[name]
        except (OSError, ValueError, KeyError):
            retry[name] = time.monotonic() + 15


@contextmanager
def soundtrack_player(root, run, package, *, enabled, workspace=None):
    """Return available soundtrack routes while an owned media helper is available."""
    if not enabled or sys_platform_unsupported():
        yield ()
        return
    included = {row['path'] for row in package['files']}
    local = {track: root / 'music' / track for track in TRACKS if 'music/' + track in included}
    routes = {
        name: tracks
        for name, tracks in playlists().items()
        if all(track in local or (workspace is not None and track in REMOTE_TRACKS)
                                       for track in tracks)
    }
    if not routes:
        yield ()
        return
    remote = {track: run / 'map-soundtrack-tracks' / track
              for tracks in routes.values() for track in tracks if track not in local}
    paths = local | remote
    available = {name: [str(paths[track]) for track in tracks] for name, tracks in routes.items()}
    if remote:
        (run / 'map-soundtrack-tracks').mkdir()
    config = run / 'map-soundtrack.json'
    config.write_text(json.dumps(available), encoding='ascii')
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = '$session=' + quote(run) + '\n$parentId=' + str(os.getpid()) + '\n' + _PLAYER
    executable = (Path(os.environ.get('SystemRoot', r'C:\Windows'))
                  / 'System32/WindowsPowerShell/v1.0/powershell.exe')
    try:
        process = subprocess.Popen(
            [str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-Sta',
             '-EncodedCommand', b64encode(command.encode('utf-16-le')).decode('ascii')],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError:
        yield ()
        return
    stop = threading.Event()
    downloader = None
    if remote:
        downloader = threading.Thread(target=download_tracks, daemon=True,
                                      args=(root, run, workspace, routes, remote, stop))
        downloader.start()
    try:
        yield tuple(available)
    finally:
        stop.set()
        try:
            (run / 'map-soundtrack-stop').touch()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=2)
        if downloader is not None:
            downloader.join(timeout=1)


def sys_platform_unsupported():
    return os.name != 'nt' or hasattr(ctypes.WinDLL('ntdll'), 'wine_get_version')


_PLAYER = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore
$config = Get-Content -LiteralPath (Join-Path $session 'map-soundtrack.json') -Raw | ConvertFrom-Json
$request = Join-Path $session 'map-soundtrack-request'
$ready = Join-Path $session 'map-soundtrack-ready'
$stop = Join-Path $session 'map-soundtrack-stop'
$parent = Get-Process -Id $parentId
$dispatcher = [Windows.Threading.Dispatcher]::CurrentDispatcher
$player = New-Object Windows.Media.MediaPlayer
$player.Volume = 0
$current = ''
$index = 0
$readyAt = 0
$openedAt = 0
$failed = $false
$playing = $false
$opened = $false
try {
    while (!$parent.HasExited -and ![IO.File]::Exists($stop)) {
        $dispatcher.Invoke([Action]{}, [Windows.Threading.DispatcherPriority]::Background)
        $target = ''
        $gain = 0
        $shouldPlay = $false
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        try {
            if ($now - ([DateTimeOffset][IO.File]::GetLastWriteTimeUtc($request)).ToUnixTimeSeconds() -le 4) {
                $data = [IO.File]::ReadAllText($request)
                if ($data -match '^([A-Za-z][A-Za-z0-9_]{0,39}) ([0-9]{1,4}) ([01])$') {
                    $entry = $config.PSObject.Properties[$Matches[1]]
                    if ($entry -and [int]$Matches[2] -le 1000) {
                        $target = $entry.Name
                        $tracks = @($entry.Value)
                        $gain = [int]$Matches[2]
                        $shouldPlay = $Matches[3] -eq '1'
                    }
                }
            }
        } catch [IO.IOException] {
            Start-Sleep -Milliseconds 125
            continue
        }
        if ($target -ne $current) {
            $player.Close()
            $playing = $false
            $failed = $false
            $readyAt = 0
            $current = $target
            $index = 0
            $opened = $false
            [IO.File]::Delete($ready)
        }
        if ($current -and !$opened -and [IO.File]::Exists($tracks[$index])) {
            $player.Open([uri]$tracks[$index])
            $openedAt = $now
            $opened = $true
        }
        if ($current -and $opened -and !$failed) {
            if ($player.HasAudio -and $player.NaturalDuration.HasTimeSpan) {
                if ($now -ne $readyAt) {
                    try {
                        [IO.File]::WriteAllText($ready, "$current $now")
                        $readyAt = $now
                    } catch [IO.IOException] {}
                }
                $player.Volume = $gain / 1000.0
                if ($shouldPlay -and !$playing) {
                    $player.Play()
                    $playing = $true
                } elseif (!$shouldPlay -and $playing) {
                    $player.Pause()
                    $playing = $false
                }
                if ($playing -and $player.Position -ge $player.NaturalDuration.TimeSpan) {
                    $index = ($index + 1) % $tracks.Count
                    $player.Close()
                    $playing = $false
                    $opened = $false
                }
            } elseif ($now - $openedAt -ge 4) {
                $failed = $true
                [IO.File]::Delete($ready)
            }
        }
        Start-Sleep -Milliseconds 125
    }
} finally {
    $player.Close()
    [IO.File]::Delete($ready)
}
"""
