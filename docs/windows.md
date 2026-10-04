# Windows setup: from checkout to the first decision

## 1. Get the project

The implementation is currently on the `codex/vision-harness` branch in
[esotericode/gpt64](https://github.com/esotericode/gpt64/tree/codex/vision-harness).
Download that branch using GitHub's **Code > Download ZIP**, extract it, and
open the extracted project folder. If you use Git:

```powershell
git clone --branch codex/vision-harness https://github.com/esotericode/gpt64.git
cd gpt64
```

The folder must contain `README.md`, `pyproject.toml`, and a `gpt64` subfolder.
Open PowerShell in this folder. All commands below run from that folder.
Keep this PowerShell window open when starting the app.

## 2. Install the local prerequisites

- Install [Python 3.11 or later](https://www.python.org/downloads/windows/),
  including its Windows launcher. Run `py --version` to verify it.
- Download [BizHawk 2.11.1](https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1).
  Install the prerequisites linked on that release and extract BizHawk to a
  normal local folder. Run `EmuHawk.exe`.
- Have your self-dumped Mario 64 ROM locally. Keep it outside the project folder.
  You do not need to upload it or an API key to this chat.

The application itself uses the Python standard library, so there is no
`pip install` step or npm build. You can preview it now:

```powershell
py -m gpt64 serve --demo
```

Open `http://127.0.0.1:8765` in your browser. Choose One decision or Start run.
The scene and commentary are synthetic, clearly labelled, and free of API calls.
Press Ctrl+C in PowerShell to close demo mode before starting the real server.

## 3. Connect BizHawk

```powershell
py -m gpt64 init
```

This prints an absolute path to `start.lua`.

1. In BizHawk, use File > Open ROM to load your Mario 64 ROM.
2. Verify the game normally renders. Pause the emulator.
3. Open Tools > Lua Console and open the `start.lua` path printed by init.
4. Leave this script enabled and the Lua Console open. Look for
   `gpt64 bridge ready` in the console.
5. Make sure player 1 is connected. Avoid physical controller input, movies,
   autoholds, rewind, and other Lua scripts while this harness owns the game.

Begin with an ordinary working N64 configuration. Mupen64Plus is the intended
first core when available. The script checks the controller names used by the
active core instead of silently assuming a mapping. Record core/renderer and
ROM region/hash if comparing runs.

In the same project PowerShell window:

```powershell
py -m gpt64 doctor
py -m gpt64 smoke
```

Doctor captures a screenshot; open its printed PNG and compare it to the game.
Smoke requests 30 neutral frames and verifies exact frame advancement and
frozen idle time. It does not verify gameplay inputs visually. From a harmless
playable area, these commands help verify movement, jump release, and the camera:

```powershell
py -m gpt64 step --y 0.6 --frames 12
py -m gpt64 sequence examples\jump.json
py -m gpt64 step --button "C Left" --frames 2
py -m gpt64 observe
```

Positive x is stick right and positive y is stick up. These are camera-relative
controller directions. The jump example is a press/release sequence, not a
calibrated skill. Real results depend on terrain, camera, and momentum.

## 4. Set up OpenAI API access

gpt64 calls the OpenAI API directly. It does not control a ChatGPT webpage and
does not use your current ChatGPT session as authentication. Configure API
billing/credit for your OpenAI Platform project and check model permissions.

1. Sign in to [OpenAI Platform](https://platform.openai.com/).
2. Select or create a project for this experiment.
3. Configure API billing/credit and the project permissions you need.
4. Create a project API key in the API keys section. It needs access to model
   metadata, Responses, and the input-token counting endpoint.
5. Keep the key on your PC. Do not paste it into chat, the dashboard, or git.

Set it for the current PowerShell window with a hidden prompt:

```powershell
$gpt64ApiKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $gpt64ApiKey).Password
Remove-Variable gpt64ApiKey
py -m gpt64 api-check
```

API check sends a read-only model metadata request for `gpt-6.1-sol`, with no
generation. Successful metadata access does not guarantee funded inference;
the first decision also checks the token-counting and generation endpoints.
An unavailable model stops with an error. No replacement model is selected.

This environment variable is inherited by the app launched from this window.
Closing the window clears this session's setting; repeat the prompt next time.
The key stays in the local Python process and is sent only in the Authorization
header to `https://api.openai.com`. It is not delivered to the browser or logs.

Official references: [API key quickstart](https://developers.openai.com/api/docs/quickstart),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[image input](https://developers.openai.com/api/docs/guides/images-vision),
and [input token counting](https://developers.openai.com/api/docs/guides/token-counting).

## 5. Start the dashboard

With the ROM loaded, the Lua bridge enabled, and the API key set:

```powershell
py -m gpt64 serve
```

Open `http://127.0.0.1:8765`. The server listens only on your computer's loopback
interface. Keep PowerShell and BizHawk running.

1. Choose **Observe** to verify that the latest game screenshot appears.
2. Enter a small goal, such as `Enter Bob-omb Battlefield through its painting.`
3. Leave the first budget estimate at $1 and choose a small decision limit
   such as 10. These are per-run limits; a new run gets a new budget.
4. Choose **One decision**. Watch the commentary, selected inputs, usage, and
   resulting screenshot. The game pauses after the action.
5. Choose **One decision** again for another turn, or **Resume run** to continue
   autonomously until you pause/stop or a limit/completion/error is reached.

The screenshot updates at action boundaries, not continuously during a burst.
**Pause** holds the next action. If a model request is in flight, its usage is
recorded and its decision is held for later; resume does not call the model again
for that pending decision. **Stop** discards a pending decision once in-flight
work returns. A controller burst already in progress finishes before pausing.
An API request already submitted may still incur usage after pause or stop.

Reasoning defaults to medium. To choose a supported setting:

```powershell
py -m gpt64 serve --reasoning high
```

## 6. Monitor and troubleshoot

The Usage panel shows API-returned token counts, cached/cache-write input,
reasoning tokens (already included in output), latency, and estimated dollar
cost. Prices are dated 2026-10-04. The app requests the standard service tier,
counts inputs before each generation, and reserves the highest standard input
rate plus the output cap when checking the remaining budget.

Dollar estimates are not an authoritative bill or account balance. Regional
premiums, price changes, other apps, and failed requests with unknown outcomes
can affect charges. Check [OpenAI API usage](https://platform.openai.com/usage)
for your account. An unknown generation outcome leaves a visible reservation
and stops the run; no automatic retry is sent.

Use Saved runs to inspect earlier sessions. Download run ZIP exports the event
log, usage/IDs, state, and screenshots. No ROM, credentials, or private model
reasoning is included. Review the goals and screenshots before sharing a bundle.

| Symptom | Next step |
| --- | --- |
| `py` is not found | Install Python's launcher, reopen PowerShell, check `py --version`. |
| Bridge not ready | Load the ROM, pause, load the printed launcher, check Lua Console. |
| Missing controller names | Record BizHawk version/core and `joypad.get(1)` output in Lua Console. |
| Blank screenshots | Verify normal ROM rendering and inspect the Lua Console. |
| Smoke reports extra frames | Stop other input/scripts/movies and resolve timing before agent play. |
| API 401 | Re-enter the API key in this PowerShell window. |
| API 403 or 404 | Verify project permissions and exact `gpt-6.1-sol` availability. |
| API 429 | Check credit, rate limits, and project limits. No retry is automatic. |
| Incomplete response | Output cap may include reasoning; inspect usage, then deliberately start another run. |
| Budget reached | The next request's maximum estimate did not fit; choose a new run/budget deliberately. |
| Port in use | Stop the old server or use `py -m gpt64 serve --port 8766`. |
| Unconfirmed emulator action/client lock | Follow the recovery procedure below. |

For an unconfirmed emulator action, stop the bridge script in Lua Console first:

```powershell
py -m gpt64 init --reset
```

Reload the printed launcher and observe the current game state. Reset retains
logs/screenshots and does not rewind Mario. The unconfirmed action may already
have moved him. Save/load a repeatable starting state manually in BizHawk when
calibrating; no save-state control is exposed to the agent yet.
