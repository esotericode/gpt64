"""Local screenshot/action MCP tools. Claude authentication stays in its app."""

import json
from pathlib import Path
import sys
import time
from urllib import request, error
from urllib.parse import urlsplit

from .model import INSTRUCTIONS, SCHEMA, NoRedirect

MCP_INSTRUCTIONS = INSTRUCTIONS + '''
For MCP play, call observe to get the goal, screenshot and its observation_id.
Submit the public commentary, memory, done flag and segments to act, together
with that observation_id. The tool queues data; the host alone executes inputs.
Never resubmit an accepted decision, even after a timeout. Call observe for the
next screenshot. If paused, pending, stopped, completed, errored, or at the
limit, stop tool calls and return control to the user. Do not loop on unchanged
screenshots. No game RAM, filesystem, shell or network tools are needed.
The dashboard does not receive your token usage or actual model ID; use /model
and /usage in the official Claude app. Do not invent usage measurements.
'''

ACT_SCHEMA = {**SCHEMA, 'properties': {**SCHEMA['properties'],
    'observation_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'}},
    'required': SCHEMA['required'] + ['observation_id']}
TOOLS = [
    {'name': 'observe', 'description': 'Get the paused screenshot, goal and last confirmed actions. If a queued action is finishing, waits locally up to 10 seconds. Does not advance the emulator.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'act', 'description': 'Queue ONE validated public decision for the current screenshot. Inputs are bounded to 240 frames. Never retry an accepted decision; use observe next. The dashboard must have an armed Claude run.',
     'inputSchema': ACT_SCHEMA, 'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False, 'openWorldHint': False}},
]


class DashboardClient:
    def __init__(self, descriptor):
        self.descriptor = Path(descriptor)
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect)

    def send(self, path, body):
        try:
            descriptor = json.loads(self.descriptor.read_text(encoding='utf-8'))
            parsed = urlsplit(descriptor['url'])
            if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError()
            token = descriptor['token']
            if not isinstance(token, str) or not 20 <= len(token) <= 200:
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('Start the Claude dashboard with start-claude.cmd first; its local connection file is unavailable.') from None
        req = request.Request(descriptor['url'] + path, data=json.dumps(body).encode(), headers={
            'Content-Type': 'application/json', 'X-Gpt64-Control': token})
        try:
            with self.opener.open(req, timeout=15) as reply:
                return json.load(reply)
        except error.HTTPError as exc:
            try:
                message = json.loads(exc.read(8192)).get('error', 'Local game tool was rejected')
            except (ValueError, AttributeError):
                message = 'Local game tool was rejected'
            raise RuntimeError(message) from None
        except (OSError, error.URLError, ValueError):
            raise RuntimeError('Local game tool response was unconfirmed. Never retry act; reconnect and observe the dashboard.') from None

    def call(self, name, arguments):
        if name == 'observe':
            if arguments:
                raise ValueError('observe takes no arguments')
            deadline = time.monotonic() + 10
            while True:
                value = self.send('/api/external/observe', {})
                if not value['pending_decision'] or value['status'] in ('paused', 'stopped', 'error') or time.monotonic() >= deadline:
                    break
                time.sleep(.1)
            image = value.pop('image')
            return {'content': [{'type': 'text', 'text': json.dumps(value)}, image]}
        if name == 'act':
            if set(arguments) != set(ACT_SCHEMA['required']):
                raise ValueError('act requires the decision fields and observation_id')
            value = self.send('/api/external/decision', arguments)
            return {'content': [{'type': 'text', 'text': json.dumps(value)}]}
        raise ValueError('Unknown game tool')


class Protocol:
    def __init__(self, client):
        self.client = client
        self.initialized = False

    def handle(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in message:  # Initialized/cancellation notifications have no response.
            return None
        reply = {'jsonrpc': '2.0', 'id': message['id']}
        method, params = message['method'], message.get('params') or {}
        if not isinstance(params, dict):
            return {**reply, 'error': {'code': -32602, 'message': 'Expected object parameters'}}
        if method == 'initialize':
            self.initialized = True
            requested = params.get('protocolVersion')
            version = requested if requested in ('2024-11-05', '2025-03-26', '2025-06-18') else '2025-06-18'
            result = {'protocolVersion': version, 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'gpt64', 'version': '0.4.0'}, 'instructions': MCP_INSTRUCTIONS}
        elif not self.initialized:
            return {**reply, 'error': {'code': -32000, 'message': 'Initialize first'}}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            try:
                arguments = params.get('arguments') or {}
                if not isinstance(arguments, dict):
                    raise ValueError('Expected tool arguments object')
                result = self.client.call(params.get('name'), arguments)
            except (RuntimeError, ValueError) as exc:
                result = {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
        else:
            return {**reply, 'error': {'code': -32601, 'message': 'Method not supported'}}
        return {**reply, 'result': result}


def serve_stdio(descriptor, source=None, sink=None):
    source, sink = source or sys.stdin, sink or sys.stdout
    protocol = Protocol(DashboardClient(descriptor))
    while True:
        line = source.readline(65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith('\n'):
            return  # Reject oversized/truncated requests before any action.
        try:
            response = protocol.handle(json.loads(line))
        except (ValueError, TypeError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}}
        if response is not None:
            sink.write(json.dumps(response) + '\n'); sink.flush()
