# RadSim Feature Roadmap: /plan, /panning & Auto-Update

**Version Target:** v1.2.0
**Based on:** RadSim SWOT Analysis (27 Feb 2026)
**Priority:** HIGH (addresses #1 developer demand from feedback report)

---

## Current State (v1.1.0)

| Feature | Status | Notes |
|---------|--------|-------|
| `/plan` command | Missing | Only a basic `plan_task` tool exists in `tools/project.py` |
| `/panning` command | Missing | No brain-dump processing anywhere |
| Auto-update check | Missing | Version hardcoded in `__init__.py` and `pyproject.toml`, no update notifications |
| Command registry | 31 commands | Pattern established in `commands.py` lines 83-162 |

---

## Feature 1: `/plan` Command

### What It Does
Structured plan-confirm-execute workflow. The agent generates an implementation plan, the human reviews and approves it, then the agent executes step-by-step with checkpoint confirmations.

### Why (from SWOT)
> "The single most requested feature across ALL agents" - Developer Feedback Report Section 6.1

### Command Interface

```
/plan <description>     Start a new plan from a task description
/plan show              Show the current active plan
/plan approve           Approve the current plan for execution
/plan reject            Reject and discard the current plan
/plan step              Execute the next step in an approved plan
/plan run               Execute all remaining steps (with confirmations)
/plan status            Show progress on active plan
/plan history           Show past plans
/plan export            Export current plan to markdown file
```

### Plan Structure

Each plan contains:
- **Title** - one-line summary
- **Goal** - what success looks like
- **Steps** - ordered list, each with:
  - Description of the change
  - Files affected
  - Risk level (low / medium / high)
  - Estimated scope (lines changed)
  - Checkpoint (pause for confirmation: yes / no)
- **Dependencies** - external requirements or blockers
- **Rollback** - how to undo if something goes wrong

### Implementation Files

| File | Change |
|------|--------|
| `radsim/commands.py` | Add `/plan` command registration and `_cmd_plan()` handler |
| `radsim/planner.py` | **NEW** - `PlanManager` class (plan creation, storage, execution) |
| `radsim/prompts.py` | Add planning system prompt for structured plan generation |
| `radsim/tools/project.py` | Upgrade existing `plan_task` tool to integrate with PlanManager |
| `plans/` directory | Local storage for plan JSON files (gitignored) |

### Workflow

```
User: /plan Add user authentication with JWT

RadSim generates:
┌─────────────────────────────────────────┐
│  PLAN: Add JWT Authentication           │
│  Goal: Secure API endpoints with JWT    │
│                                         │
│  Step 1: Install dependencies     [LOW] │
│    Files: pyproject.toml, requirements  │
│    Checkpoint: No                       │
│                                         │
│  Step 2: Create auth module      [MED]  │
│    Files: src/auth.py (NEW)             │
│    Checkpoint: Yes                      │
│                                         │
│  Step 3: Add login endpoint      [MED]  │
│    Files: src/routes.py                 │
│    Checkpoint: Yes                      │
│                                         │
│  Step 4: Protect existing routes [HIGH] │
│    Files: src/routes.py, src/middleware  │
│    Checkpoint: Yes                      │
│                                         │
│  Rollback: git revert to pre-plan      │
└─────────────────────────────────────────┘

Approve? [y/n/edit]:
```

### Risk Scoring

- **LOW**: New files, adding dependencies, documentation
- **MEDIUM**: Modifying existing files, adding new functions
- **HIGH**: Changing existing logic, modifying shared state, database changes

---

## Feature 2: `/panning` Command

### What It Does
Brain-dump processing mode. Users stream unstructured thoughts (voice transcripts, raw text, scattered notes) and RadSim parses them into structured, actionable output. Named after gold-panning: sifting raw material to find nuggets.

### Why (from SWOT)
> "No coding agent currently serves the pre-planning phase... /panning captures the moment before clarity exists and helps the developer get there."

### Command Interface

```
/panning                Start a panning session (interactive dump mode)
/panning <text>         Process a one-shot brain dump
/panning file <path>    Process a text/transcript file
/panning end            End interactive session and generate synthesis
/panning refine         Drill deeper into the last synthesis
/panning bridge         Convert panning output into a /plan
```

### Processing Pipeline

1. **Capture** - Accept raw, unstructured input. No formatting required. Rambling encouraged.
2. **Parse** - Identify distinct topics, extract concrete ideas, flag decisions and open questions, detect emotional signals (frustration, excitement, uncertainty).
3. **Synthesise** - Produce structured output:
   - Key themes identified
   - Actionable items extracted
   - Suggested priorities (based on emotional signals and repetition)
   - Hidden connections between ideas
   - Open questions that need resolving
4. **Iterate** - User reacts, dumps more thoughts, challenges the synthesis. Conversation refines.
5. **Bridge to /plan** - Once satisfied, `/panning bridge` feeds output directly into `/plan`.

### Output Format

```
┌─────────────────────────────────────────┐
│  PANNING SYNTHESIS                      │
│                                         │
│  THEMES:                                │
│  1. Authentication needs overhaul       │
│  2. Performance concerns on dashboard   │
│  3. Mobile responsiveness is a blocker  │
│                                         │
│  ACTION ITEMS:                          │
│  - [ ] Research JWT vs session auth     │
│  - [ ] Profile dashboard API calls      │
│  - [ ] Audit CSS breakpoints            │
│                                         │
│  PRIORITIES (by signal strength):       │
│  1. Mobile (mentioned 4x, frustration)  │
│  2. Auth (mentioned 3x, decision needed)│
│  3. Performance (mentioned 2x, curious) │
│                                         │
│  CONNECTIONS:                           │
│  - Auth + Mobile: login flow on mobile  │
│    may need separate consideration      │
│                                         │
│  OPEN QUESTIONS:                        │
│  - Who are the primary mobile users?    │
│  - Is there an existing auth system?    │
└─────────────────────────────────────────┘

Continue dumping? [y] | Refine? [r] | Bridge to /plan? [p]
```

### Implementation Files

| File | Change |
|------|--------|
| `radsim/commands.py` | Add `/panning` command registration and `_cmd_panning()` handler |
| `radsim/panning.py` | **NEW** - `PanningSession` class (capture, parse, synthesise, iterate) |
| `radsim/prompts.py` | Add panning system prompt for brain-dump analysis |
| `panning_sessions/` directory | Local storage for session history (gitignored) |

---

## Feature 3: Auto-Update Check

### What It Does
On startup, RadSim checks the latest release tag on GitHub against the installed version. If a newer release exists, displays a non-blocking notice. Respects offline usage by failing silently.

### Why (from SWOT)
> "Users who clone once have no way to know updates exist without manually checking GitHub."

### Behaviour

```
$ radsim
RadSim v1.1.0
Update available: v1.2.0 (run 'git pull && ./install.sh' to update)

Ready. Type /help for commands.
```

### Rules

- Check runs **once per session**, on startup only
- **Non-blocking**: if network fails, skip silently
- **Timeout**: 3-second max for the GitHub API call
- **Cache**: store last check timestamp, only check once per 24 hours
- **Opt-out**: `--skip-update-check` CLI flag or `RADSIM_SKIP_UPDATE_CHECK=1` env var
- **No auto-download**: only notifies, never modifies files

### Implementation Files

| File | Change |
|------|--------|
| `radsim/cli.py` | Add update check call during startup (after version display) |
| `radsim/update_checker.py` | **NEW** - `check_for_updates()` function |
| `radsim/__init__.py` | Version remains the source of truth |
| `.radsim_cache/` | Local cache file for last check timestamp (gitignored) |

### Update Check Logic

```python
def check_for_updates(current_version):
    """Check GitHub for newer RadSim version. Non-blocking, fail-silent."""
    cache_file = Path.home() / ".radsim_cache" / "update_check.json"

    # Skip if checked within last 24 hours
    if cache_is_fresh(cache_file, hours=24):
        return None

    try:
        response = requests.get(
            "https://api.github.com/repos/MBemera/Radsim/releases/latest",
            timeout=3
        )
        latest_version = response.json()["tag_name"].lstrip("v")

        save_cache(cache_file, latest_version)

        if version_is_newer(latest_version, current_version):
            return latest_version
    except Exception:
        return None  # Fail silently

    return None
```

---

## Version Control Plan

### Version Bump: v1.1.0 -> v1.2.0

| File | Line | Change |
|------|------|--------|
| `radsim/__init__.py` | 7 | `__version__ = "1.1.0"` -> `"1.2.0"` |
| `pyproject.toml` | 7 | `version = "1.1.0"` -> `"1.2.0"` |

### Git Strategy

1. Create feature branch: `feature/plan-panning-update`
2. Implement in order:
   - Auto-update checker (smallest, immediate value)
   - `/plan` command (highest demand)
   - `/panning` command (unique differentiator)
3. Each feature gets its own commit
4. PR back to `main` when all three are stable
5. Tag release `v1.2.0`

### New Files Created

```
radsim/
├── planner.py           # PlanManager class
├── panning.py           # PanningSession class
├── update_checker.py    # Auto-update check
tests/
├── test_planner.py      # Plan command tests
├── test_panning.py      # Panning command tests
├── test_update_checker.py # Update check tests
```

### Files Modified

```
radsim/
├── commands.py          # Register /plan and /panning commands
├── cli.py               # Add update check on startup, --skip-update-check flag
├── prompts.py           # Add planning and panning system prompts
├── __init__.py          # Version bump
pyproject.toml           # Version bump
.gitignore               # Add plans/, panning_sessions/, .radsim_cache/
```

---

## Execution Priority

| Order | Feature | Effort | Impact |
|-------|---------|--------|--------|
| 1 | Auto-update check | Small | Solves distribution problem immediately |
| 2 | `/plan` command | Medium | Addresses #1 developer demand |
| 3 | `/panning` command | Medium | Unique differentiator, no competitor has this |

---

## Success Criteria

- [ ] `/plan <description>` generates a structured, reviewable plan
- [ ] `/plan approve` + `/plan run` executes with checkpoint confirmations
- [ ] `/panning` accepts unstructured input and produces structured synthesis
- [ ] `/panning bridge` feeds into `/plan` seamlessly
- [ ] Auto-update check runs silently on startup, notifies when update available
- [ ] All three features have test coverage
- [ ] Version bumped to v1.2.0
- [ ] No breaking changes to existing commands or workflows
