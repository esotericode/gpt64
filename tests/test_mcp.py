import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from gpt64.bridge import atomic_json
from gpt64.claude import launch
from gpt64.mcp_server import DashboardClient
from gpt64.paths import Settings
from gpt64.runner import Controller
from gpt64.server import make_server
from test_agent import FakeBridge, answer, PNG


class MCPTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = FakeBridge(self.root)
        self.factory = Mock(side_effect=AssertionError('No model credentials or inference in MCP mode'))
        self.controller = Controller(self.root / 'bridge', self.root / 'runs', billing='claude',
            settings=Settings(self.root), bridge_factory=lambda: self.bridge, client_factory=self.factory)
        self.server = make_server(self.controller, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.descriptor = self.root / 'dashboard.json'
        atomic_json(self.descriptor, {'url': f'http://127.0.0.1:{self.server.server_port}', 'token': self.server.control_token})
        self.client = DashboardClient(self.descriptor)

    def tearDown(self):
        self.controller.close(); self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.tmp.cleanup()

    def until(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.01)
        self.fail('Worker did not reach expected state')

    def arm(self, limit=2, continuous=False):
        self.controller.start('Reach painting', max_steps=limit, continuous=continuous)
        self.until(lambda: self.controller.snapshot()['status'] == 'waiting_external')

    def observation(self):
        result = self.client.call('observe', {})
        self.assertEqual(base64.b64decode(result['content'][1]['data']), PNG)
        return json.loads(result['content'][0]['text'])

    def test_official_client_tools_observe_act_and_one_decision_pauses(self):
        self.arm()
        obs = self.observation()
        self.assertNotIn('frame_before', obs)
        value = {**answer(), 'observation_id': obs['observation_id']}
        self.client.call('act', value)
        self.until(lambda: self.controller.snapshot()['status'] == 'paused' and self.controller.snapshot()['steps'] == 1)
        self.assertEqual(len(self.bridge.actions), 1)
        self.factory.assert_not_called()
        self.assertFalse(self.controller.snapshot()['usage_available'])
        with self.assertRaisesRegex(RuntimeError, 'Stale screenshot'):
            self.client.call('act', value)
        self.assertEqual(len(self.bridge.actions), 1)
        records = ''.join(p.read_text() for p in self.controller.log.directory.rglob('*.json*'))
        self.assertIn('action_finished', records)
        self.assertIn('The path looks clear', records)

    def test_pause_holds_queued_decision_and_resume_never_resubmits(self):
        self.arm(continuous=True)
        obs = self.observation()
        self.controller.pause()
        self.until(lambda: self.controller.snapshot()['status'] == 'paused')
        self.client.call('act', {**answer(), 'observation_id': obs['observation_id']})
        self.assertTrue(self.controller.snapshot()['pending_decision'])
        self.assertEqual(self.bridge.actions, [])
        with self.assertRaisesRegex(RuntimeError, 'already pending'):
            self.client.call('act', {**answer(), 'observation_id': obs['observation_id']})
        self.controller.start('Reach painting', continuous=False)
        self.until(lambda: self.controller.snapshot()['status'] == 'paused' and self.controller.snapshot()['steps'] == 1)
        self.assertEqual(len(self.bridge.actions), 1)

    def test_stop_and_limit_prevent_further_actions(self):
        self.arm(limit=1)
        obs = self.observation()
        self.client.call('act', {**answer(), 'observation_id': obs['observation_id']})
        self.until(lambda: self.controller.snapshot()['status'] == 'limit_reached')
        newer = self.observation()
        with self.assertRaises(RuntimeError):
            self.client.call('act', {**answer(), 'observation_id': newer['observation_id']})
        self.assertEqual(len(self.bridge.actions), 1)
        self.factory.assert_not_called()

    def test_stop_discards_a_queued_decision_without_moving_game(self):
        self.arm()
        obs = self.observation()
        self.controller.pause()
        self.until(lambda: self.controller.snapshot()['status'] == 'paused')
        self.client.call('act', {**answer(), 'observation_id': obs['observation_id']})
        self.controller.stop()
        self.until(lambda: self.controller.snapshot()['status'] == 'stopped')
        self.assertEqual(self.bridge.actions, [])
        with self.assertRaises(RuntimeError):
            self.client.call('act', {**answer(), 'observation_id': obs['observation_id']})

    def test_invalid_action_and_goal_completion_advance_no_frames(self):
        self.arm()
        obs = self.observation(); bad = answer(); bad['segments'][0]['frames'] = 999
        with self.assertRaises(RuntimeError):
            self.client.call('act', {**bad, 'observation_id': obs['observation_id']})
        self.client.call('act', {**answer(done=True), 'observation_id': obs['observation_id']})
        self.until(lambda: self.controller.snapshot()['status'] == 'completed')
        self.assertEqual(self.bridge.actions, [])

    def test_stdio_protocol_returns_only_json_and_images_without_credentials(self):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'observe', 'arguments': {}}}]
        self.arm()
        result = subprocess.run([sys.executable, '-m', 'gpt64', '--data', str(self.root), 'mcp'],
            input=''.join(json.dumps(m)+'\n' for m in messages), capture_output=True, text=True, timeout=5, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2, 3])
        self.assertEqual(replies[1]['result']['tools'][1]['name'], 'act')
        self.assertEqual(replies[2]['result']['content'][1]['mimeType'], 'image/png')
        self.assertNotIn(self.server.control_token, result.stdout)
        self.assertEqual(result.stderr, '')

    def test_descriptor_rejects_remote_or_redirected_control_destination(self):
        atomic_json(self.descriptor, {'url': 'https://remote.invalid', 'token': self.server.control_token})
        with self.assertRaisesRegex(RuntimeError, 'local connection'):
            self.client.call('observe', {})

    def test_launcher_uses_native_authentication_and_only_game_tools(self):
        with patch('gpt64.claude.shutil.which', return_value='/fake/claude'), patch('gpt64.claude.subprocess.Popen') as spawn:
            launch(self.root)
        command = spawn.call_args.args[0]
        self.assertIn('--strict-mcp-config', command)
        self.assertEqual(command[command.index('--tools')+1], '')
        self.assertNotIn('-p', command)
        self.assertNotIn('--bare', command)
        config = json.loads((self.root / 'claude-mcp.json').read_text())
        self.assertNotIn('token', json.dumps(config))
        self.assertEqual(config['mcpServers']['gpt64']['command'], sys.executable)
