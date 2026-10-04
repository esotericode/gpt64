# Architecture and agent boundary

## Why this backend

BizHawk already has Lua controller, screenshot, pause, and frame APIs. We can
use those without writing an N64 emulator, a custom input plugin, or a desktop
keyboard automation loop. Python is convenient for model adapters, experiment
logs, replay tools, and later a dashboard.

Mupen64Plus/Libretro remains a possible future backend for a Linux host. A
custom Libretro frontend must also manage the N64 core's graphics context and
controller mapping. That is unnecessary work for the first Windows prototype.
Backend code and action data are separated so we can replace the emulator
transport without redesigning the agent.

## Control loop

The bridge starts paused. Python publishes a bounded request by atomic rename.
Lua reads it, validates the entire sequence before executing anything, and
removes the consumed mailbox. For every requested frame, it applies the inputs,
unpauses, calls `emu.frameadvance()`, then pauses when the coroutine resumes.
It checks the frame counter at every boundary. At the end, all controlled
buttons and axes become neutral, a PNG is written, and the response is published.
Idle calls `emu.yield()` while paused, so the UI remains usable while game time
stays stopped. There are no wall-clock sleeps controlling game movement.

An observe request has zero segments and advances zero frames. A sequence
supports multi-button chords and precise press/release timing. Intermediate
frames within a sequence do not produce screenshots; use short separate
requests when visual feedback is needed.

## Vision-only rule

The model-facing adapter exposes:

- Current screenshot and a few recent screenshots.
- Executed controller actions, including durations.
- The task goal and compact notes derived from visible observations.

It does not expose RAM, world positions, Mario's velocity or movement state,
collision geometry, invisible rewards, or emulator debug metadata. Pixel-based
HUD reading is allowed. Generic knowledge of Mario 64 can be included in the
prompt, but the game state must come from images.

Operational frame counts exist to verify that the harness did exactly what was
requested. They are not measurements of Mario's state. This first milestone
implements no RAM APIs at all.

## Model, commentary, and budget

`model.py` targets `gpt-6.1-sol` explicitly through the official Responses API.
The key comes from the local `OPENAI_API_KEY` environment variable. Requests
use the standard service tier, medium reasoning by default, structured JSON
output, and a 4,096-token output cap. No response-chain IDs are supplied: every
turn gets at most four recent images, eight executed action records, the goal,
and a compact memory note. Debug frame counters are not in this payload.

The structured answer contains a public commentary, memory, completion flag,
and controller segments. Commentary is normalized to at most two sentences and
280 characters. Model actions are validated locally before any execution.
Private reasoning output items are ignored and never displayed or saved.
An unexpected model, refusal, malformed action, or incomplete response stops
the run without applying the requested inputs.

Before generation, the input-token counting endpoint counts the same context.
The app checks a reserve using the largest standard input rate (including cache
writes) plus the entire output cap at the standard output rate. Context is also
capped at 100,000 input tokens, below long-context pricing thresholds.
The reserve is persisted before generation. Returned usage settles the reserve
and records cached input, cache writes, output, and reasoning counts. Reasoning
is already included in output and is not added again for cost calculation.
Even an incomplete or rejected answer is counted when usage is returned.

Prices are dated 2026-10-04, with input/cached/cache-write/output rates of
$2/$0.10/$2.50/$10 per million tokens. These are estimated standard charges,
not authoritative account billing. Regional premiums and pricing changes are
not modeled. An unknown request outcome retains its reserve and stops; an
unexpected service tier also stops for billing verification. Limits are per run.

## Observer and run records

`runner.py` serializes emulator ownership, model requests, and actions in one
worker. The HTTP server stays responsive while the model thinks. Pause stops
before the next action and retains a completed pending decision; resume does
not pay for that decision again. Stop discards a pending decision after
in-flight work completes. A running input burst remains bounded and finishes
before the emulator pauses. Process exit during generation can leave usage
unconfirmed; that state is written before sending the request.

`server.py` listens on 127.0.0.1 only. The bundled browser UI polls public state,
shows the latest screenshot, brief commentary, selected inputs, token/cost
metrics, and event timeline. It supports saved-run inspection and ZIP export.
Local control requests require a server-issued token, a loopback Host header,
and a local Origin when present. The API key is never returned to the browser.
There is no external UI host, CDN, analytics, or JavaScript dependency.

Each run has an append-only JSONL event log (flushed and synced after each
event), atomic state snapshots, copied screenshots, and usage/latency/API IDs.
Logs exclude Authorization headers, API keys, raw reasoning blocks, and image
base64. They include goals, public commentary, compact notes, and visible game
images, so users can inspect a bundle before sharing it. Archived runs are
read-only; restarting the server does not automatically resume old sessions.

Demo mode uses a labelled synthetic scene and scripted decisions with zero API
usage. It tests the observer and records without pretending to run Mario 64.

## Local protocol

`start.lua` loads the packaged `gpt64/bridge.lua` with an absolute working
directory. The transport is local files; no networking or Lua socket/JSON
dependency is needed. Request files are numeric/text data, never evaluated Lua.

`request.txt` contains a header, runtime session ID, request ID, segment count,
then one `frames x y button_mask` line per segment. The limits are checked in
both Python and Lua. Buttons use the order in `gpt64/actions.py`.

Lua publishes `ready.json` and `responses/<request-id>.json`, writes `images/<request-id>.png`,
and removes readiness when the script exits. Python keeps `actions.jsonl`, an
exclusive `client.lock`, and a persistent `pending.json` for an unconfirmed
request. The session changes whenever Lua starts, so stale queued requests
cannot run after a restart. A duplicate of the last successful request is
consumed without replaying the action.

A timeout never sends a retry. An action may have executed even if its response
was lost. The pending marker blocks subsequent requests, including after a
Python restart. Recovery is explicit: stop Lua, run `init --reset`, and reload
the generated script. Logs and screenshots are retained. Do not infer that a
failed action made no game progress.

## Current limits

- Real Windows BizHawk execution and N64 rendering have not been tested yet.
- The Lua host tests simulate the coroutine contract; they do not prove
  BizHawk's main-loop timing. Run the real `smoke` check before agent integration.
- Frames are emulator ticks, not guaranteed unique rendered Mario frames.
- Manual unpause, other scripts, movies, rewind, and physical controller input
  can interfere. Run the bridge alone; frame checks detect many such problems.
- Live OpenAI API access and real Mario gameplay are not yet validated. Model
  tests use simulated provider responses; they do not demonstrate playing skill.
- There is no save-state API. Checkpoints can be managed manually in BizHawk.
- `init --reset` assumes the previous Lua script was stopped. One bridge
directory belongs to one emulator and one Python client.
- Logs and screenshots accumulate locally; retention controls are a later task.

## Verified API sources

These APIs were checked against BizHawk's pinned 2.11.1 source, not inferred
from desktop hotkeys:

- [EmulationLuaLibrary](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.Common/lua/CommonLibs/EmulationLuaLibrary.cs): frame count, frame advance, paused UI yield.
- [ClientLuaLibrary](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.Common/lua/CommonLibs/ClientLuaLibrary.cs): pause/unpause, screenshots, OSD suppression.
- [JoypadLuaLibrary](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.Common/lua/CommonLibs/JoypadLuaLibrary.cs): button overrides and analog autoholds.
- [N64Input](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Emulation.Cores/Consoles/Nintendo/N64/N64Input.cs): stick axes, direction signs, button names.
