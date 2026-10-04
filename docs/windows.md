# First Windows validation

Use [BizHawk 2.11.1](https://github.com/TASEmulators/BizHawk/releases/tag/2.11.1)
and Python 3.11+. Install BizHawk's release prerequisites. Keep the ROM and
emulator installation outside the repository. A US/NTSC ROM is a useful
consistent starting point; record its region and hash when comparing runs.

The harness is independent of ROM revision. Actual behavior, timing, and save
states depend on the ROM and core. Begin with an ordinary working BizHawk N64
configuration. Mupen64Plus is the intended first backend when available; the
bridge also checks the active controller names instead of silently guessing.
Do not spend time optimizing renderer accuracy before validating controls.

1. Run `py -m gpt64 init` from the repository.
2. Load Mario 64 in BizHawk and verify it renders normally. Pause the emulator.
3. Open Tools > Lua Console and load the absolute `start.lua` printed by init.
4. Check for `gpt64 bridge ready`. Keep the script enabled and the Lua Console
   open. Ensure player 1 is connected. Disable movies, rewind, other scripts,
   and manual input for this test.
5. Run `py -m gpt64 doctor`. Open the printed PNG and confirm it matches the
   current screen, with no emulator OSD covering the game.
6. Run `py -m gpt64 smoke`. It requests 30 neutral frames, checks the exact
   counter difference, and waits between observations to verify frozen time.
7. From a safe playable area, request a short stick movement, an A press and
   release, and each C-button camera action. Compare the screenshots visually.
   Frame counts alone do not prove that the game accepted the controls.

Example commands, from the repository:

```powershell
py -m gpt64 step --y 0.6 --frames 12
py -m gpt64 sequence examples\jump.json
py -m gpt64 step --button "C Left" --frames 2
py -m gpt64 observe
```

The jump example is a controller sequence, not a calibrated movement skill.
Mario's facing, camera orientation, terrain, and momentum all change the result.
Load or save a repeatable starting state manually in BizHawk between calibration
runs; state operations are not yet exposed to the harness.

For a custom working directory, put the global option before the command:

```powershell
py -m gpt64 --bridge C:\gpt64-run init
py -m gpt64 --bridge C:\gpt64-run smoke
```

If a request times out or the client is interrupted, **stop the bridge script
in Lua Console first**, then run:

```powershell
py -m gpt64 init --reset
```

Reload the printed launcher. Recovery preserves existing images and logs. An
unconfirmed action may already have moved Mario; inspect the next screenshot.

If setup reports missing controller names, record the BizHawk version, active
N64 core, and output of `joypad.get(1)` in Lua Console. If screenshots are blank,
verify normal ROM rendering and inspect the Lua Console. If smoke reports extra
frames, stop and resolve emulator timing before adding an agent.

## Acceptance record

When real validation is complete, record the host OS, BizHawk version, N64 core,
renderer, ROM region/hash, smoke output, and whether movement, jumps, releases,
and camera controls visibly worked. Do not commit the ROM or save state.
