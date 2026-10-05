"""Persistent, non-secret configuration outside the replaceable source folder."""

import json
import math
import os
from pathlib import Path

from .bridge import atomic_json
from .model import MODEL, model_id


def data_root():
    if os.environ.get('GPT64_DATA_DIR'):
        return Path(os.environ['GPT64_DATA_DIR']).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'gpt64' / 'data'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'gpt64'


class Settings:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'settings.json'

    def load(self):
        defaults = {'model': MODEL, 'goal': 'Enter Bob-omb Battlefield through its painting.',
                    'max_steps': 10, 'budget_usd': .25, 'emulator': '', 'rom': ''}
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict):
                    raise ValueError()
                defaults.update(self.validate(value))
            except (OSError, ValueError, TypeError):
                raise ValueError(f'Unreadable settings: {self.path}. Keep a backup and configure again.') from None
        return defaults

    @staticmethod
    def validate(value):
        if set(value) - {'model', 'goal', 'max_steps', 'budget_usd', 'emulator', 'rom'}:
            raise ValueError('Unknown settings field')
        if 'model' in value:
            model_id(value['model'])
        if 'goal' in value and (not isinstance(value['goal'], str) or not 1 <= len(value['goal'].strip()) <= 1500):
            raise ValueError('Goal must be 1–1500 characters')
        if 'max_steps' in value and (type(value['max_steps']) is not int or not 1 <= value['max_steps'] <= 10000):
            raise ValueError('Decision limit must be 1–10000')
        budget = value.get('budget_usd', .25)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or not 0 < budget <= 1000:
            raise ValueError('Invalid budget')
        for key in ('emulator', 'rom'):
            if key in value and (not isinstance(value[key], str) or len(value[key]) > 4096):
                raise ValueError('Invalid local file path')
        return value

    def save(self, changes):
        self.validate(changes)
        value = {**self.load(), **changes}
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_json(self.path, value)
        return value
