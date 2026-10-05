# gpt64

A vision-only Mario 64 agent and local observer dashboard for BizHawk on Windows.

The ChatGPT agent defaults to **GPT-6.1 SOL (`gpt-6.1-sol`)** through the OpenAI Responses API.
You can explicitly choose any model from your account's live catalog, subject to screenshot/JSON compatibility.
Claude Pro is supported through the official Claude Code app and local MCP game tools; its sign-in and model picker stay in that app.
It sees screenshots and its own executed inputs, selects a bounded input burst,
and gives a public explanation of one or two sentences. BizHawk advances the
requested frames and pauses while the next decision is made. No game RAM is read.

**Status:** implementation and automated tests are in place. Account-specific ChatGPT sign-in/inference, live API access
and real BizHawk/Mario 64 gameplay still need validation on the game host.
Successful autonomous gameplay has not yet been demonstrated.

## What you can see

- Latest game screenshot, brief agent commentary, analog position, button chords,
  frame durations, and the decision/execution timeline.
- Connecting, observing, counting tokens, thinking, acting, paused, stopping,
  completion, limits, and actionable error states.
- Returned input/output/cached/cache-write/reasoning token counts, estimated cost,
  request latency, pending request reservation, and decision/action totals.
- Start, One decision, Pause, Stop, Observe, saved run inspection, and ZIP export.
- Account-specific model picker and read-only catalog refresh.

Each run saves ongoing JSONL events, screenshots, API IDs/usage, and its last
state. Commentary is a short public action summary; private reasoning content,
API keys, request headers, and image base64 are excluded from the records.

## Download and start

