"""Guide Linux players through the one-time Steam launch configuration."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Running with isolated Python leaves the script directory off sys.path.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from linux_launcher import setup_option

TITLE = 'Clan Wars for Linux'
TEXT = (
    '1. In Steam, open TRIBES 3: Rivals > Properties > Compatibility, '
    'and select a Proton version. Start with Proton 10.0-4 if available.\n'
    '2. Under General > Launch Options, replace the contents with the line below.\n'
    '3. Click Play in Steam. If the Starter does not open, reopen this installer '
    'and choose Launch diagnostics.'
)


def data_directory():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    if not base.is_absolute():
        raise ValueError('XDG_DATA_HOME must be an absolute directory.')
    return base/'Tribes3CommunityStarter'


def launch_option(root):
    return '/bin/sh ' + setup_option(root)


def diagnostics(data):
    logs = [data/'launcher-start.log']
    folders = data/'linux-launches'
    if folders.is_dir():
        sessions = [item for item in folders.iterdir()
                    if item.is_dir() and (item/'proton-preflight.log').is_file()]
        if sessions:
            recent = max(sessions, key=lambda item:(item/'proton-preflight.log').stat().st_mtime)
            logs.extend(recent/name for name in ('proton-preflight.log','linux-launcher.log','bridge.log'))
    report = []
    for path in logs:
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-4096))
            tail = stream.read(4096).decode('utf-8',errors='replace').strip()
        if tail:
            report.append(path.name+'\n'+tail)
    return '\n\n'.join(report) or 'No launch output yet. Check the Steam launch option, then click Play and retry.'


def choose(dialog):
    if dialog == 'kdialog':
        args = ['--menu','Choose an action','setup','Steam setup','logs','Launch diagnostics']
    else:
        args = ['--list','--column=Action','Steam setup','Launch diagnostics']
    result = subprocess.run([dialog,*args,'--title='+TITLE],capture_output=True,text=True,check=False)
    return {'setup':'setup','Steam setup':'setup','logs':'logs','Launch diagnostics':'logs'}.get(result.stdout.strip())


def show_builtin_window(option, data):
    # Some Linux desktops ship neither KDE's nor GNOME's dialog utility.
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return
    try:
        window = tk.Tk()
    except tk.TclError:
        return
    window.title(TITLE)
    body = ttk.Frame(window, padding=18)
    body.grid(sticky='nsew')
    window.columnconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)
    instructions = ttk.Label(body, text=TEXT, wraplength=650, justify='left')
    instructions.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0,12))
    value = ttk.Entry(body, width=92)
    value.insert(0, option)
    value.state(['readonly'])
    value.grid(row=1, column=0, columnspan=2, sticky='ew')
    report = tk.Text(body, width=82, height=12, wrap='word')

    def copy():
        window.clipboard_clear()
        window.clipboard_append(option)
        value.selection_range(0, 'end')

    def show_logs():
        report.config(state='normal')
        report.delete('1.0','end')
        report.insert('1.0','Review these details before sharing them.\n\n'+diagnostics(data))
        report.config(state='disabled')
        report.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(12,0))

    ttk.Button(body, text='Copy launch option', command=copy).grid(row=2, column=0, sticky='w', pady=(12,0))
    ttk.Button(body, text='Launch diagnostics', command=show_logs).grid(row=2, column=1, sticky='e', pady=(12,0))
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    request = parser.add_mutually_exclusive_group()
    request.add_argument('--print-launch-option',action='store_true')
    request.add_argument('--diagnostics',action='store_true')
    args = parser.parse_args()
    data = data_directory()
    if args.diagnostics:
        print(diagnostics(data))
        return 0
    for name in ('python/pythonw.exe','linux_bootstrap.pyw','package-manifest.json'):
        if not (ROOT/name).is_file():
            raise ValueError('Extract the complete Clan Wars ZIP before running this installer.')
    data.mkdir(parents=True,exist_ok=True)
    option = launch_option(ROOT)
    if args.print_launch_option:
        print(option)
        return 0
    print(TEXT+'\n\n'+option,flush=True)
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return 0
    dialog = next((name for name in ('kdialog','zenity') if shutil.which(name)),None)
    if not dialog:
        show_builtin_window(option, data)
        return 0
    action = choose(dialog)
    if action == 'setup':
        prompt = TEXT+'\n\nSelect the entire line below and copy it into Steam.'
        if dialog == 'kdialog':
            command = [dialog,'--inputbox',prompt,option,'--title',TITLE]
        else:
            command = [dialog,'--entry','--text='+prompt,'--entry-text='+option,'--title='+TITLE,'--width=760']
        subprocess.run(command,stdout=subprocess.DEVNULL,check=False)
    elif action == 'logs':
        prompt = 'Review these details before sharing them.\n\n'+diagnostics(data)
        if dialog == 'kdialog':
            subprocess.run([dialog,'--textbox','/dev/stdin','840','490','--title',TITLE],
                           input=prompt,text=True,check=False)
        else:
            subprocess.run([dialog,'--text-info','--width=840','--height=490','--title='+TITLE],
                           input=prompt,text=True,check=False)
    return 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(TITLE+' - '+str(exc),file=sys.stderr)
        sys.exit(1)
