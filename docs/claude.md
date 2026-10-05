# Claude Pro through the official Claude app

The subscription option uses **official, unmodified Claude Code**, signed in
by you with your Claude account. gpt64 exposes local MCP tools for screenshots
and bounded controller decisions. Claude performs inference in its own app;
gpt64 does not implement Claude OAuth, read its credentials, or call a Claude
inference endpoint with subscription tokens.

Anthropic's [authentication guidance](https://code.claude.com/docs/en/legal-and-compliance)
allows an end user to sign into the unmodified Claude Code binary with their
subscription. It does not permit third-party apps to offer their own Claude.ai
login or intermediate users' subscription credentials. MCP is the supported
[tool connection](https://code.claude.com/docs/en/mcp), including image results.
This is why the sign-in and model chooser stay in the native app.

## First time

1. Install official Claude Code on native Windows, following
   [Anthropic's setup guide](https://code.claude.com/docs/en/setup). One option,
   in PowerShell, is:

   ```powershell
   winget install Anthropic.ClaudeCode
   ```

   Open a new terminal afterward and verify `claude --version`. The launcher
   expects the native `claude.exe`, rather than an npm command shim. It does not
   download, replace, or modify Anthropic's binary.
2. Stop any ChatGPT dashboard server. Run **start-claude.cmd**. The same automated
   emulator startup and persistent files are used.
3. In the dashboard, choose **Open Claude Code**. A native interactive terminal
   opens with this project's MCP tools. Sign into your Pro account using the
   official browser flow. If it offers an API key or Console account, choose
   your subscription account deliberately; gpt64 does not control native billing.
4. Choose `/model` in Claude Code and select a model that your account offers.
   gpt64 places no hardcoded Claude-model list or API-price restriction on it.
   Use `/usage` to check your plan; normal account/model/region limits apply.
5. Back in the dashboard, enter your goal and choose **One decision**.
6. Tell Claude: **Use gpt64 to work toward the dashboard goal.** Approve the
   gpt64 game tools if Claude asks. It sees the paused screenshot and submits
   short public commentary plus controller segments. The dashboard displays
   and records them before execution.
7. One decision pauses after its action. To continue, choose One decision or
   Resume run in the dashboard, then tell Claude to continue. For an autonomous
   bounded session, use Start/Resume run and a small decision limit such as 10.
   Let Claude stop when the dashboard reports pause, stop, completion or a limit.

Later starts use the same launcher, native sign-in and model picker. You can
reuse the Claude window while the dashboard stays open. After replacing the
project or restarting the dashboard, close the old Claude session and open a
fresh one so its MCP connection and instructions are current.

## What is available in the dashboard

Screenshots, the public 1–2 sentence commentary, selected controls, pending
inputs, executed action counts, pause/stop, errors, saved logs and run exports
work for both providers. Actual Claude model IDs, token counts, cost and remaining
allowance are **unavailable** through this local game connection; gpt64 labels
those fields accordingly. Use the official app's `/model` and `/usage`.

Pause or Stop controls **the game**, and prevents queued inputs from executing.
It cannot cancel inference that Claude already started. Press Esc in Claude to
interrupt model work. A decision limit bounds accepted game decisions; it is
not a Claude token/spend limit. Check your native account's usage settings.

## What is connected

Startup writes `%LOCALAPPDATA%\gpt64\data\claude-mcp.json` and
`claude-instructions.txt`. The launcher opens an interactive Claude Code session
with `--strict-mcp-config`, this config, `--tools ""` (no built-in filesystem,
shell or network tools), and the Mario instructions. It does not use `-p`, bare
mode, a custom authentication flow, a modified binary, or permission bypass.
Claude's own permission prompts and authentication methods remain available.

The MCP child process uses stdio JSON-RPC. Its only tools are:

| Tool | Effect |
| --- | --- |
| `observe` | Return the paused screenshot, goal, visible memory and confirmed input history |
| `act` | Queue one validated decision referencing the current screenshot ID |

The dashboard owns the emulator and enforces all frame/button limits, pause,
stop and decision limits. A pending/stale decision cannot be submitted twice.
The child connects only to a loopback dashboard, using a local control token.
That token is unrelated to your Claude credentials and is excluded from exports.

MCP transport and control behavior are tested with a simulated Claude client
and BizHawk host. Real Claude Pro sign-in/model play has not been exercised on
your computer yet. See the [Windows guide](windows.md) for recovery.
