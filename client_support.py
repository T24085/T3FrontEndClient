import csv,hashlib,io,json,os,re,shutil,subprocess,time,uuid
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
REL=Path('Topaz/Binaries/Win64')
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def engine_command_line(arguments):
    """Match UE 5.3's BuildFromArgV format after Windows parses the transport."""
    result = []
    for arg in arguments:
        if ' ' in arg and '"' not in arg:
            equals = arg.find('=')
            if equals > 0 and arg.find(' ') > equals:
                arg = arg[:equals + 1] + '"' + arg[equals + 1:] + '"'
            else:
                arg = '"' + arg + '"'
        result.append(arg)
    return ' '.join(result)


def save(path, value):
    temp = path.with_suffix('.tmp-' + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)

def relative(value):
    p = PurePosixPath(value.replace('\\', '/'))
    if p.is_absolute() or '..' in p.parts or ':' in str(p):
        raise ValueError('Unsafe inventory path: ' + value)
    return Path(*p.parts)

from verified_file_cache import verify_package as verify_package_files


def verify_package():
    return verify_package_files(ROOT)

def discover_game(explicit):
    if explicit:
        candidates = [Path(explicit).expanduser()]
    else:
        import winreg
        steam_roots = []
        for hive, key, name in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    steam_roots.append(Path(winreg.QueryValueEx(k, name)[0]))
            except OSError:
                pass
        libraries = list(steam_roots)
        for root in steam_roots:
            f = root / 'steamapps/libraryfolders.vdf'
            if f.is_file():
                for value in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', f.read_text(encoding='utf-8')):
                    libraries.append(Path(value.replace('\\\\', '\\')))
        candidates = []
        for library in libraries:
            manifest = library / 'steamapps/appmanifest_2687970.acf'
            if manifest.is_file():
                match = re.search(r'"installdir"\s+"([^"/\\]+)"', manifest.read_text(encoding='utf-8'))
                if match:
                    candidates.append(library / 'steamapps/common' / match[1])
    found = list(dict.fromkeys(p.resolve() for p in candidates if (p / REL / 'TribesRivals.exe').is_file()))
    if len(found) != 1:
        raise RuntimeError('Choose your original game folder with --game-dir "X:\\SteamLibrary\\steamapps\\common\\TRIBES 3 Rivals". Found: ' + str(found))
    return found[0]

def file_identity(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]

def verify_game(source, workspace, force=False):
    manifest = json.loads((ROOT / 'base-game-manifest.json').read_text())
    cache = workspace / 'verified-source.json'
    key = digest(ROOT / 'base-game-manifest.json')
    identities = {x['path']: file_identity(source / relative(x['path'])) for x in manifest['files']}
    old = {}
    if cache.is_file() and not force:
        try:
            old = json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
    reused = (old.get('source') == str(source) and old.get('manifest') == key
              and old.get('identities') == identities and 0 <= time.time() - old.get('verified_at', 0) < 86400)
    if not reused:
        print('Verifying original game files (9.2 GB). The first check may take several minutes.', flush=True)
        for n, item in enumerate(manifest['files']):
            path = source / relative(item['path'])
            if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
                raise RuntimeError('Unsupported or changed game file: ' + item['path'])
            if file_identity(path) != identities[item['path']]:
                raise RuntimeError('Source changed while hashing: ' + item['path'])
            if n % 25 == 0:
                print(f'Verified {n + 1}/{len(manifest["files"])}', flush=True)
        save(cache, dict(source=str(source), manifest=key, identities=identities, verified_at=time.time()))
    if digest(source / REL / 'TribesRivals.exe') != manifest['executable_sha256']:
        raise RuntimeError('Game executable version differs from this playtest.')
    return manifest, identities, 'retained hashes with 24-hour file-identity/size/time guards' if reused else 'fresh SHA256'

def running_image(name):
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ' + name, '/FO', 'CSV', '/NH'], capture_output=True, text=True, check=True)
    return any(row and row[0].lower() == name.lower() for row in csv.reader(io.StringIO(result.stdout)))
