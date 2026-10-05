# gpt64

A vision-only Mario 64 agent and local observer dashboard for BizHawk on Windows.

The agent defaults to **GPT-6.1 SOL (`gpt-6.1-sol`)** through the OpenAI Responses API.
You can explicitly choose another model from your account's live catalog.
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
extract it to `C:\gpt64\project`, and open [START-HERE.md](START-HERE.md).
Install Python 3.11+, then run **setup-windows.cmd** once. Run **demo.cmd** to
inspect the dashboard free of model usage, or **start.cmd** after connecting
BizHawk. No npm build is required.

Equivalent demo command, after setup:

```powershell
.\.venv\Scripts\python.exe -m gpt64 serve --demo
```

Open `http://127.0.0.1:8765`. Demo mode is a clearly labelled synthetic scene
with scripted decisions and no emulator, ROM, model allowance or credits.

## Run with Mario 64

Follow the complete [Windows setup guide](docs/windows.md). You need:

1. Python 3.11+ and BizHawk 2.11.1 with its prerequisites.
2. Your locally supplied Mario 64 ROM.
3. An eligible ChatGPT account that grants plan usage and offers a compatible vision model,
   or an explicitly configured, separately billed OpenAI API project.

**The default is Continue with ChatGPT.** Eligible Plus/Pro users can authorize
local apps to use their plan or available credits. Account/model eligibility
and shared allowance limits still apply. The dashboard provides an account
picker, sign-in/sign-out, plan-use confirmation and a Manage usage link.
It never switches to paid API billing or another model automatically.

See [official local-app sign-in](https://developers.openai.com/siwc/quickstart).
The complete guide includes exact folders, prerequisites, hidden local key
entry for the optional API path, and troubleshooting. Credentials remain
outside the checkout; Windows encrypts saved OAuth credentials with DPAPI.

```powershell
.\.venv\Scripts\python.exe -m gpt64 init
# Load your ROM, pause BizHawk, then open the printed start.lua in Lua Console.
.\.venv\Scripts\python.exe -m gpt64 doctor
.\.venv\Scripts\python.exe -m gpt64 smoke
.\.venv\Scripts\python.exe -m gpt64 login
.\.venv\Scripts\python.exe -m gpt64 models
# If your catalog lists this model:
.\.venv\Scripts\python.exe -m gpt64 api-check --model gpt-6-sol
.\.venv\Scripts\python.exe -m gpt64 serve
```

Or use start.cmd and Continue with ChatGPT in the dashboard. Enter a goal and
choose an **Agent model** in Run controls, then begin with **One decision**.
Try `gpt-6-sol` first if listed, then `gpt-6-luna`. Neither requires switching to
paid API billing. Catalog presence does not prove inference admission.
Reasoning defaults to medium (`serve --reasoning high` also works).
See [what the agent is told on every turn](docs/agent.md).

`serve --model MODEL_ID` sets the initial selection. GPT-6.1 Sol, GPT-6 Sol,
GPT-6 Luna and GPT-6 Astra have configured vision/reasoning/pricing profiles.
Other listed IDs can be selected experimentally in ChatGPT plan mode, with
provider default reasoning; unsupported image/structured-output requests stop
before game inputs. Paid API mode allows only the four priced profiles.
Stop an existing run before switching models. The selected and returned model
IDs are saved with the run; a dated snapshot of the selected alias is accepted.

Upgrading from 0.3.0: follow [the upgrade steps](docs/windows.md#upgrading-an-existing-installation).
Preserve `.gpt64` and `.venv`, replace the source files, and rerun setup.

The API-key path is an explicit `--billing api` choice for both `api-check`
and `serve`. Set `OPENAI_API_KEY` locally as described in the guide.

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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

CI runs on Windows and Linux. Linux requires Lua 5.4 and executes the actual Lua
bridge against a simulated BizHawk host. Authentication tests verify signed JWT claims, callback state/PKCE, refresh and
protected credential storage. Agent tests mock OpenAI responses and
verify pause/stop behavior, rejected actions, usage, budgets, and durable logs.
HTTP tests exercise the dashboard demo, saved screenshots, and ZIP export.
These tests do not replace real emulator/API validation.

ROMs, emulator binaries, save states, logs, and credentials are excluded from git.
