# Mei

A local, privacy-first desktop agent for Windows. Mei listens to voice or
text commands, decides what you mean using local language models (no cloud
API calls), and carries it out by directly controlling your OS — launching
apps, driving windows, automating browsers, and falling back to visual
screen understanding when standard automation can't reach an app's UI.

> **Status: pre-alpha, actively developed.** Core architecture works end to
> end, but this is a solo research/hobby project, not a finished product.
> See [Known Limitations](#known-limitations) before expecting production
> reliability.

<!-- TODO: screenshot or short GIF of the TUI in action goes here -->
<!-- ![Mei TUI](docs/images/tui-screenshot.png) -->

## Features

- **Fully local** — intent understanding and planning run on local GGUF
  models via `llama.cpp`; nothing is sent to a cloud LLM API.
- **Tiered execution** — remembers goals it's successfully completed before
  and can replay them directly once they've proven reliable, falling back to
  full reasoning for anything new or recently unreliable.
- **OS automation** — launches and controls applications, windows, and
  keyboard/mouse input via Windows UI Automation.
- **Dynamic browser control** — discovers whichever browsers are actually
  installed on your machine (via Windows' own browser registrations) rather
  than assuming one specific browser, and drives them over Chrome DevTools
  Protocol through Playwright.
- **Graph-based memory** — a Kùzu-backed memory of past goals, actions, and
  their outcomes, with a reliability score that decays over time rather than
  accumulating forever, so a workflow that used to work but has since broken
  doesn't keep its old trust indefinitely.
- **Visual fallback** — when an app hides its UI elements from standard
  accessibility APIs, Mei can fall back to a vision model (OmniParser) to
  find what it's looking for on screen.
- **Teach-by-demonstration** — record a sequence of commands as a named
  workflow (`/teach`) and replay it later.
- **Voice input** — wake-word detection and local speech-to-text via Whisper.

## Known Limitations

Being upfront about where this currently stands:

- **Windows only** — relies on `pywin32`, Windows UI Automation, and native
  Kùzu/CUDA builds. Linux/macOS support is a possible future direction, not
  current scope.
- **The TUI currently hangs after the first command on some setups** — this
  is unresolved and under active investigation. **Use `py app.py --headless`
  for now** until this is root-caused; it doesn't have the TUI's slash
  commands, but command execution itself is reliable there.
- **Multi-step command decomposition is inconsistent** — compound,
  multi-clause commands sometimes get decomposed into fewer steps than
  intended, or a less-than-ideal tool/parameter gets picked. This is being
  actively investigated; the cause isn't pinned down yet, and it's too early
  to say how much of it is addressable through prompting/retrieval
  improvements versus requiring fine-tuning or further training of the
  local models currently in use. Not claiming this is a hard ceiling — just
  that it's an open problem right now.
- **No automated test suite yet** — correctness is currently verified by
  manual runs, not CI.
- **Experimental automation** — Mei executes real shell commands, file
  operations, and browser actions on your machine. See
  [Security](#security) before giving it broad permissions.

## Requirements

- Windows 10/11
- Python 3.11
- A GPU is recommended (the default models target a modest consumer GPU with
  a few GB of VRAM) but CPU-only inference works, just slower
- A few GB of free disk space for model weights (downloaded separately, see
  below — they are not stored in this repository)

## Resource Usage

> The figures below are derived from the default models' known file/context
> sizes and an explicit VRAM budget noted in the code — they are **design
> targets, not measured benchmarks**. Actual usage will vary by hardware and
> hasn't been profiled with a tool like Task Manager/`nvidia-smi` yet.
> <!-- TODO: replace with real measured numbers once profiled. -->

**VRAM**: Mei is explicitly designed around a **~4GB VRAM budget** and loads
only one local LLM at a time — a GPU-exclusivity mechanism unloads whichever
model is currently resident before loading the next (intent model, planner
model, and the visual-fallback vision models all share this one slot; they
are never all in VRAM simultaneously). As a concrete reference point from the
code itself: the default intent model (Phi-3.5-mini, Q5_K_M) alone is
~2.6GB of weights plus ~2.3GB of KV-cache at its configured context length —
already close to saturating a 4GB GPU by itself. The default
general-purpose model (Qwen2.5-3B, Q4_K_M) and the planner (xLAM-2-1B) are
both smaller. Running on CPU only avoids VRAM entirely but is slower.

**System RAM**: no hard minimum has been measured; 8GB is a reasonable floor
and 16GB+ is more comfortable, since the active model, the embedding model
used for memory/tool retrieval, the Kùzu graph database, and (if GPU layers
are partially offloaded) the portion of the model kept in system RAM all
need to coexist with the OS and whatever else you're running. This is a
rough recommendation, not a verified requirement.

**CPU**: `llama.cpp` is configured for up to 16 threads by default
(`LLMConfig.threads`, adjustable in `config.yaml` for lower-core-count
machines) during model inference. Expect noticeable CPU usage during
intent/planning steps regardless of GPU offload, and heavier CPU load if the
visual fallback (OCR + object detection) triggers, since that pipeline is
CPU-heavier than the LLM-only path.

**Ongoing/idle usage**: once a model has been swapped out (its slot given to
another model, or no command is being processed), it's unloaded rather than
kept resident, so idle VRAM/RAM usage should drop between commands — this
follows from the GPU-exclusivity design but hasn't been separately profiled
either.

## Installation

```bat
git clone https://github.com/ShivaanshGusain/Mei.git
cd Mei
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` is a full snapshot of the development environment,
including a CUDA build of `llama-cpp-python` — if you don't have an NVIDIA
GPU, install a CPU-only build of `llama-cpp-python` instead before running
the rest.

**Model weights** (not committed to this repo — download separately into
`models/`):

| File | Role |
|---|---|
| `qwen2.5-3b-instruct-q4_k_m.gguf` | Default/general-purpose LLM |
| `Phi-3.5-mini-instruct.Q5_K_M.gguf` | Intent decomposition |
| `xLAM-2-1B-fc-r-Q4_0.gguf` | Tool-calling planner |
| `whisper-model/` | Speech-to-text |

<!-- TODO: add the exact download links/sources you actually used for each
     model above, plus the OmniParser icon_detect/icon_caption weights
     (see NOTICE.md for their licenses before redistributing anything). -->

On first run, Mei auto-generates a `config.yaml` with sensible defaults if
one doesn't already exist — edit it afterward to point at different model
paths, change audio settings, etc.

## Usage

```bat
:: Use this for now — see Known Limitations, the TUI currently hangs
:: after the first command on some setups
py app.py --headless

:: Interactive terminal UI — has slash commands below, but unreliable
:: right now (hang after first command, unresolved)
py app.py
```

TUI commands (headless mode only supports plain-text commands, none of the
slash commands below):

| Command | Does |
|---|---|
| *(plain text)* | Give Mei a command |
| `/teach <name>` → `/done` | Record a named workflow, then save/discard it after review |
| `/query <cypher>` | Run a raw query against the live memory graph |
| `/tools` | List every registered tool |
| `/memory` | Quick memory stats |
| `/graph` | Export the memory graph as an interactive HTML visualization |
| `/wipe` | Wipe the memory database (confirmation required) |
| `/restart` | Restart the agent worker if it gets stuck |
| `/help` | Full command list |

See `Markdown files/Verification_And_Usage_Guide.md` for a more complete
walkthrough.

## Architecture

In short: a command goes through memory lookup → (depending on how
confident/reliable the match is) either a direct replay, a lighter
re-verification, or a full intent-decomposition-and-planning pass → tool
execution → observation → memory update. Tools are organized by domain (app,
window, input, web, filesystem, system) behind a shared executor and
validation/verification layer.

For the full, evidence-grounded architecture writeup — every major
component, the complete runtime flow, memory/model/tool architecture
diagrams, and known technical debt — see
`Markdown files/Full_Architecture_Audit.md`.

## Configuration

- `config.yaml` (auto-generated on first run) — model paths, audio settings,
  memory/Kùzu settings, GPU layer allocation.
- `Mei/config/guardrails.yaml` (Ed25519-signed) — the allowlist of
  executables Mei is permitted to run via shell commands, plus write-path
  restrictions. This is the primary safety boundary for system-level actions.

## Security

Mei executes real shell commands, file operations, and browser automation on
your machine based on natural-language commands interpreted by a local
language model. It is experimental software:

- Review `Mei/config/guardrails.yaml` before running it with broad
  permissions.
- Don't point it at commands or directories you wouldn't want an
  occasionally-wrong automated process touching.
- There is currently no interactive confirmation step before executing
  file-deletion or shell commands beyond the static allowlist — treat it
  accordingly.

## Acknowledgments

Mei vendors Microsoft's [OmniParser](https://github.com/microsoft/OmniParser)
for visual-UI fallback, and depends on several separately-downloaded local
models (Qwen2.5, Phi-3.5, xLAM, Whisper). Full attribution and per-component
licenses are in [`NOTICE.md`](./NOTICE.md).

## License

MIT — see [`LICENSE`](./LICENSE). Third-party components are licensed
separately; see [`NOTICE.md`](./NOTICE.md).
