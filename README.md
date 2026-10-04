# gpt64

A vision-only Mario 64 agent and local observer dashboard for BizHawk on Windows.

The agent uses **GPT-6.1 SOL (`gpt-6.1-sol`)** through the OpenAI Responses API.
It sees screenshots and its own executed inputs, selects a bounded input burst,
and gives a public explanation of one or two sentences. BizHawk advances the
requested frames and pauses while the next decision is made. No game RAM is read.

**Status:** implementation and automated tests are in place. Live OpenAI access
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

Each run saves ongoing JSONL events, screenshots, API IDs/usage, and its last
state. Commentary is a short public action summary; private reasoning content,
API keys, request headers, and image base64 are excluded from the records.

## Try the dashboard without setup

With Python 3.11+, from this repository:

```powershell
py -m gpt64 serve --demo
```

Open `http://127.0.0.1:8765`. Demo mode shows a clearly labelled synthetic scene
and scripted decisions; it uses no emulator, ROM, model, or API credits.

## Run with Mario 64

Follow the complete [Windows setup guide](docs/windows.md). You need:

1. Python 3.11+ and BizHawk 2.11.1 with its prerequisites.
2. Your locally supplied Mario 64 ROM.
3. An OpenAI Platform project API key with GPT-6.1 SOL access and API billing.

There is no ChatGPT sign-in inside gpt64. The local Python server reads
`OPENAI_API_KEY`; the browser never receives it. No Python packages need to be
installed when running from this checkout.

```powershell
py -m gpt64 init
# Load your ROM, pause BizHawk, then load the printed start.lua in Lua Console.
py -m gpt64 doctor
py -m gpt64 smoke
# Set OPENAI_API_KEY locally as described in the setup guide.
py -m gpt64 api-check
py -m gpt64 serve
```

Open the dashboard, enter a goal, and begin with **One decision**. The model is
fixed to `gpt-6.1-sol`; unavailable access stops with an error instead of silently
selecting another model. Reasoning defaults to medium and is configurable:

```powershell
py -m gpt64 serve --reasoning high
```

## Timing and cost

The screen updates after observations/actions; this is a screenshot-based
turn-taking player, not a continuous video stream. Each segment is 1–120 emulator
frames; each sequence has at most 16 segments and 240 frames. These are emulator
ticks, not guaranteed distinct game renderings. Short actions help with camera
movement, momentum, and landing corrections.

Before each generation, the app counts input tokens and reserves a conservative
standard-price estimate for the input and the 4,096-token output cap. A run
stops before a request that exceeds its remaining estimated budget. Output usage
includes reasoning tokens; they are displayed separately without charging twice.

Rates are dated 2026-10-04. Dollar totals are estimates for this app's recorded
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

Default locations:

| Location | Contents |
| --- | --- |
| `.gpt64/bridge/` | Lua launcher, mailbox state, low-level screenshots/actions |
| `.gpt64/runs/<run-id>/events.jsonl` | Ongoing timestamped decisions, inputs, observations, usage, errors |
| `.gpt64/runs/<run-id>/screens/` | Screenshots used in that run |
| `.gpt64/runs/<run-id>/api/` | API response/request IDs, status, usage, latency |
| `.gpt64/runs/<run-id>/state.json` | Last dashboard state and dated pricing |

Use **Saved runs** to inspect old sessions and **Download run ZIP** for a
troubleshooting bundle. Records persist locally until you remove them. They
contain your goals and screenshots. No API key or ROM is included.

See [architecture](docs/architecture.md) for the protocol, model boundary,
budget accounting, and recovery behavior.

## Development

```powershell
py -m unittest discover -s tests -v
```

CI runs on Windows and Linux. Linux requires Lua 5.4 and executes the actual Lua
bridge against a simulated BizHawk host. Agent tests mock OpenAI responses and
verify pause/stop behavior, rejected actions, usage, budgets, and durable logs.
HTTP tests exercise the dashboard demo, saved screenshots, and ZIP export.
These tests do not replace real emulator/API validation.

ROMs, emulator binaries, save states, logs, and credentials are excluded from git.
