# Start here: gpt64 on Windows

1. Extract this project to `C:\gpt64\project`. Install Python 3.11+ and
   BizHawk 2.11.1 with its prerequisites. Put BizHawk and your ROM in the separate
   folders shown in [the full Windows guide](docs/windows.md).
2. Run **setup-windows.cmd** once. It creates a local Python environment and
   installs the sign-in support. No account is billed by setup.
3. Run **demo.cmd** to inspect the dashboard at `http://127.0.0.1:8765` for free.
   Close it with Ctrl+C before starting the real server.
4. Follow the guide's bridge setup: generate `start.lua`, open your ROM in
   BizHawk, pause, load that script in Lua Console, then run doctor and smoke.
5. Run **start.cmd**. In the dashboard choose **Continue with ChatGPT** and grant
   plan usage on the official OpenAI sign-in page. Check your app limits in
   ChatGPT Settings > Usage. In Run controls choose **Refresh models**, select a
   listed **Agent model**, then choose **One decision**. Try `gpt-6-sol` first if
   it appears, then `gpt-6-luna`.

The default uses eligible ChatGPT plan access and initially selects GPT-6.1 Sol.
You can explicitly choose another model your account lists. Catalog access does
not guarantee an admitted inference request. The app never switches to paid
API billing automatically. A separate API-key path is documented as an optional
choice. Keep keys and ROMs on your PC; do not send them to chat.

The model receives Mario-specific instructions on every turn. See
[what the agent is told](docs/agent.md). Live emulator play and account-specific
sign-in/inference still need validation on your computer.

Already installed 0.3.0? Stop the server and Lua script, replace the source files
in the same project folder, preserve `.gpt64` and `.venv`, rerun setup-windows.cmd,
then reload the Lua launcher and start.cmd. Your saved sign-in lives separately
and is retained. See [upgrade details](docs/windows.md#upgrading-an-existing-installation).
