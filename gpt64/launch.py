"""Host startup: remember file picks, load Lua automatically, and open the UI."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import webbrowser

from .bridge import Bridge, BridgeError
from .cli import initialize
from .paths import Settings


def choose_file(title, types):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        root.attributes('-topmost', True)
        try:
            value = filedialog.askopenfilename(title=title, filetypes=types)
        finally:
            root.destroy()
    except Exception:
        raise ValueError('File picker unavailable. Run configure --emulator PATH --rom PATH from a terminal.') from None
    if not value:
        raise ValueError('No file selected. Run start.cmd again when ready.')
    return str(Path(value).resolve())


def migrate_logs(legacy, directory):
    """Copy old run records once; never copy/replay emulator mailboxes."""
    source = Path(legacy) / 'runs'
    target = Path(directory) / 'runs'
    if source.is_dir() and source.resolve() != target.resolve():
        target.mkdir(parents=True, exist_ok=True)
        for run in source.iterdir():
            if run.is_dir() and len(run.name) == 32 and all(c in '0123456789abcdef' for c in run.name) and not (target / run.name).exists():
                shutil.copytree(run, target / run.name)


def emulator_command(emulator, rom, launcher):
    exe, game = Path(emulator).resolve(), Path(rom).resolve()
    if not exe.is_file() or exe.name.lower() != 'emuhawk.exe':
        raise ValueError('Select BizHawk EmuHawk.exe, keeping its bundled files together')
    if not game.is_file() or game.suffix.lower() not in ('.z64', '.n64', '.v64'):
        raise ValueError('Select your locally dumped Mario 64 .z64, .n64 or .v64 ROM')
    return [str(exe), '--lua=' + str(Path(launcher).resolve()), str(game)]


def prepare_emulator(settings, bridge_root, timeout=30):
    bridge_root = Path(bridge_root)
    # A pending action is never erased or replayed by startup.
    if (bridge_root / 'pending.json').exists() or (bridge_root / 'client.lock').exists():
        raise BridgeError('Unconfirmed work/client lock exists. Stop Lua, run init --reset, then start again. Logs are retained.')
    if (bridge_root / 'ready.json').exists():
        with Bridge(bridge_root, timeout=2) as bridge:
            bridge.observe()  # A screenshot proves the old bridge is alive; advances zero frames.
        return None
    value = settings.load()
    if not Path(value['emulator']).is_file():
        value = settings.save({'emulator': choose_file('Select BizHawk EmuHawk.exe (first start only)', [('BizHawk', 'EmuHawk.exe')])})
    if not Path(value['rom']).is_file():
        value = settings.save({'rom': choose_file('Select your Mario 64 ROM (first start only)', [('N64 ROM', '*.z64 *.n64 *.v64')])})
    if os.name == 'nt':
        running = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq EmuHawk.exe', '/FO', 'CSV', '/NH'], capture_output=True, text=True, check=True)
        if 'emuhawk.exe' in running.stdout.lower():
            raise BridgeError('BizHawk is already open without a live gpt64 bridge. Close it once, then run start.cmd to load everything automatically.')
    launcher = initialize(bridge_root, reset=(bridge_root / 'start.lua').exists())
    command = emulator_command(value['emulator'], value['rom'], launcher)
    child = subprocess.Popen(command, cwd=Path(value['emulator']).parent)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise BridgeError('BizHawk exited during startup. Check its prerequisites and ROM.')
        if (bridge_root / 'ready.json').exists():
            with Bridge(bridge_root, timeout=3) as bridge:
                bridge.observe()
            return child
        time.sleep(.1)
    raise BridgeError('BizHawk did not report a ready Lua bridge. Check its window/Lua Console. It has been left open; no model request was sent.')


def launch(directory, bridge_root, demo=False, billing='chatgpt', legacy=None):
    from .server import serve
    directory = Path(directory)
    if legacy:
        migrate_logs(legacy, directory)
    settings = Settings(directory)
    if not demo:
        prepare_emulator(settings, bridge_root)
    serve(bridge_root, directory / 'runs', demo=demo, billing=billing, settings=settings, open_browser=True)
