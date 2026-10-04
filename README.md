# gpt64

A vision-only, turn-based control harness for Super Mario 64 in BizHawk on Windows.

**Status:** the first emulator bridge is implemented. Python and Lua contract tests
run without a ROM. Real BizHawk + Mario 64 validation is still required; this is
not yet an autonomous Mario player.

## Recommended approach

Use Python for the agent and BizHawk Lua for the emulator. The emulator stays
paused while the agent thinks. Each action holds an analog stick position and a
set of buttons for an exact number of **emulator frames**, then pauses and takes
a PNG screenshot. These are N64 emulation frames, not necessarily distinct game
renderings; measure the host's frame rate before interpreting durations as seconds.

The eventual agent receives only screenshots, its own action history, and notes
it wrote from those observations. The bridge does not read RAM, coordinates,
collision state, or other hidden game data. Frame counters and controller names
are harness diagnostics, not agent observations.

## Start on Windows

Install Python 3.11+ and [BizHawk 2.11.1](https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1)
with its listed prerequisites. Supply your own Mario 64 ROM locally.

In PowerShell, from this repository:

```powershell
py -m gpt64 init
```

Open your ROM in BizHawk, pause it, and open **Tools > Lua Console**. Open the
`start.lua` file printed by `init`. Leave the script enabled. The Lua Console
should print `gpt64 bridge ready`. Avoid other Lua scripts, movies, autoholds,
rewind, or manual input during a run.

```powershell
py -m gpt64 doctor
py -m gpt64 observe
py -m gpt64 smoke
py -m gpt64 step --x 0 --y 0.6 --frames 12
py -m gpt64 step --button A --frames 4
py -m gpt64 sequence examples\jump.json
```

Screenshots and action logs go into `.gpt64/bridge/`. There are no Python
dependencies, model credentials, or API charges for this first milestone.
`smoke` advances 30 neutral frames and checks that time does not pass between
requests. Use it from a harmless starting screen.

`x` and `y` are normalized values in [-1, 1]. Positive x is stick right;
positive y is stick up. This is a controller direction, not an absolute world
direction: Mario moves relative to the game's camera. A value of 1 maps to 80
N64 stick units, a conservative practical range.

Each segment is 1–120 frames, and a sequence is at most 16 segments and 240
frames in total. Start with 6–15 frame actions around obstacles. A sequence can
express press/release timing, such as holding A briefly, then releasing it while
continuing forward. No default action macros claim to have been calibrated in
the game yet.

## Build order

1. **Validate the bridge in real BizHawk.** Exact frame counts, frozen idle time,
   live screenshots, analog movement, jump press/release, and camera buttons.
2. **Calibrate control from screenshots.** Compare before/after movement and
   jumps. Save a repeatable starting state locally for debugging.
3. **Add the vision agent.** A configurable model, structured action output,
   recent screenshots, compact notes, bounded actions, and step/token budgets.
   The agent should stop and re-observe when uncertain.
4. **Attempt one task.** First enter Bob-omb Battlefield; then attempt one star.
   Add longer runs and an observer dashboard after a reliable short run.

See [architecture](docs/architecture.md) and [Windows validation](docs/windows.md).

## Development

```powershell
py -m unittest discover -s tests -v
```

On Linux with `liblua5.4`, the suite also executes the actual Lua bridge against
a simulated BizHawk host. CI requires those Lua tests. This verifies the
protocol and frame-control logic, not N64 rendering or actual Mario gameplay.

ROMs, emulator binaries, save states, local logs, and credentials are excluded
from git.
