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
   ChatGPT Settings > Usage, then choose **One decision**.

The default uses eligible ChatGPT plan access. Plus eligibility and GPT-6.1 SOL
availability must be checked on your account. The app never switches to paid
API billing automatically. A separate API-key path is documented as an optional
choice. Keep keys and ROMs on your PC; do not send them to chat.

The model receives Mario-specific instructions on every turn. See
[what the agent is told](docs/agent.md). Live emulator play and account-specific
sign-in/inference still need validation on your computer.
