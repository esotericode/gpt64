import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from gpt64.bridge import BridgeError
from gpt64.launch import emulator_command, migrate_logs, prepare_emulator
from gpt64.paths import Settings
from gpt64.runner import Controller
from scripts import bootstrap


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_settings_and_model_survive_a_different_project_directory(self):
        settings = Settings(self.root / 'persistent')
        settings.save({'model': 'account-listed-vision-model', 'goal': 'Reach the door', 'max_steps': 4})
        c = Controller(self.root / 'bridge', self.root / 'runs', settings=Settings(settings.directory), demo=True)
        self.assertEqual(c.snapshot()['model'], 'account-listed-vision-model')
        self.assertEqual(c.snapshot()['preferences']['goal'], 'Reach the door')
        self.assertEqual(c.snapshot()['max_steps'], 4)
        with self.assertRaises(ValueError):
            settings.save({'api_key': 'SECRET'})
        self.assertNotIn('SECRET', settings.path.read_text())

    def test_saved_preference_does_not_rewrite_an_old_run_record(self):
        c = Controller(self.root / 'bridge', self.root / 'runs', demo=True)
        c.state['run_id'] = 'old'
        c.state['model'] = 'gpt-6-sol'
        c.save_preferences({'model': 'gpt-6-luna'})
        self.assertEqual(c.snapshot()['model'], 'gpt-6-sol')
        self.assertEqual(c.snapshot()['preferences']['model'], 'gpt-6-luna')

    def test_runtime_skips_install_until_source_fingerprint_changes(self):
        runtime = self.root / 'runtime'
        python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        python.parent.mkdir(parents=True); python.touch()
        (runtime / 'gpt64-package.sha256').write_text('same\n')
        with patch('scripts.bootstrap.subprocess.run') as install:
            self.assertEqual(bootstrap.provision(runtime, 'same'), python)
            install.assert_not_called()
            bootstrap.provision(runtime, 'new')
        self.assertEqual(install.call_count, 1)
        self.assertEqual((runtime / 'gpt64-package.sha256').read_text().strip(), 'new')
        source = self.root / 'project'; (source / 'gpt64').mkdir(parents=True)
        (source / 'pyproject.toml').write_text('version=1')
        code = source / 'gpt64/example.py'; code.write_text('one')
        first = bootstrap.fingerprint(source)
        code.write_text('two')
        self.assertNotEqual(first, bootstrap.fingerprint(source))

    def test_migration_copies_logs_without_replaying_or_deleting_mailboxes(self):
        legacy = self.root / 'legacy'; run = legacy / 'runs' / ('a' * 32)
        run.mkdir(parents=True); (run / 'events.jsonl').write_text('old record')
        (legacy / 'bridge').mkdir(); (legacy / 'bridge/pending.json').write_text('unknown')
        target = self.root / 'data'
        migrate_logs(legacy, target); migrate_logs(legacy, target)
        self.assertEqual((target / 'runs' / run.name / 'events.jsonl').read_text(), 'old record')
        self.assertTrue((legacy / 'bridge/pending.json').exists())
        self.assertFalse((target / 'bridge/pending.json').exists())

    def test_emulator_launch_preserves_spaces_and_passes_rom_last(self):
        emulator = self.root / 'Emulator folder/EmuHawk.exe'; emulator.parent.mkdir(); emulator.touch()
        rom = self.root / 'Mario game.z64'; rom.touch()
        script = self.root / 'bridge folder/start.lua'
        command = emulator_command(emulator, rom, script)
        self.assertEqual(command, [str(emulator.resolve()), '--lua=' + str(script.resolve()), str(rom.resolve())])
        with patch('gpt64.launch.subprocess.Popen') as launch:
            bridge = self.root / 'bridge'; bridge.mkdir(); (bridge / 'pending.json').write_text('{}')
            with self.assertRaises(BridgeError):
                prepare_emulator(Settings(self.root), bridge)
            launch.assert_not_called()

    def test_live_bridge_is_reused_without_relaunching_or_resetting(self):
        bridge = self.root / 'bridge'; bridge.mkdir(); (bridge / 'ready.json').write_text('{}')
        with patch('gpt64.launch.Bridge') as transport, patch('gpt64.launch.subprocess.Popen') as launch:
            self.assertIsNone(prepare_emulator(Settings(self.root), bridge))
            transport.return_value.__enter__.return_value.observe.assert_called_once()
            launch.assert_not_called()

    def test_fresh_launch_loads_lua_and_verifies_zero_frame_capture(self):
        emulator = self.root / 'EmuHawk.exe'; emulator.touch()
        rom = self.root / 'Mario.z64'; rom.touch()
        bridge = self.root / 'bridge'
        settings = Settings(self.root / 'data')
        settings.save({'emulator': str(emulator), 'rom': str(rom)})
        child = Mock(); child.poll.return_value = None
        def opened(*args, **kwargs):
            (bridge / 'ready.json').write_text('{}')
            return child
        with patch('gpt64.launch.subprocess.Popen', side_effect=opened) as spawn, patch('gpt64.launch.Bridge') as transport, patch('gpt64.launch.subprocess.run', return_value=Mock(stdout='')):
            self.assertIs(prepare_emulator(settings, bridge), child)
            self.assertEqual(spawn.call_args.args[0][-1], str(rom.resolve()))
            self.assertTrue(spawn.call_args.args[0][1].startswith('--lua='))
            self.assertTrue((bridge / 'start.lua').exists())
            transport.return_value.__enter__.return_value.observe.assert_called_once()

    def test_startup_lock_blocks_competing_install_and_releases(self):
        path = self.root / 'startup.lock'
        with bootstrap.startup_lock(path):
            with self.assertRaises(RuntimeError):
                with bootstrap.startup_lock(path):
                    pass
        with bootstrap.startup_lock(path):
            pass

    def test_existing_paid_dashboard_cannot_replace_a_requested_demo(self):
        with patch('scripts.bootstrap.locations', return_value=(self.root / 'runtime', self.root)), patch('scripts.bootstrap.active_dashboard', return_value={'url': 'http://127.0.0.1:8765', 'billing_mode': 'api'}), patch('scripts.bootstrap.provision') as install:
            with self.assertRaisesRegex(RuntimeError, 'different provider'):
                bootstrap.main(['--demo'])
            install.assert_not_called()
