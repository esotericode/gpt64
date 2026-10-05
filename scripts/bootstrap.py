"""One launcher: provision a stable runtime only when the package changes."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib import request, error
import venv


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def startup_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('gpt64 is already starting or running. Return to its window; do not launch another copy.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def locations():
    if os.name == 'nt':
        home = Path(os.environ['LOCALAPPDATA']) / 'gpt64'
    else:
        home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'gpt64'
    return (Path(os.environ.get('GPT64_RUNTIME_DIR', str(home / 'runtime'))).resolve(),
            Path(os.environ.get('GPT64_DATA_DIR', str(home / 'data' if os.name == 'nt' else home))).resolve())


def fingerprint(root=ROOT):
    digest = hashlib.sha256()
    paths = [root / 'pyproject.toml'] + sorted(p for p in (root / 'gpt64').rglob('*')
        if p.is_file() and p.suffix in ('.py', '.lua', '.js', '.html', '.css') and '__pycache__' not in p.parts)
    for p in paths:
        digest.update(p.relative_to(root).as_posix().encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def active_dashboard(directory):
    try:
        value = json.loads((directory / 'dashboard.json').read_text())
        url = value['url']
        if not url.startswith('http://127.0.0.1:') or '/' in url[17:]:
            return None
        with request.build_opener(request.ProxyHandler({})).open(url + '/api/state', timeout=1) as r:
            state = json.load(r)
        if state.get('control_token') != value.get('token'):
            return None
        return {'url': url, 'billing_mode': state.get('billing_mode')}
    except (OSError, ValueError, KeyError, error.URLError):
        return None


def provision(runtime, stamp):
    python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    marker = runtime / 'gpt64-package.sha256'
    if not python.is_file():
        print('Creating the reusable Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(runtime)
    if not marker.exists() or marker.read_text().strip() != stamp:
        print('Installing this gpt64 version; your settings and logs are retained...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', str(ROOT) + '[signin]'], check=True, cwd=runtime)
        marker.write_text(stamp + '\n')
    return python


def main(argv=None):
    parser = argparse.ArgumentParser(description='Set up and start gpt64 with persistent local data')
    parser.add_argument('--billing', choices=('chatgpt', 'api', 'claude'), default='chatgpt')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--setup-only', action='store_true')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        raise RuntimeError('Install Python 3.11 or newer with its Windows launcher.')
    runtime, directory = locations()
    stamp = fingerprint()
    active = active_dashboard(directory)
    if active:
        expected = 'demo' if args.demo else args.billing
        if active['billing_mode'] != expected:
            raise RuntimeError('A different provider/dashboard mode is already running. Stop its server before changing modes.')
        marker = runtime / 'gpt64-package.sha256'
        if not marker.exists() or marker.read_text().strip() != stamp:
            raise RuntimeError('An older dashboard is still running. Stop it and close BizHawk before installing this update.')
        import webbrowser
        webbrowser.open(active['url'])
        print('An existing dashboard is open at ' + active['url'] + '.')
        return 0
    with startup_lock(runtime.parent / 'startup.lock'):
        python = provision(runtime, stamp)
        if args.setup_only:
            print('Setup complete. Next time, double-click start.cmd, demo.cmd, or start-claude.cmd.')
            return 0
        command = [str(python), '-m', 'gpt64', '--data', str(directory), 'launch', '--billing', args.billing,
                   '--legacy', str(ROOT / '.gpt64')]
        if args.demo:
            command.append('--demo')
        return subprocess.call(command, cwd=runtime)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print('gpt64 startup: ' + str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        print('gpt64 startup stopped. Close the emulator normally when finished.')
        sys.exit(130)
