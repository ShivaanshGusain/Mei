# Third-Party Notices

Mei's own source code is MIT licensed (see `LICENSE`). It depends on and
vendors the following third-party components, each under its own license.

## Vendored in this repository

**OmniParser** ([microsoft/OmniParser](https://github.com/microsoft/OmniParser)) —
`Mei/perception/Visual/OmniParser/` and `Mei/perception/Visual/Omniparser_try_fix/`.
Used as the visual-UI fallback when standard Windows UI Automation can't find
an element (e.g. in apps that hide their accessible UI tree). Licensed
**CC-BY-4.0** (Creative Commons Attribution) — Copyright Microsoft
Corporation. Attribution requirement satisfied by this notice.

## Model weights — downloaded separately, not committed to this repository

These are fetched at setup time (see README's Installation section) and are
**not** part of Mei's git history. Each carries its own license, which
applies to you as the end user downloading and running it, not to Mei's own
code:

| Component | Used for | License |
|---|---|---|
| OmniParser `icon_detect` weights (YOLO-based) | Visual element detection | **AGPL-3.0** |
| OmniParser `icon_caption` weights (Florence-2-based) | Visual element captioning | MIT (Microsoft) |
| Qwen2.5-3B-Instruct (GGUF) | Default/general LLM | Qwen License (see model card) |
| Phi-3.5-mini-instruct (GGUF) | Intent extraction | MIT (Microsoft) |
| xLAM-2-1B-fc-r (GGUF) | Tool-calling planner | See model card |
| Whisper | Speech-to-text | MIT (OpenAI) |

The `icon_detect` weights are AGPL-3.0 — a copyleft license. Mei does not
redistribute this file (it's `.gitignore`d, downloaded independently by each
user from its original source), which keeps it outside the scope of what
this repository conveys. If you fork Mei and choose to bundle/distribute
these weights yourself, be aware of AGPL-3.0's copyleft obligations before
doing so.

Always check each model's current license on its own model card before
commercial or redistribution use — the table above reflects what was
verified at the time this file was written and may not reflect upstream
changes.
