# RadSim UI Redesign — Animations & Tool-Call Renderer

## Context

The current RadSim terminal UI has two visually weak areas:

- **Animations feel dated.** The boot sequence spends ~600ms on a static loading bar (`radsim/output.py:87–98`) and typewriter-prints three command hints (`output.py:145–157`). Onboarding uses per-character `animate_text` + `time.sleep(0.5)` waits. Spinners are called ad-hoc at 8 sites with no unified style and no user toggle.
- **Tool calls look heavy and generic.** Every tool invocation prints a 4–6 line ASCII-box (`┌─ │ └─`, `output.py:364–442`) studded with per-tool emoji (📄 ✏️ 🔄 ⚡ 📁 🔍 🔎 📊 💾 ➕ 🌐 🧪 🌍), followed by a rich-panel result, followed by another boxed shell-output block. A single `read_file` burns ~8 lines.

User feedback: "it looks tacky." Additional direction:
- **Do NOT clone Claude Code style.** Create a variant unique to RadSim's stated principles (Radical Simplicity: extreme clarity, self-documenting names, flat > nested, explicit > implicit).
- **Remove all emoji from the tool-call pipeline.** Verbs and plain punctuation only.

The new `radsim/theme.py` already provides glyph-by-font-profile + settings persistence. This redesign reuses it end-to-end.

---

## RadSim Visual Identity

The redesign expresses RadSim's "Radical Simplicity" principle in pixels:

- **Verbs, not icons.** The tool name itself (`read`, `write`, `grep`, `shell`) IS the indicator — self-documenting. No leading dot/circle/arrow glyph.
- **Columns, not boxes.** No `┌─ │ └─` frames. Vertical alignment replaces borders.
- **No emoji anywhere in tool-call rendering.** No 📄 ✏️ ⚡ ✅ ❌. Status words (`ok`, `fail`, `error:`) and plain separators.
- **One line per tool call.** In-flight → final overwrite on the same line.
- **Quiet motion.** Spinner is at most a single morphing character; most users run at `subtle` level (static glyph only).

The resulting look is closer to a well-designed build tool (`cargo`, `bun`, `uv`) than an AI chat CLI.

**Tool-call line format (bracket-tag, muted):**
```
  [read]   src/auth.py                      142 lines    34ms
  [grep]   "TODO" in radsim/**              8 matches    12ms
  [write]  src/auth.py                      +24 -7
  [shell]  pytest tests/auth                exit 0       2.1s
```
Brackets render in the `muted` palette color; the verb inside the brackets is colored by category (read/list/grep → primary; write/edit/git → accent; shell/run → warning; web/other → primary/muted). Argument column muted. Result default-weight. Duration dim. Columns: `  [{verb:<6}] {arg:<34}{result:<14}{duration}`.

**Running state:**
```
  [read]   src/auth.py                      running...
```
rewrites in place to the final form. No spinner glyph, no leading/trailing dot.

**Failure state:**
```
  [shell]  pytest tests/auth                fail         exit 1   2.1s
  └ error: AssertionError: expected 5, got 7
```
`fail` in error color. Optional indented error sub-line, one level, no boxes.

**Shell stdout/stderr:**
```
    42 files processed
    warnings: 0
    ...(12 more lines)
```
Pure indent — no `│` gutter, no top/bottom rule. Collapsed to first 3 lines by default.

---

## Goals

1. Replace ASCII-box tool-call renderer with the verb-column one-liner above.
2. Purge every emoji in `output.py`, `ui.py`, and `agent_api.py` tool-call paths.
3. Unify every spinner call site behind one style + one animation level.
4. Delete pointless delays: boot loading bar, per-char typewriter, onboarding `time.sleep(0.5)`.
5. Add `/animations` command (full | subtle | off) persisted to `~/.radsim/settings.json`.
6. All remaining glyphs (diff markers, shell gutter) route through `theme.glyph(name)` so `/font` selection drives them.

---

## Files to modify

### `radsim/theme.py`
- Extend each `FONT_PROFILES[*]["glyphs"]` with only what remains after emoji purge: `diff_add` (`+`), `diff_del` (`−` unicode / `-` ascii), `ellipsis` (`…` / `...`). Remove the earlier-proposed `event` and `running` glyphs — the verb itself is the indicator now.
- Add `ANIMATION_LEVELS = ("full", "subtle", "off")`, `DEFAULT_ANIMATION_LEVEL = "subtle"`.
- Add `load_active_animation_level()` / `save_animation_level(level)` mirroring existing `load_active_font_profile_name` at theme.py:155–176. Settings key: `"animation_level"`.
- Add `TOOL_CATEGORY_COLORS = {"read": "primary", "list": "primary", "grep": "primary", "write": "accent", "edit": "accent", "shell": "warning", "run": "warning", "git": "accent", "web": "primary"}` and `tool_category(tool_name)` helper that maps internal tool names (`read_file` → `read`, `write_file` → `write`, etc.) to both a display verb and a category color.

