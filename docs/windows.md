# Windows setup: from checkout to the first decision

## 1. Get the project and choose folders

Download [gpt64 from main](https://github.com/esotericode/gpt64/archive/refs/heads/main.zip).
Extract it, then rename/move the folder containing `START-HERE.md`, `pyproject.toml`,
and the `gpt64` subfolder to `C:\gpt64\project`. If you use Git:

```powershell
git clone https://github.com/esotericode/gpt64.git C:\gpt64\project
```

Use this layout. These are recommended locations; the ROM and emulator can live
elsewhere because you open them directly in BizHawk.

| Folder / file | What goes there | Who creates it |
| --- | --- | --- |
| `C:\gpt64\project\` | Extracted gpt64 source, docs and launchers | You |
| `C:\gpt64\emulator\BizHawk-2.11.1\EmuHawk.exe` | Extracted BizHawk and its bundled files | You |
| `C:\gpt64\roms\Super Mario 64.z64` | Your self-dumped ROM (`.n64`/`.v64` also work if BizHawk accepts them) | You |
| `C:\gpt64\saves\` | Optional manual BizHawk save states | You, via BizHawk |
| `C:\gpt64\project\.venv\` | Private Python environment | Setup launcher |
| `C:\gpt64\project\.gpt64\bridge\start.lua` | Generated Lua launcher to open in BizHawk | `init` |
| `C:\gpt64\project\.gpt64\runs\` | Screenshots, commentary, events, usage, state | App |
| `%LOCALAPPDATA%\gpt64\accounts.dat` | ChatGPT credentials, encrypted for your Windows user | Sign-in |

Keep the entire BizHawk release together; do not copy only `EmuHawk.exe`.
The app never searches for your ROM or uploads it. Avoid a shared/synced folder
for credentials and active mailboxes. Keep the project path fixed after `init`,
or regenerate its Lua launcher after moving it.

Open PowerShell in `C:\gpt64\project` (File Explorer address bar: type
`powershell` and press Enter). All commands below run from that folder.
Keep PowerShell and BizHawk open during a real run.

## 2. Install the local prerequisites

- Install [Python 3.11 or later](https://www.python.org/downloads/windows/),
  including its Windows launcher. Run `py --version` to verify it.
- Download [BizHawk 2.11.1](https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1).
  Install the prerequisites linked on that release and extract BizHawk to a
  normal local folder. Run `EmuHawk.exe`.
- Have your self-dumped Mario 64 ROM locally. Keep it outside the project folder.
  You do not need to upload it or an API key to this chat.

Run **setup-windows.cmd** once. It creates `.venv` and installs the application
with the maintained JWT/cryptography libraries used to verify ChatGPT sign-in.
Equivalent PowerShell commands:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[signin]"
```

No npm build is needed. Setup installs software; it sends no model request and
does not add a payment method. Keep the setup window's error text if it fails.

Run **demo.cmd**, or:

```powershell
.\.venv\Scripts\python.exe -m gpt64 serve --demo
```

Open `http://127.0.0.1:8765` in your browser. Choose One decision or Start run.
The scene and commentary are synthetic and use no model allowance or credits.
Press Ctrl+C to close the demo before starting the real server.

## 3. Connect BizHawk

```powershell
.\.venv\Scripts\python.exe -m gpt64 init
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
.\.venv\Scripts\python.exe -m gpt64 doctor
.\.venv\Scripts\python.exe -m gpt64 smoke
```

Doctor captures a screenshot; open its printed PNG and compare it to the game.
Smoke requests 30 neutral frames and verifies exact frame advancement and
frozen idle time. It does not verify gameplay inputs visually. From a harmless
playable area, these commands help verify movement, jump release, and the camera:

```powershell
.\.venv\Scripts\python.exe -m gpt64 step --y 0.6 --frames 12
.\.venv\Scripts\python.exe -m gpt64 sequence examples\jump.json
.\.venv\Scripts\python.exe -m gpt64 step --button "C Left" --frames 2
.\.venv\Scripts\python.exe -m gpt64 observe
```

Positive x is stick right and positive y is stick up. These are camera-relative
controller directions. The jump example is a press/release sequence, not a
calibrated skill. Real results depend on terrain, camera, and momentum.

## 4. Use your ChatGPT Plus plan first

The default path is **Continue with ChatGPT**, using OpenAI's documented flow
for local apps. Eligible Plus/Pro accounts can grant ChatGPT plan usage for
eligible requests. You do not need to obtain an API key for this path.
GPT-6.1 SOL availability is checked against the selected account's live model
catalog. Sign-in alone does not guarantee that a request is admitted.

Run **start.cmd**, open `http://127.0.0.1:8765`, then:

1. Choose **Continue with ChatGPT** in the ChatGPT plan panel.
2. Your system browser opens the official `auth.openai.com` sign-in page.
3. Sign into the account that has your Plus plan. Review/register the app named
   gpt64 and grant permission to use your ChatGPT plan. You never type your
   password or copy an access token into gpt64.
4. Return to the dashboard. Verify the account label and **PLAN ENABLED**.
5. Use **Manage ChatGPT usage**. In ChatGPT Settings > Usage, review gpt64's
   access and limit its use of credits to what you allow before starting.
6. Begin with **One decision** and a decision limit of 10.

Plus use is limited: the documented five-hour allowance is shared across apps
using your ChatGPT plan. This is not unlimited unattended game time. Eligible
requests may use included allowance or available credits according to your
ChatGPT settings. The app does not buy credits or upgrade your subscription.
It never changes to paid API billing or another model automatically.

If sign-in/plan permission/model access is unavailable, the app stops and shows
an error. You can keep using the free demo and Observe while resolving access.
Do not assume you must upgrade to Pro or add API funds; those are separate choices.

For terminal sign-in and a read-only model check:

```powershell
.\.venv\Scripts\python.exe -m gpt64 login
.\.venv\Scripts\python.exe -m gpt64 api-check
```

These do not submit an inference request. To re-enable declined plan permission,
choose Continue with ChatGPT or run `login --enable-plan`. To add another
account/workspace use Add account or `login --new`. Select saved accounts in the
picker, or run `accounts` and then `account <saved-client-id>`. Identical emails
can have separate registrations; their distinct labels include a client suffix.
Sign out stops use of local tokens and attempts remote session revocation.
You can also disconnect gpt64 in ChatGPT Settings.

Credentials stay outside the project under `%LOCALAPPDATA%\gpt64`, encrypted
using Windows DPAPI. They are not included in run exports. Refresh is serialized
and tokens rotate together. Never send `accounts.dat` to a support chat.
Close other gpt64 servers before changing accounts from the terminal.

Official references: [Plus/Pro local-app sign-in](https://developers.openai.com/siwc/quickstart),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[shared Plus allowance](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
and [preview limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

### Optional: separately billed API key

Choose this only if you want ordinary API billing. Your ChatGPT sign-in does
not create/fund an API Platform project for this app. A project API key authorizes
requests billed under that project's API settings. An existing Plus subscription
is not a key to paste into the application.

1. Sign in to [OpenAI Platform](https://platform.openai.com/) using your account.
2. Select/create a project for gpt64. Review API billing/credit and set a small
   spend limit. Review any automatic recharge setting before enabling it.
3. Open [API keys](https://platform.openai.com/api-keys), choose **Create new
   secret key**, name it gpt64, and select the project. Give it the endpoint
   permissions needed for model metadata, Responses, and input-token counting.
4. Copy the newly displayed secret into your local password manager. A key is
   a password for your application. Do not send it to me, put it in git, or type
   it into the dashboard. If exposed, revoke it and create another.
5. In the PowerShell window that will launch the server, use this hidden prompt:

```powershell
$gpt64ApiKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $gpt64ApiKey).Password
Remove-Variable gpt64ApiKey
.\.venv\Scripts\python.exe -m gpt64 api-check --billing api
.\.venv\Scripts\python.exe -m gpt64 serve --billing api
```

Metadata access is checked without generation. Successful metadata access does
not prove funded inference; the first One decision tests the other endpoints.
Use the initial $0.25 per-run estimate and 10-decision limit. Funding and account
eligibility cannot be verified by this chat. The key expires from this shell's
environment when you close it. It is sent only to `https://api.openai.com`.

[Official API-key setup](https://developers.openai.com/api/docs/quickstart)
and [exact GPT-6.1 SOL model](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

## 5. Start the dashboard

With the ROM loaded and the Lua bridge enabled, use start.cmd or:

```powershell
.\.venv\Scripts\python.exe -m gpt64 serve
```

Open `http://127.0.0.1:8765`. The server listens only on your computer's loopback
interface. Keep PowerShell and BizHawk running.

1. Choose **Observe** to verify that the latest game screenshot appears.
2. Enter a small goal, such as `Enter Bob-omb Battlefield through its painting.`
3. Keep the first decision limit at 10. In explicit API mode, keep the initial
   $0.25 budget estimate. Those limits apply per run.
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
.\.venv\Scripts\python.exe -m gpt64 serve --reasoning high
```

## 6. Monitor and troubleshoot

The Usage panel shows returned input/output/cache/reasoning tokens, latency and
decision counts. In **ChatGPT plan** mode it links to ChatGPT Settings > Usage;
it does not translate your Plus allowance or credit use into API-price dollars.
Remaining allowance/account credits are not inferred from token totals.

In explicit **API** mode it shows dollar estimates at dated 2026-10-04 standard
rates. It counts input tokens and reserves the highest standard input rate plus
the 4,096-token output cap before each generation. Reasoning is already included
in output and is not charged twice. Prices, regional premiums and unknown
outcomes can affect charges; reconcile at [API usage](https://platform.openai.com/usage).
Neither the local budget nor a provider spend setting is a guarantee that an
in-flight request cannot consume usage. Unknown outcomes stop with a visible
warning, and generation requests are never automatically retried.

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
| ChatGPT sign-in dependency missing | Run setup-windows.cmd or install `.[signin]` in `.venv`. |
| ChatGPT plan use not granted | Choose Continue with ChatGPT and grant plan usage. |
| ChatGPT allowance/credit limit | Open ChatGPT Settings > Usage; wait or change limits deliberately. |
| ChatGPT model unavailable / 403 | Verify selected account, region, eligibility and GPT-6.1 SOL availability. No model/billing fallback. |
| API 401, in explicit API mode | Re-enter the API key in this PowerShell window. |
| API 403 or 404 | Verify project permissions and exact `gpt-6.1-sol` availability. |
| API 429 | Check credit, rate limits, and project limits. No retry is automatic. |
| Incomplete response | Output cap may include reasoning; inspect usage, then deliberately start another run. |
| Budget reached | The next request's maximum estimate did not fit; choose a new run/budget deliberately. |
| Port in use | Stop the old server or use `.\.venv\Scripts\python.exe -m gpt64 serve --port 8766`. |
| Unconfirmed emulator action/client lock | Follow the recovery procedure below. |

For an unconfirmed emulator action, stop the bridge script in Lua Console first:

```powershell
.\.venv\Scripts\python.exe -m gpt64 init --reset
```

Reload the printed launcher and observe the current game state. Reset retains
logs/screenshots and does not rewind Mario. The unconfirmed action may already
have moved him. Save/load a repeatable starting state manually in BizHawk when
calibrating; no save-state control is exposed to the agent yet.

For unreadable saved credentials, stop all gpt64 servers, disconnect the app in
ChatGPT Settings, then move `%LOCALAPPDATA%\gpt64\accounts.dat` to a private
backup and sign in again. This starts a new local registration; do not share the
backup. Normal sign-out keeps the host/client mapping for later reauthorization.

## 7. What the model is told

See [the agent contract](agent.md). To print the exact current instructions:

```powershell
.\.venv\Scripts\python.exe -m gpt64 instructions
```

Every turn supplies those instructions, your goal, recent screenshots, confirmed
controller history and compact visual notes. The model proposes data; local
Python/Lua validation controls execution. It never opens your ROM, reads game
RAM, sees account credentials or controls the emulator through a web browser.
