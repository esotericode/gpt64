# Windows setup and everyday startup

## 1. Install the prerequisites once

- Install [Python 3.11+](https://www.python.org/downloads/windows/), including its
  Windows launcher. Reopen your terminal and verify `py --version`.
- Download [BizHawk 2.11.1](https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1),
  install the prerequisites linked on that release, and extract the whole
  release. Keep its DLLs and other bundled files beside `EmuHawk.exe`.
- Keep your self-dumped Mario 64 ROM locally. The launcher accepts `.z64`,
  `.n64` and `.v64`; BizHawk still needs to support its contents.

Recommended locations:

| Location | Contents |
| --- | --- |
| `C:\gpt64\project\` | Replaceable gpt64 source, docs and launchers |
| `C:\gpt64\emulator\BizHawk-2.11.1\` | Complete BizHawk release |
| `C:\gpt64\roms\Super Mario 64.z64` | Your local ROM |
| `C:\gpt64\saves\` | Optional manually managed save states |
| `%LOCALAPPDATA%\gpt64\runtime\` | Reusable Python environment, installed app/dependencies |
| `%LOCALAPPDATA%\gpt64\data\settings.json` | Remembered emulator/ROM paths, model, goal and run limits |
| `%LOCALAPPDATA%\gpt64\data\bridge\` | Lua launcher, mailbox and low-level screenshots |
| `%LOCALAPPDATA%\gpt64\data\runs\` | Durable run logs, screenshots, commentary and usage |
| `%LOCALAPPDATA%\gpt64\accounts.dat` | ChatGPT credentials encrypted for your Windows user |

The source folder can be replaced or moved after the first upgrade. Runtime and
local data stay put. ROMs and emulator binaries should remain outside the source
folder. Settings contain local paths and goals; never put a key in them.

## 2. Double-click a launcher

Download [main as a ZIP](https://github.com/esotericode/gpt64/archive/refs/heads/main.zip)
and extract all project files together. The folder with `start.cmd` should also
contain `scripts`, `gpt64`, `pyproject.toml` and the docs.

- **start.cmd**: ChatGPT plan mode.
- **start-claude.cmd**: official Claude Code with local MCP game tools.
- **demo.cmd**: synthetic scene and scripted commentary; no emulator/account usage.
- **setup-windows.cmd**: install/update the runtime without opening the game.

Each launcher provisions the persistent Python environment if needed and installs
an updated package only when its source fingerprint changes. You do not need to
rerun setup manually after an update. Downloads/install steps send no inference
requests and do not add a payment method.

On the first real start, file pickers ask for `EmuHawk.exe` and your ROM.
These choices are remembered. Startup opens BizHawk with the ROM and
`--lua=<generated launcher>`, confirms a screenshot advancing zero frames, and
opens `http://127.0.0.1:8765`. It does not call a model or replay old inputs.
Close an already-open BizHawk without a working bridge before that first start.

On later starts, the launcher reuses a live bridge, or opens BizHawk and Lua
again. If the same dashboard is already running, it opens that dashboard rather
than starting a second server. Stop it before switching provider modes.

A frozen emulator between decisions is expected. Game speed depends on model
latency and action bursts; this is a paused, turn-taking player, not a video feed.

## 3. ChatGPT sign-in and model selection

Choose **Continue with ChatGPT**. Your browser opens the official OpenAI sign-in
page. Sign into the account with your plan and grant gpt64 plan usage. Passwords
and bearer tokens are never entered into the dashboard. Verify **PLAN ENABLED**.
Saved sign-in is retained across source replacements, subject to reauthorization.

Review app access/credit limits in **ChatGPT Settings > Usage**. Eligible requests
may use plan allowance or available credits. Plus's documented five-hour allowance
is shared across participating apps. The app does not buy credits or upgrade your
subscription, and does not switch to separately billed API requests automatically.

Choose **Refresh models** and select any ID returned by your account's catalog.
GPT-6.1 Sol is the initial preference; try GPT-6 Sol or Luna if they appear.
Configured GPT-6 profiles set reasoning effort; other listed models use provider
default reasoning. All still need image input and structured JSON support.
Catalog presence alone does not prove inference admission. The first
**One decision** verifies actual access; incompatible responses stop before inputs.
The model choice, goal and run limits are remembered locally. Stop a run before
switching models; a paused run retains its pending decision and selected model.

Enter a goal, set a small decision limit such as 10, and choose One decision.
Inspect the screenshot, commentary and controls. Use Start/Resume run to allow
further decisions, Pause to hold the next input, and Stop to end the run. A model
request already in flight may still consume usage. No failed request is retried.

Official references: [local-app sign-in](https://developers.openai.com/siwc/quickstart),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[shared allowance](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions).

For Claude Pro instead, follow [the Claude guide](claude.md). Sign-in and all
available model choices stay inside official Claude Code. The dashboard retains
its screenshot/commentary/controls/logs; Claude usage is checked in the native app.

## 4. Manual commands when useful

The normal launchers perform setup, ROM loading, Lua loading and a zero-frame
connection check automatically. You do not need these commands every session.
For terminal diagnostics, open PowerShell in the project folder and define:

```powershell
$gpt64Python = "$env:LOCALAPPDATA\gpt64\runtime\Scripts\python.exe"
& $gpt64Python -m gpt64 --help
& $gpt64Python -m gpt64 models
& $gpt64Python -m gpt64 api-check --model gpt-6-sol
& $gpt64Python -m gpt64 doctor
& $gpt64Python -m gpt64 instructions
```

`models` and `api-check` read metadata only; `doctor` captures a paused screenshot.
To change paths without the graphical picker:

```powershell
& $gpt64Python -m gpt64 configure --emulator "C:\gpt64\emulator\BizHawk-2.11.1\EmuHawk.exe" --rom "C:\gpt64\roms\Super Mario 64.z64"
```

For initial calibration, `smoke` verifies a 30-frame neutral action and frozen
idle. It advances the emulator deliberately; it is not an everyday startup step.
Manual controller commands also advance the game:

```powershell
& $gpt64Python -m gpt64 smoke
& $gpt64Python -m gpt64 step --y 0.6 --frames 12
& $gpt64Python -m gpt64 sequence examples\jump.json
& $gpt64Python -m gpt64 observe
```

Stick right/up are positive x/y, relative to the camera. A distinct jump needs
press/release segments. The example is illustrative, not a calibrated skill.

Direct `serve` starts just the dashboard; `launch` also prepares the emulator:

```powershell
& $gpt64Python -m gpt64 launch
& $gpt64Python -m gpt64 serve --model gpt-6-sol --reasoning high --port 8766
```

For a custom data location, set `GPT64_DATA_DIR` before running a launcher or use
`gpt64 --data PATH ...`. `--bridge PATH` overrides its mailbox. Keep it local,
not in a shared/synced directory. `GPT64_RUNTIME_DIR` overrides the runtime path;
these optional settings must be used consistently. On Unix, data defaults to
`$XDG_DATA_HOME/gpt64` or `~/.local/share/gpt64`, and runtime is its `runtime` folder.

## 5. Optional, separately billed OpenAI API key

This path is an explicit choice; it does not charge a ChatGPT subscription.
The app permits only the four configured GPT-6 API pricing profiles so its
budget reserve has known rates. Other catalog-listed models remain selectable
in ChatGPT plan mode.

1. Sign into [OpenAI Platform](https://platform.openai.com/) and select/create a project.
2. Review API billing/credits, a small spend limit and automatic recharge settings.
3. Open [API keys](https://platform.openai.com/api-keys) and create a project secret
   key named gpt64. Allow model metadata, Responses and input-token counting.
4. Save the key in your local password manager. Do not send it to chat, commit
   it, enter it in settings.json, or paste it into the dashboard.
5. In the PowerShell window that starts gpt64, use a hidden prompt:

```powershell
$gpt64ApiKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $gpt64ApiKey).Password
Remove-Variable gpt64ApiKey
$gpt64Python = "$env:LOCALAPPDATA\gpt64\runtime\Scripts\python.exe"
& $gpt64Python -m gpt64 api-check --billing api --model gpt-6-sol
& $gpt64Python -m gpt64 launch --billing api
```

The key is read from the process environment and sent only to the official API.
The app does not save it. Close the shell to clear that environment. Metadata
access is not proof of funded inference; begin with One decision. Use a small
per-run budget such as $0.25 and reconcile estimates with official API usage.
Reasoning is included in output counts; it is not charged twice in estimates.

## 6. Logs, stopping and recovery

Every run saves `events.jsonl`, `state.json`, `screens/*.png` and response usage/IDs
where available. Saved runs and Download run ZIP work for both providers. Exports
exclude credentials, ROMs and private reasoning; goals and screenshots are included.
Review those before sharing a troubleshooting bundle.

Ctrl+C stops the dashboard after bounded/in-flight work. BizHawk is left open
and paused so you can manage saves. Close it normally before replacing project
files. In Claude mode, press Esc in Claude separately to interrupt its inference.

| Symptom | Next step |
| --- | --- |
| Python launcher missing | Install Python 3.11+ with its launcher; reopen the terminal. |
| Older dashboard running during update | Stop its server and close BizHawk, then rerun start.cmd. |
| BizHawk already open without a live bridge | Close it once; start.cmd will load ROM and Lua automatically. |
| Lua bridge startup times out | Inspect BizHawk/Lua Console and prerequisites; it is left open and no inference was sent. |
| File picker unavailable | Use `configure --emulator PATH --rom PATH`. |
| ChatGPT model not listed | Refresh models and select a returned ID; no API fallback. |
| Unrecognized catalog response | Refresh or reauthorize; this is not proof of a missing subscription model. |
| ChatGPT 403/plan admission denied | Check account, region and granted plan permission. Catalog presence is insufficient. |
| ChatGPT allowance/credit limit | Check ChatGPT Settings > Usage; wait or change limits deliberately. |
| Model response was not a valid structured decision (0.4.0 or earlier) | Upgrade to 0.4.1; it fixes commentary being joined to the final JSON. Test One decision with the same model. |
| No final answer with completed status/empty output (0.4.1 or earlier) | Upgrade to 0.4.2, which retains finalized streamed messages. If it still fails, share the new run ZIP; it includes stream event counts. |
| Empty/invalid/multiple final answer or rejected decision | Download that run ZIP and share the model ID and connection mode. Its `api/*.json` records include the public answer, message phases and specific parse error; no input is executed for that turn. |
| Claude Code missing | Install its official native Windows app; reopen start-claude.cmd. |
| Claude MCP tool reports no active run | Arm One decision/Start in the dashboard, then ask Claude to continue. |
| Claude paused/limit reached | Stop tool calls; use the dashboard to deliberately resume/start another run. |
| Stale screenshot or decision already pending | Never replay it; Observe and inspect the dashboard. |
| API 401/403/404/429 | Check the locally entered key, permissions, chosen model and API credit/rate limits. |
| Port occupied | Stop the old dashboard or use `serve --port 8766`. |
| Pending action/client lock | Follow the reset procedure below; startup never silently clears it. |
| Lua bridge timing limits are outdated | Close BizHawk and rerun the launcher so it loads the updated Lua script; no request was sent. |

For an interrupted bridge or unconfirmed action, stop its Lua script (or close
BizHawk) first. Then, with the runtime command from section 4:

```powershell
& $gpt64Python -m gpt64 init --reset
```

Now run start.cmd. Reset retains logs/screenshots and does not rewind Mario;
the earlier action may already have moved him. If an unrelated BizHawk window
remains open, close it before automatic relaunch. Manual saves/checkpoints are
managed through BizHawk; no game RAM or save-state API is exposed to the model.

For unreadable ChatGPT credentials, stop all servers, disconnect gpt64 in
ChatGPT settings, privately back up `%LOCALAPPDATA%\gpt64\accounts.dat`, and sign
in again. Never share that backup. Normal sign-out retains the registration.

## Upgrading an existing installation

For 0.5.0, stop the dashboard, close BizHawk and also close Claude Code if used.
Replace the source folder and run the same launcher. Reopen Claude Code from the
dashboard to load its new scratchpad tools. No new sign-in is required. New AI
notes are stored in `%LOCALAPPDATA%\gpt64\data\scratchpad\notes.jsonl` and are
kept across later replacements. AI timing & memory shows durations, notes and
search/paging. Start run continues automatically; One decision stops after a turn.

**From 0.3.x, once:** stop the old server and close BizHawk. Copy all new source
files into the existing project folder. Leave the old `.gpt64` folder present
for this first launch if you want old run logs copied. Run start.cmd. It creates
the external runtime and copies old UUID-named run records into the external
data folder, leaving originals intact. It does not migrate pending actions or
mailboxes. Check Saved runs before discarding the old project. ChatGPT credentials
already live outside it and are retained.

**After that:** stop the server and close BizHawk, replace the entire source
folder with the new version, and double-click start.cmd. It installs the changed
package automatically. Settings, runtime and logs are unaffected. ROM/emulator
paths are remembered; if you moved those files, the picker asks again. No source
file-by-file preservation or manual Lua regeneration is required.