### `radsim/ui.py`
- Rewrite `Spinner` (67–114). Keep `start/stop/update/__enter__/__exit__` surface (8 dependents). Branch on `load_active_animation_level()`:
  - `off` → no-op.
  - `subtle` → single static line `  {message}`, erased on stop.
  - `full` → rich `console.status(spinner="dots", spinner_style="primary")`.
- Delete `print_typewriter` (252–261).
- Add `tool_event(tool_name, argument) -> ToolEventHandle`. Handle exposes:
  - `update(argument)` — rewrite the arg column.
  - `finish(ok: bool, result: str, duration_ms: float | None, error: str | None = None)` — overwrite with the final line; emit optional `  └ error: …` sub-line on failure.
  Uses `rich.control.Control` (`move_to_column(0)`, `erase_in_line(2)`) for portable rewrite. Skips rewrite entirely when `not sys.stdout.isatty()` or `animation_level == "off"` — only the final line prints in that case.

### `radsim/output.py`
- `print_boot_sequence` (65–162): delete per-line `time.sleep(0.06)` logo loop, delete 40-char loading bar (87–98), delete three `print_typewriter` calls (145–157), replace the `⚡` tagline (line 85) with a plain version. Paint logo + info box instantly. Optional reveal only at `animation_level == "full"`.
- `print_tool_call` (364–442): becomes a thin wrapper that calls `tool_event(tool_name, _summarize_argument(tool_name, tool_input))` and returns the handle. Delete the entire emoji `icons` dict (374–388) and the ASCII box drawing. Keep `set_last_written_file` side effect and the teach-mode `show_code` path (code preview stays as a rich `Panel`, the tool-call line does not).
- `print_tool_result_verbose` (445–494): collapses to `handle.finish(success, _result_summary(tool_name, result), duration_ms, error=result.get("error"))`. Delete `show_success_panel` / `show_error_panel` calls here; panels are gone from the tool pipeline. Remove the `✅` / `❌` titles.
- `print_shell_output` (497–532): replace ASCII frame with a plain 4-space-indented block, truncated to first 3 lines + `...(N more)`. No top/bottom rules. No emoji.
- Delete `SPINNER_STYLES` (43–48), legacy `print_thinking` / `clear_thinking` (223–229), and any `✓`/`✗`/`⚠` emoji in `print_success`/`print_error`/`print_warning` — replace with plain words.
- Add `_summarize_argument(tool_name, tool_input)` and `_format_duration(ms)` helpers.

### `radsim/agent_api.py`, `radsim/agent.py`, `radsim/agent_policy.py`
- Collapse the `print_tool_call` → `Spinner("Executing…")` → `print_tool_result_verbose` triple at agent_api.py:213–234 into one `tool_event(...)` / `handle.finish(...)` pair.
- Same rewrite at agent_policy.py:156–160 (MCP path) and agent.py:730–741 (shell).
- Spinner-only call sites (agent.py:359, 383, 768, 932; agent_api.py:42, 217; agent_policy.py:40) keep `Spinner("...")` — they pick up the unified style automatically.
- Strip any `[+]` / `[x]` style emoji in the Telegram branch at agent_api.py:249–256 (scope: tool-call path only).

### `radsim/commands_core.py` + `radsim/commands_metadata.py`
- Add `_cmd_animations` mirroring `_cmd_font`. Register `/animations` + `/anim` aliases in `DEFAULT_COMMAND_SPECS` (category: `appearance`).

### `radsim/onboarding.py`
- Delete `animate_text` (109–114) and its sole call.
- Delete `time.sleep(0.5)` at line 207.
- Extend the existing `step_appearance` with a third question: animation level (default Subtle).
- Leave `clear_screen`, `print_header`, `print_box` — static scaffolding, not animations.
- Emoji in onboarding prose (🔐 🎓 ⚠ ✓) is handled by the emoji-purge pass below.

---

## Animation level semantics

| Level   | Boot                 | Spinner                 | Tool events                       |
|---------|----------------------|-------------------------|-----------------------------------|
| full    | logo fade-in         | rich dots animated      | running-line → final rewrite      |
| subtle  | instant              | static label, no frames | running-line → final rewrite      |
| off     | instant              | no output               | final line only, no `\r` rewrites |

`supports_color() == False` forces `off`.

---

## Verification

