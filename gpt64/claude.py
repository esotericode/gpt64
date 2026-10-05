"""Open the unmodified interactive Claude app; never access its credentials."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from .bridge import atomic_json
from .mcp_server import MCP_INSTRUCTIONS


def prepare(directory):
    directory = Path(directory).resolve()
    config = directory / 'claude-mcp.json'
    prompt = directory / 'claude-instructions.txt'
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(config, {'mcpServers': {'gpt64': {'type': 'stdio', 'command': sys.executable,
        'args': ['-m', 'gpt64', '--data', str(directory), 'mcp', '--dashboard-file', str(directory / 'dashboard.json')]}}})
    prompt.write_text(MCP_INSTRUCTIONS, encoding='utf-8')
    return config, prompt


def launch(directory):
    executable = shutil.which('claude.exe' if os.name == 'nt' else 'claude')
    if not executable:
        raise ValueError('Install official Claude Code first: winget install Anthropic.ClaudeCode. Reopen the launcher afterward. See docs/claude.md.')
    config, prompt = prepare(directory)
    command = [executable, '--strict-mcp-config', '--mcp-config', str(config), '--tools', '',
               '--append-system-prompt-file', str(prompt)]
    # Authentication options and limits remain entirely in Anthropic's native app.
    options = {'creationflags': subprocess.CREATE_NEW_CONSOLE} if os.name == 'nt' else {}
    return subprocess.Popen(command, cwd=Path(directory), **options)
