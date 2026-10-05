# Start here: gpt64 0.4 on Windows

1. Install Python 3.11+ with its Windows launcher. Download BizHawk 2.11.1,
   install its prerequisites, and keep its release folder intact. Keep your
   locally dumped Mario 64 ROM outside this project.
2. Extract the project's files together. Double-click **start.cmd**.
   It creates or updates a reusable Python environment automatically. On the
   first real start, select `EmuHawk.exe`, then your ROM in the two file pickers.
3. Startup remembers those paths, launches BizHawk with its Lua bridge, verifies
   a paused screenshot, and opens `http://127.0.0.1:8765`. It sends no inference.
4. For ChatGPT, choose **Continue with ChatGPT** once, grant plan usage, review
   app limits in ChatGPT settings, and choose any model in **Refresh models**.
   Begin with **One decision**. The app remembers your selection and run settings.
5. For Claude instead, install official Claude Code, then use
   **start-claude.cmd**. Follow [the Claude guide](docs/claude.md): sign in and
   select a model inside the official app, which connects to the game's local
   screenshot/action tools. No Claude credential is copied into gpt64.

**Next time:** double-click the appropriate start launcher. It reuses a live
bridge or loads the ROM/Lua automatically. **demo.cmd** needs no emulator or
account. **setup-windows.cmd** can provision the environment without starting.

**Replacing files:** stop the dashboard and close BizHawk, then replace the
whole source folder and run start.cmd. Runtime, settings, logs and sign-in live
outside that folder. You do not need to preserve individual source files.

**First upgrade from 0.3.x:** overwrite the old project with this version first,
keeping its old `.gpt64` folder for that first start if you want its logs imported.
Startup copies the old run records into persistent storage. After that, the
entire project folder can be replaced. ChatGPT sign-in was already stored outside
it and is retained. No emulator mailbox or pending action is migrated.

See [the full Windows guide](docs/windows.md) for persistent paths, manual
commands, recovery, optional API billing, and first-upgrade details. Live
account inference and real emulator gameplay still need testing on your host.