1. `python -c "import radsim.theme as t; t.save_animation_level('subtle'); print(t.load_active_animation_level())"` → round-trips through `~/.radsim/settings.json`.
2. Cold launch `radsim` → boot completes under 50ms (vs ~600ms today). No loading bar, no `⚡` emoji, no typewriter.
3. `radsim "list files in radsim"` → every tool call is one aligned verb-column line, rewritten in place from `running...` to the final result. No ASCII boxes, no emoji anywhere in the transcript.
4. `grep -rE "[\x{1F300}-\x{1FAFF}]|📄|✏|🔄|⚡|📁|🔍|🔎|📊|💾|➕|🌐|🧪|🌍|✅|❌|🛑|🎓|🔐" radsim/output.py radsim/ui.py radsim/agent_api.py` → returns no matches after changes.
5. `/animations off` then run a tool → only the final line prints, no intermediate `running...`. `/animations full` → spinner animates. Setting persists across restart.
6. `/font ascii` → diff markers become `+` / `-`, ellipsis becomes `...`, verbs still render.
7. `radsim "…" | tee /tmp/out.log; grep -c $'\r' /tmp/out.log` → returns `0` (no rewrites leak to piped output).
8. Press Esc mid-tool → escape listener fires, spinner stops cleanly, final line renders with `fail` word + error sub-line.
9. Shell tool → stdout is plain 4-space-indented block, truncated correctly.

---

## Risks / edge cases

- **Non-TTY**: `tool_event` must skip `\r` rewrites when `not sys.stdout.isatty()` — guard at handle construction.
- **Stream + tool-event leak**: callers must `finish()` before returning. Add dev-only `__del__` warning in `ToolEventHandle`.
- **Rich `Live` contexts** (`PhaseProgressBar`, `LiveStatusTable`, `TaskDashboard`) don't overlap with tool events today. Document that `tool_event` must not nest inside a `Live`.
- **Windows `cmd.exe`**: prefer `rich.control.Control` over raw `\x1b[2K` — rich handles VT-mode fallback.
- **Terminal width**: `_summarize_argument` truncates to `shutil.get_terminal_size().columns - 30` with `…`.
- **Category fallback**: unknown tool names (MCP, custom) get `other` category → muted color + raw tool name as the verb.

---

## Full emoji purge (user-facing, across `radsim/*.py`)

Confirmed scope: remove every emoji-rendered character from every user-facing string in the package. Plain geometric glyphs (box-drawing `╭─╮│└`, arrows `→ ❯`) stay — they are not emoji and already route through `theme.glyph()`. Emoji replaced with bracket-tags or plain words so the RadSim identity is consistent end-to-end.

Substitution table:

| Current | Replacement | Files affected |
|---|---|---|
| `🔐 API key setup` | `[api key] API key setup` | `onboarding.py:517`, `config.py:486–502`, `commands_core.py` |
| `🎓` (teach markers) | `[teach]` | `output.py:50`, `output.py:tool_event teach path`, `onboarding.py` |
| `⚡ Radically Simple Code ⚡` | `Radically Simple Code` | `output.py:85` |
| `💡 Tip` | `Tip:` | `ui.py:260`, onboarding tips |
| `✅` (success title) | `ok` word prefix | `ui.py show_success_panel`, `output.py` |
| `❌` (error title) | `error` word prefix | `ui.py show_error_panel`, `output.py` |
| `⚠` / `⚠️` (warning) | `warning:` | `ui.py:197`, `cli.py:51,57,61`, `onboarding.py` |
| `✓` (inline success) | `ok` | `ui.py:191`, `onboarding.py`, `commands_core.py` |
| `✗` (inline fail) | `fail` | `ui.py` |
| `🛑 EMERGENCY STOP` | `EMERGENCY STOP` | `cli.py:51` |
| tool icons (📄 ✏️ 🔄 ⚡ 📁 🔍 🔎 📊 💾 ➕ 🌐 🧪 🌍) | deleted dict | `output.py:374–388` |

Method: one pass with `grep -rE "[\x{1F300}-\x{1FAFF}]|⚡|✅|❌|⚠|🛑|🎓|🔐|💡|✓|✗" radsim/` produces the exhaustive hit list; replace each call site. Where the removed emoji was decorative (boot tagline, success title) the bracket/word fills the role; where it was informational (teach marker inline in streamed code, `output.py:245–248`) substitute `[teach]` so annotated lines are still visually distinct.

File-level touchpoints beyond the tool pipeline:
- `radsim/ui.py:155,165,189,191,194,197,260,283` — panel titles and print_{success,error,warning,hint}
- `radsim/cli.py:51,57,61` — interrupt messages
- `radsim/onboarding.py` — welcome, appearance step, step_api_key, step_complete, step_tutorial
- `radsim/config.py:486–502,604,606` — setup_config prints
- `radsim/commands_core.py` — success confirmations for /theme, /font, /ratelimit, /animations
- `radsim/output.py` — teach comment prefixes (`TEACH_COMMENT_PREFIXES`, 234) need to change: `# [teach]` instead of `# 🎓`; update `is_teach_comment` detection and `style_teach_content`. Migration: detection accepts both old and new markers during transition.

---

## Critical files
- `/Users/brighthome/Desktop/RADSIM/radsim/theme.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/ui.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/output.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/agent_api.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/agent_policy.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/agent.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/commands_core.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/commands_metadata.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/onboarding.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/cli.py`
- `/Users/brighthome/Desktop/RADSIM/radsim/config.py`
