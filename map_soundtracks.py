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


# Content addresses from the verified signed r94 Direct release. Audio is stored outside Git.
REMOTE_TRACKS = {'rollercoaster.mp3': ('a18590a5cfcd38d90281131f4f163bfb2f142618e5f632df7f08eb634291392c',
                       (('d74b8c34571fb13a0e7db7b54537691f5fe2d52f768e7add2a4026b303b6540b', 786432),
                        ('37ac6434e3a3bbd8b3c1b771f78a724d0df1efc60c70fb94057e625443bc2f56', 786432),
                        ('988c8c488acac9c01cade9806926321474ff7eb2ed6ae84539430a1abfe002fd', 786432),
                        ('46c919cb5959ffb138402d94663286af30c8ed24b1fbd353a9e34e6b03657bb7', 786432),
                        ('fd623614f424b31cd03c3ac9aec5896b9cbe35ac581d4c108465e47860e5b701', 786432),
                        ('87cef3ecaa21cc3ead5e50ff296e110d58b5f784f679b1ef295ae7755d2d5141', 786432),
                        ('7bac7aa79fb393cf96f85d7a51e501d226bf2e0b73853a9ceb7f05f6aa3e25c3', 480223))),
 't1-01.mp3': ('63ccbba1cec3cb22aa6c30487dbf4d514dabfdff654517dbdd318256e21fa857',
               (('d7fa4c8badd0c823a131e712949e3764e433e5e7619f7708d68951c0fee71979', 786432),
                ('7b2f6a712749fd2e80025d147307ee4aac7207a077bac0caec3bc468331330db', 786432),
                ('8d17fdb61d259b6242c3593ac0433b27ea3c9652f89693a31cb16212605f4c1b', 786432),
                ('7a4816fd1fa2e91bf68287d1bc9c23cfff013983f125cfeeb0462579a3fc9d21', 786432),
                ('ce738361b7d9873503f58eee4647b84b8bc7a570d45be8c5b6822dda41392824', 786432),
                ('6fb26308c030be9bc0622f7291fc565f8d348f7944733a091758706eab0c50b8', 404273))),
 't1-02.mp3': ('be5a70b28798e33ae556ae1ccdf25a46f9bb8a5aec5b2d8ba5aa089ea7233721',
               (('a83336f0385bb78ecfc4e4902b2162d1e3ee63425782616343082d92e91c8077', 786432),
                ('a8d06c407c4e310eeda51b0af9383e22c72b4af37e71fda6899466da9770e678', 786432),
                ('7ff45d5ab8b57eba87c58590a38c6fb2303f4cd0ce1abed8819c91d3dc09c4f0', 786432),
                ('46fd71cd416584644e4b547654b368bf6a0ddf61c4daddafe58ddb26f6d058eb', 786432),
                ('05402e818423f81852663fdc31f9a4e88a4c4e9a20339f7bedf3fb34335023a4', 433415))),
 't1-03.mp3': ('c5204c2fe5863f78f125b96da3f32da53f5fc5dca0377b7529627928cf9e8b85',
               (('5274c9e695d2ff4d7366913da6acd393f3325bb6e7acb048cf902c2fb1e022b8', 786432),
                ('d058cd6ecaf8df25fabb43a6841a69724a8d037a745675f34f2846a849bf6255', 786432),
                ('d96b835bcc47c7a1e04e71659ba34eb9d109ee15ebd912a3b4fdb1a719473d76', 786432),
                ('7add8cd568bb68a60ce7728896ad32c866fc6bc0b268881124b53fd2b0f55544', 786432),
                ('7d5982ad1e2e17a5c2e81e7744e1fabb26c70f735ae2c4a8a699765c2e638096', 786432),
                ('0290ffda32e40709d6e9979144a4f6983911bd296f7be0e2e2792eee603d2276', 388045))),
 't1-04.mp3': ('1b6a764416ddc476578dc3880354d62485048bbda260bd48e044304034796c34',
               (('d44716092128632c46c5628af72ed200292afb87b823929e2fd7f7698d674afa', 786432),
                ('694ce3caf3c1e63650b1674de0df6ecc4ed19470210632fe51ed79263e2d573d', 786432),
                ('ba01c5373ac3d77072fb6dc96821e0de73c6f9962d1649320c87b562510ceeef', 786432),
                ('1e4333ac8a1ab944d65ccc0a4af007ce0bf916c642486218e76ab1e77ecbaf31', 786432),
                ('60f3cfb4ea9e6274442c9bfe894ca18e620060f76820516051eea2b51b44bfed', 786432),
                ('f92de8f76e0f661b0761855417bbafd90f8517debd4010213f3a3cd805722633', 80508))),
 't1-05.mp3': ('ce2136543beb60245dad4ff153752c20166c77e67a3fbf7864628898ac9a98be',
               (('755ccd093edae02da9a35bf1594a35c469396b86182597ba1f1c1338ae999e07', 786432),
                ('ba1b29c197d258264938768533b14d727f9846fc204d53ce920c4bf4a3d67a3b', 786432),
                ('55d1e6f496e0674016aa7d3a10cdaee036d970c700bd4ffbcec93ce2bbf38885', 786432),
                ('e45e88163595472ae5c6db88d9854c7e6ceb79ed10591e2c4351f59c6d9456bb', 786432),
                ('c31f52fb70eeaca33b2c40a2f0e7b0e03e974ac64a84c2575e7299fb31a91dfe', 786432),
                ('3e1ecc77b0180c6d949e7aaf138300b4beabf671f198318d1c69832614239699', 327350))),
 't1-06.mp3': ('f7d5f43206f26f7ad94e97cf43fb878d2073ccc0fe69ec9c1b1a007747a31580',
               (('b01bf4f53ed36b303358838f1bb0466ef3734d7b04f26e5ad3995cc02c79f881', 786432),
                ('f6922d33cfb8e50f5274034ee96e672fa20e866430d7ef71cd9265cea2355ecd', 786432),
                ('0b07cf9d7604e2ff1409ec6386e36387a3ad12ea819c6b42da4c5f2d7f497780', 786432),
                ('1824d652196aa61649cedc2342df84e787f7e2a919ec463c297948b088011999', 786432),
                ('ae8889371a1338b9e3c0ed22ad8f538ea4cb7377f43d7655b775f9506b7bbe8d', 786432),
                ('204043478fa550097e3e01aa8ad7ab95b8cdf86611002147a8f08d2f5e7df7b3', 14744))),
 't1-07.mp3': ('5793df0dfcc9192d3fe3901610e93e2320c462a0cdd34c672e2a4e172cc76fbf',
               (('f81f8c460a77e0e51aa29c6f684b13f81b535eddcbc4773f3588bec6b3835fc1', 786432),
                ('25d23b7f982c509bce2b4cd1c558c95c7c10e623ab2a172e13da74f0e2c29cf2', 786432),
                ('0d0ad8e51f5e911422d7746b9459eab1ddf5e7b5ac4b04ffd3b1ae8acc330c22', 786432),
                ('2e3298761f0092d1ba9d3ac3d9af29c7b231a59a482e6f89b22a62f022505a8c', 786432),
                ('015724766089e0b19aa992caa7c2900dbf9c615af5dd3496f7f66cb33327202f', 786432),
                ('2641b9ea92cf494cd53de92bd48c5d3fdd6163ba24be9ef624577b7344467e83', 535906))),
 't1-08.mp3': ('e2fd2e9090470ac95d58fcadf11f65641903b3da44c2f481ff895e381d6679c8',
               (('5c0f8b371acf1677b80d23fd42b3f5be8944590282dad2ccefec3618e751e6c8', 786432),
                ('d9902da45f00f9a412caded7e8ff465f9bf0a9147a1546fbe07d824392b5421c', 786432),
                ('d33b4a90747faa557a8bedd6262cd0c0e31f4e21809938bef672175482513186', 786432),
                ('9e47acb369b2b64d84c800045380cea31b59b38c5a4c248a6c1d73ac5824e696', 786432),
                ('11b0d1f67fe9ee0bd1ed39544230539971be080fec5135a44b8fd8f459162a04', 733274))),
 't1-09.mp3': ('019ae1427365fce42e311f7ec76fc6367ee901500ef4959fb217688785eb1f9c',
               (('9d80b459b4d27e95d16ec8dbb75e595fe7587bbe6a9cdb7643b90086eacda632', 786432),
                ('41c68dee1a0a1cdccae79bb96ce73d653f4be09b1d0dc7b361fc4ae7df679a76', 786432),
                ('f7712b6cf8b666b6a4290e3473754ea7e11d91e5a588511b2013d8005884cbe4', 786432),
                ('ef4e774909e5755d0d3d451660f9c5ff518b6d517c94c7f8b9334709cfd2fa94', 786432),
                ('6c7bc2ac5b35f63bd2afa05559fd8ff10ffd66bcddd17c1235b69fb7b53efed6', 786432),
                ('df2e53c7f788718786af586380b2f440848e1e67dad7d6915fd0f37be9668934', 786432),
                ('19ae723403101e323f143126b3dbbd1793a0497160cef82b6896f13d341c2d59', 99155))),
 't1-10.mp3': ('7ca40155b129f707fc6ee2a93048bb9ce84bddf80fd5587ac06dc5ae5098be02',
               (('efb69b3927052625f894daa5991fe299c48908b0d68af3bcd63f00c635d569a2', 786432),
                ('52001781de2d80677985c3d291c231a86f10c1df50f0fb955428d8286c6d00f5', 786432),
                ('a44a4b0fd61cc9588dc352872532146cd820a6625f9123c903225de49a88e3d2', 786432),
                ('55325ceb73aabed9cc3780ac96c7445f51dd105cff0d1563f3b50a86cbdd8099', 786432),
                ('59e74926b9529427ba161e011207aae5a319deb8241aef9810f989f32fc19f56', 559418))),
 't2-badlands.mp3': ('c49b81127e481fa432669cd3d8768412c2305a51ab172824af9d2c1266de0c2a',
                     (('e9c9bf4d01d5929f5abb9749ae71f5ba125f6ca76a1c0c9513de3f5d836cc7a4', 786432),
                      ('b8da73a39e97dd717f4696d1cc278d8c19ce0f093c33f39a335f63a13ad095c9', 786432),
                      ('b883a8e79dcfe73644617eaf50cf43d964d48bf6fefc1c2807382c39667dd229', 786432),
                      ('7b3e96eb02dc1d35f84cc18893dd4cf79c3a7dc155e09a6f0dfc97601622763c', 786432),
                      ('5c6787e264f735e7e0906879d40d1fa453e492165864f6088f076bb739bef801', 786432),
                      ('95db6c7376b4082fd389e4825181d0fb07dd1ee16c9af00576e38e9996293efa', 786432),
                      ('76ec31488726ed0fd24d4b6f3430c5377a34e00973f2122ba88f87cc8b1b0add', 786432),
                      ('923428b88f38cf882bf2cd8c44617135bf4248aa5f55561921b860c6c8ed3d81', 254976))),
 't2-desert.mp3': ('af7dbda75d3c57dad6438daa4a98afb784a979ce1dffc1836a9be5fbc7227c66',
                   (('5a82dac5aa2d730db6c4af68190d3f2eb89c8e6f7b04457632d4cc2f11fa89ab', 786432),
                    ('197f3e4d4f2731db5c77eceaacdfdf79d60ace90a7dfa608c6d51e9420d5cdac', 786432),
                    ('9e642a3cee2aaa9a1ad72b2b604fee667869444bcec324f201b2df5ec604c98b', 786432),
                    ('512efe99e24c0fb03fa3e9b6cabbffb026957e4765e06b2adfc53a0417f38d93', 786432),
                    ('5a0e190abcce53761a4c5421ca9066705d1e470c4ba72e310ed505a9cfc24c75', 786432),
                    ('fcb8144efeb77d92f67ba193ef4960c6fc3587a43396224d1fb5f5126794e631', 786432),
                    ('2c3af4f9fe7135e49617a0a35d57b7398768d829df4ed8b369ba53d9776b5aba', 786432),
                    ('e1df650b16ec3abf818322ea0807b2b0d429459198007a8211a2c428c895d6d0', 710976))),
 't2-ice.mp3': ('f61918b8199e91bb094fdddcb34d36f376b2a7c6cde8f47f067933aab4e40f93',
                (('ebb4e38460985bd9f11d38aaab3719a5e9bbc67c2a552edf965502a237bbe350', 786432),
                 ('c122a091ec267c0a2120bee8436c56c84ee84d083288b17fce7869bbf296e5d4', 786432),
                 ('e93091a82299d78dec64bac8ab36d330b21d058af1da68b9d282b7db50822eb8', 786432),
                 ('8d3548e5ab3d7a67d31e5708f7c8b48259cb3656e7ab781fb8947b95b71d9036', 786432),
                 ('dacf9a530e4cc7838e6b36adc37a613bc6d0e957093180f6f2fd4c4d2fd6f1c1', 786432),
                 ('b60aad324bd0edc057930ca205d3f09872a6888ddd5da58cbe3586151c0e6458', 786432),
                 ('13b50f54bb25e6bcc17d3bd8d55568dc73d4330c25f6aac9fdae8fb943f131d6', 786432),
                 ('324fa91057d2e14a56d03585108ca4b7165b1d0ae84bff5fc9a16a68a8a4e9b0', 710976))),
 't2-lush.mp3': ('79cf5078032b5369fc1a8228796c8d11a2137d93bd4228ff0f9379e5c91eeb1f',
                 (('fc3e4071aca11f85a976ef8df1c8361c65a52afbb60e1046dc92019fa7059fb9', 786432),
                  ('05fbdee5794e04d8bee7d84c6c1b4efa36dc90fe23ba986d20ce7aff906b2d52', 786432),
                  ('d6989c228249a51146b95aad3a8092082133784119276bdc86672b9720a58f22', 786432),
                  ('cf7d7964f117bf0810434b13f14377911ce41a285738fc96d2a127c64f8dadb7', 786432),
                  ('f21d1b6248483d45d5579147f5da5439c14e24354861b044d57bce1d6d66cf44', 786432),
                  ('b904c40a3005cd6a0d1f63546fed2d621fc1c587d436e48ff63a3912f2830e06', 786432),
                  ('0aff15139ccb3a6b8b34aea6c098ef3a148a8c2b7289f32713246902d85e23ed', 786432),
                  ('fe5e8d11473b80ad6516c6361535c6fec9e4bb20c79a09e3d0c05dc1793290b2', 662976))),
 't2-volcano.mp3': ('19589d34a9a7ec49701aa0b90b8920c71ac0012b70bc844b5de614c01107b19c',
                    (('06b0aa256290a59a26cfcab2d44aa5582da65928b3f87a78b65a74b3cf93f798', 786432),
                     ('03ef7445b91d6705211d8249803aab160a9b56a527f4a6147c182a4d35455bd4', 786432),
                     ('a4e299f581ce92f5905af9914138d893ce53bdf200a86a990d5091e18aec6ecd', 786432),
                     ('05a8e1ccc95a9a539b82a3479ca65cbb9ec0be8793d3f1bae96f68e402ca1847', 786432),
                     ('431edd265c2c2e9cbcea0c94e318d6bc61af90edbe3833b85b8ef01ac53e9b8a', 786432),
                     ('cc997dab62f90d92425e819255d6dce2c5fcb09d57b84bca41fa4b9f500aa5dd', 786432),
                     ('97b436689777e071fb054772ae27acd3df9e384d19277a5f7256a8f6970ad467', 786432),
                     ('bc4fe53efed3298bd38d0bf9f182c2dc7adf7368590f56fd95d8d28793880a8c', 734976)))}
T1_TRACKS = tuple(f't1-{number:02}.mp3' for number in range(1, 11))
T2_BIOMES = ('badlands', 'desert', 'ice', 'lush', 'volcano')
TRACKS = (*T1_TRACKS, *(f't2-{biome}.mp3' for biome in T2_BIOMES), 'rollercoaster.mp3')

def playlists():
    routes = {Path(track).stem.replace('-', '_'): (track,) for track in TRACKS}
    for first in range(1, len(T1_TRACKS) + 1):
        routes[f'playlist_t1_{first}'] = T1_TRACKS[first - 1:] + T1_TRACKS[:first - 1]
    return routes


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
