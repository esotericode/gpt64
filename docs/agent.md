# What the selected model is told

Yes: the application sends an explicit Mario 64 instruction block **on every
turn**, in the Responses API `instructions` field. The exact text is
`INSTRUCTIONS` in [model.py](../gpt64/model.py). Print it locally with:

```powershell
& "$env:LOCALAPPDATA\gpt64\runtime\Scripts\python.exe" -m gpt64 instructions
```

Your setup work does not train or fine-tune a new model. The application supplies
the selected model ID, task and controls with each request. The initial ID is
`gpt-6.1-sol`; use the account-specific model picker or `serve --model MODEL_ID`
to choose another. These Mario instructions and action limits apply to every model.

## Its task and observations

It is told to play Super Mario 64 toward the goal you enter, using screenshots
and its own confirmed input history. Each turn contains at most four recent
screenshots, eight confirmed action sequences and compact visual notes.
The app never supplies RAM, invisible coordinates, collision maps or Mario's
internal movement state. The model can interpret visible HUD elements.

It is told that the game is paused during deliberation. Each returned segment
holds a stick position and button chord for its specified emulator ticks, after
which the harness releases controls and captures the next paused screenshot.

## Controls and output contract

| Field | Meaning / limits |
| --- | --- |
| `commentary` | Public explanation tied to visible evidence and the selected input; 1–2 sentences, at most 280 characters |
| `memory` | Compact notes from visible observations and confirmed outcomes; up to 1,500 characters |
| `done` | Completion claim supported by screenshots; must have no segments |
| `segments[].frames` | 1–120 emulator ticks per segment |
| `segments[].x`, `y` | Analog axes from -1 to 1; right/up are positive and camera-relative |
| `segments[].buttons` | `A`, `B`, `Z`, `Start`, `L`, `R`, `C Up`, `C Down`, `C Left`, `C Right` |
| Entire sequence | Up to 16 segments and 240 ticks |

It is instructed to use short bursts near obstacles, check the next observation,
and release buttons explicitly between presses when needed. It cannot execute
arbitrary Python or Lua. The response is structured JSON; Python validates it
before sending a numeric mailbox packet, and Lua validates it again.
The prompt explicitly asks for one raw JSON object without Markdown fences.
Intermediate API commentary messages are excluded from decision parsing; the
public `commentary` field inside the final JSON is what the dashboard displays.

For example, this illustrates a proposed short jump press and release. It is
not a calibrated Mario skill:

```json
{
  "commentary": "The ledge is directly ahead, so I will try a short forward jump. I will check the landing before moving further.",
  "memory": "A low ledge is visible ahead.",
  "done": false,
  "segments": [
    {"frames": 6, "x": 0, "y": 0.5, "buttons": ["A"]},
    {"frames": 4, "x": 0, "y": 0.5, "buttons": []}
  ]
}
```

Claude via MCP receives the same contract as tool instructions; sign-in and model selection remain in its official app. It submits the decision to the local act tool, instead of returning a direct Responses API answer.

The dashboard shows commentary before execution and keeps it in the run log.
It is a brief public action explanation. Private model reasoning output is
ignored and not recorded. We also normalize commentary to the two-sentence/
280-character limit if the model writes too much.

## What happens on the next turn

Confirmed actions and the new screenshot become the next request's context.
Unconfirmed emulator actions stop the run instead of being assumed successful.
Completed pending decisions can be held by Pause and resumed without another
model request. Model knowledge alone does not prove a successful jump or star;
the instructions ask for visible evidence. Successful autonomous play still
needs real emulator evaluation.