Download [main as a ZIP](https://github.com/esotericode/gpt64/archive/refs/heads/main.zip),
extract all files together, and read [START-HERE.md](START-HERE.md).
Install Python 3.11+ and BizHawk 2.11.1 with its prerequisites once. Keep the
emulator and your locally dumped ROM outside the source folder.

Double-click **start.cmd** for ChatGPT, **start-claude.cmd** for Claude, or
**demo.cmd** for the free synthetic scene. Startup installs/updates its reusable
Python environment, remembers your emulator/ROM file picks, starts BizHawk with
Lua, verifies a paused screenshot, and opens the browser. Later starts reuse a
live bridge. No model request is sent until you deliberately start model work.

The runtime, settings, logs and credentials live outside the source folder.
After the first upgrade from 0.3.x, you can replace the whole project folder,
then double-click its launcher. No manual setup/Lua regeneration is needed.
Old `.gpt64/runs` logs are copied on the first upgrade if that folder is present;
see [upgrade details](docs/windows.md#upgrading-an-existing-installation).

## Choose an account and model

**ChatGPT:** Continue with ChatGPT, grant plan use, review app limits in ChatGPT
settings, then Refresh models and select any account-listed ID. The preference
is remembered. GPT-6 Sol and Luna are configured options if offered; unknown
profiles use provider default reasoning. Image/structured-output rejection stops
before inputs. Catalog presence is not proof of inference admission, so begin
with One decision. No automatic model or paid API fallback occurs.

**Claude Pro:** install the official native Claude Code app, run start-claude.cmd,
and choose Open Claude Code in the dashboard. Sign in through the native app
and use `/model` for whatever models it offers. Arm One decision in the dashboard
and ask Claude to use gpt64 toward its displayed goal. Screenshots, commentary,
inputs, limits and logs work through the local game tools. Check `/usage` in
Claude; token counts, actual model ID and cost are unavailable to this dashboard.
See [the Claude guide](docs/claude.md).

The Claude app remains unmodified, handles its own authentication and inference,
and connects only the game's MCP tools in the supplied launch configuration.
gpt64 never reads or intermediates its subscription credentials. The connection
is tested with simulated clients; real account inference/gameplay needs validation.

**Optional API billing:** explicitly use `--billing api` with your locally entered
OpenAI API key. Only configured API pricing profiles are permitted; budget
accounting uses the selected model's rates. See [the Windows guide](docs/windows.md)
for exact local key entry, setup, folders, diagnostics and recovery.

For terminal use after setup:

```powershell
$gpt64Python = "$env:LOCALAPPDATA\gpt64\runtime\Scripts\python.exe"
& $gpt64Python -m gpt64 models
& $gpt64Python -m gpt64 launch
& $gpt64Python -m gpt64 serve --model gpt-6-sol --reasoning high
```

Stop a run before changing models. Resume preserves a pending decision without
asking the model again. See [the agent instructions](docs/agent.md).

## Timing and cost

The screen updates after observations/actions; this is a screenshot-based
turn-taking player, not a continuous video stream. Each segment is 1–120 emulator
frames; each sequence has at most 16 segments and 240 frames. These are emulator
ticks, not guaranteed distinct game renderings. Short actions help with camera
movement, momentum, and landing corrections.

In explicit API mode, before each generation the app counts input tokens and reserves a conservative
standard-price estimate for the input and the 4,096-token output cap. A run
stops before a request that exceeds its remaining estimated budget. Output usage
includes reasoning tokens; they are displayed separately without charging twice.

In ChatGPT plan mode, the app records tokens without applying API dollar rates.
Review remaining allowance, app access and credit limits in ChatGPT Settings >
Usage. Plus's five-hour allowance is shared across participating apps.
Plan requests stream to a terminal response; an interrupted stream cannot
execute a partial action. The preview route does not accept an output-token
cap, so use the 10-decision initial limit and your ChatGPT app limits.

API rates are dated 2026-10-05. Dollar totals are estimates for this app's recorded
calls, not your account balance or authoritative invoice. Regional premiums,
price changes, other applications, and unknown request outcomes may change the
actual bill. Use [OpenAI API usage](https://platform.openai.com/usage) to reconcile
charges. Limits apply per run; starting another run creates a fresh budget.

Pause holds the next action, including one selected by an in-flight response.
Resume uses that pending decision without another generation request. Stop
discards the pending decision once in-flight work finishes. Neither operation
can undo API usage or a controller burst already in progress. No failed API or
emulator action is retried automatically.

## Logs and troubleshooting

Default Windows locations (under `%LOCALAPPDATA%/gpt64/data`):

| Location | Contents |
| --- | --- |
| `bridge/` | Lua launcher, mailbox state, low-level screenshots/actions |
| `runs/<run-id>/events.jsonl` | Ongoing timestamped decisions, inputs, observations, usage, errors |
| `runs/<run-id>/screens/` | Screenshots used in that run |
| `runs/<run-id>/api/` | API response/request IDs, status, usage, latency, answer diagnostics |
| `runs/<run-id>/state.json` | Last dashboard state and dated pricing |

Use **Saved runs** to inspect old sessions and **Download run ZIP** for a
troubleshooting bundle. Records persist locally until you remove them. They
contain your goals, screenshots, and public final answers (up to 16,384 characters
per response). No API key, ROM, or private reasoning is included.

**“Model response was not a valid structured decision” in 0.4.0 or earlier:** the
parser could accidentally join an intermediate commentary message to the final
JSON answer. Version 0.4.1 fixes that reproducible bug by selecting one final
answer and ignoring other explicit message phases. The old generic error also
covered empty or invalid JSON; old records do not contain the rejected answer,
so they cannot establish which cause occurred on your machine.

After upgrading, use **One decision** with the same selected model. If it stops,
download that run ZIP and share it along with the model ID and connection mode.
`api/0001.json` (or the failing turn's number) now includes `diagnostics` with
message types/phases, the public answer, returned format, and a specific
`parse_error` code/message. Missing answers, malformed JSON, refusals, ambiguous
answers and rejected inputs stay stopped. Usage is recorded when returned;
there is no automatic repair request, retry, model switch, or paid fallback.

**“Model returned no final answer” with a completed request:** version 0.4.2
retains finalized public `response.output_item.done` messages when the terminal
stream envelope has an empty or missing output list. Earlier versions discarded
those events. It still waits for the terminal response and usage, preserves
message phases/refusals, and never executes a partial text delta. The export now
includes stream event counts, the terminal output count, and whether the answer
came from the envelope or completed message events. If no finalized answer
arrived anywhere in the stream, the run stays stopped; share the new run ZIP.

See [architecture](docs/architecture.md) for the protocol, model boundary,
budget accounting, and recovery behavior.

## Development

```powershell
& "$env:LOCALAPPDATA\gpt64\runtime\Scripts\python.exe" -m unittest discover -s tests -v
```

CI runs on Windows and Linux. Linux requires Lua 5.4 and executes the actual Lua
bridge against a simulated BizHawk host. Authentication tests verify signed JWT claims, callback state/PKCE, refresh and
protected credential storage. Agent tests mock OpenAI responses and
verify pause/stop behavior, rejected actions, usage, budgets, and durable logs.
HTTP/MCP tests exercise real local transport, screenshots, duplicate/stale action rejection, pause/stop and ZIP export. Startup tests cover source changes, persistent settings, log migration and bridge reuse.
These tests do not replace real emulator/API validation.

ROMs, emulator binaries, save states, logs, and credentials are excluded from git. Claude session history is managed by its native app.
