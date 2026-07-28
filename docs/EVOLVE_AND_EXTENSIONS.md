# Evolve and extensions

RadSim's evolution features are local, bounded, and user-controlled. Learning
can recommend an action, but it cannot bypass tool policy, confirmation,
hooks, path validation, command validation, or undo checkpoints.

The proposal engine and self-extension are off by default.

## `/evolve` commands

| Command | Behavior |
| --- | --- |
| `/evolve` | Open the menu and show current toggle states. |
| `/evolve status` | Show learning, proposal, automatic proposal, extension, pending, and analysis status. |
| `/evolve on` or `off` | Toggle the existing `self_improvement.enabled` setting. |
| `/evolve auto on` or `off` | Toggle automatic proposal generation. |
| `/evolve learning on` or `off` | Toggle event collection without deleting existing data. |
| `/evolve extensions on` or `off` | Toggle extension execution after a typed warning. |
| `/evolve settings` | Configure the proposal engine and individual learning modules. |
| `/evolve analyze` | Analyze verified outcomes and create reviewable proposals. |
| `/evolve review` | Approve, reject, or skip pending proposals. |
| `/evolve history` | Inspect resolved proposals. |
| `/evolve stats` | Inspect proposal statistics. |

Turning the proposal engine off retains learning records, proposal history,
extension files, and the automatic proposal preference. Turning learning off
does not alter trust-bandit data.

## Verified learning

Every completed task uses one outcome:

- `unknown`
- `successful`
- `partially_successful`
- `failed`
- `cancelled`
- `user_rejected`
- `reverted`

Returning model text is not success evidence. Successful tool calls and
verification tools provide evidence. Failed tests, lint, or type checks produce
a failed or partially successful outcome. Interruptions, rejected
confirmations, and undo actions remain distinct.

Tool, task, feedback, proposal, and extension lifecycle events use the bounded
SQLite store at `~/.radsim/learning/learning_events.sqlite3`. Existing learning
JSON files are imported once, backed up under
`~/.radsim/learning/legacy_backup_v1/`, and recorded in `migration_v1.json`.
The migration is idempotent.

Retrieval uses one local TF-IDF scorer. It makes no network call and ranks text
relevance together with verified outcome, recency, user decisions, task
category, tool, and error context.

## Extension locations

Global extensions:

```text
~/.radsim/extensions/<extension_id>/
    manifest.json
    extension.py
```

Project extensions:

```text
.radsim/extensions/<extension_id>/
    manifest.json
    extension.py
```

Global files require approval of an exact fingerprint covering every file and
relative path in the extension directory. Project files do not execute until
the exact project and its current extension versions are trusted:

```text
/evolve extensions list
/evolve extensions approve <extension-id>
/evolve extensions trust-project
/evolve extensions load <extension-id>
```

Any file, source, manifest, or permission change changes the fingerprint and
requires another approval. Symlinks, bytecode caches, non-regular files, more
than 100 files, and extension trees larger than 2 MiB are rejected.

## Manifest v1

```json
{
  "id": "targeted-tests",
  "name": "Targeted Tests",
  "version": "1.0.0",
  "entrypoint": "extension.py",
  "permissions": [
    "tools.register",
    "commands.register",
    "hooks.observe",
    "storage.read_write"
  ]
}
```

Supported permissions:

| Permission | Allows |
| --- | --- |
| `tools.register` | Register tools with a required permission tier. |
| `commands.register` | Register slash commands. |
| `hooks.observe` | Register non-blocking post-event observers. |
| `storage.read_write` | Use bounded storage for this extension ID. |

Unknown permissions, invalid semantic versions, duplicate IDs, path traversal,
missing entrypoints, and symlink escapes block loading before Python is
imported.

## API v1

An entrypoint exposes one function:

```python
def setup(api):
    api.register_tool(definition, execute, permission_tier="read_only")
    api.register_command("targeted-tests", handler, "Show a test hint")
    api.on("post_tool", observer)
```

Available methods:

```python
api.register_tool(definition, execute, permission_tier)
api.register_command(name, handler, description, accepts_args=False)
api.on(event_name, handler)
api.get_extension_storage()
api.set_extension_tool_active(name, enabled)
```

Permission tiers are `read_only`, `mutation`, and `generated_code`. Mutation
and generated-code tools require explicit confirmation. Tool inputs use the
existing schema, path, protected-file, symlink, and command validation. Calls
still pass through pre and post hooks and dynamic undo checkpoints.

Path and command validation is applied to inputs named by convention (`path`,
`file`, `directory`, `*_path`, `*_file`, `*_dir`, `command`, `*_command`). An
input that holds a path or a command under any other name, such as `filename`
or `cmd`, is only validated when the tool declares it:

```python
definition = {
    "name": "rewrite_report",
    "description": "Rewrite one generated report file.",
    "input_schema": {
        "type": "object",
        "properties": {"filename": {"type": "string"}},
        "required": ["filename"],
    },
    "input_roles": {"path": ["filename"]},
}
```

`input_roles` accepts `path` and `command`, each listing declared property
names. It is stripped from the provider-facing schema and drives the same
validation and undo checkpoints as the conventional names. Declaring roles is
required for undeclared names because RadSim cannot infer intent from an
arbitrary parameter name.

Extensions cannot replace built-in registrations, toggle another extension's
tool, mutate registry dictionaries through the API, or use observe hooks to
approve a blocked action. Observer contexts are deep snapshots, so nested edits
cannot change live tool or lifecycle state.

An approved Python extension is trusted local code, not a sandboxed plugin.
Its setup function runs with the user's operating-system permissions. The tool
tier controls RadSim's invocation policy, but it cannot constrain malicious
Python inside an extension. Review the complete fingerprinted directory before
approval.

## Reload, unload, and rollback

```text
/evolve extensions reload <extension-id>
/evolve extensions unload <extension-id>
/evolve extensions rollback <extension-id>
```

Reload prepares and validates a complete replacement before removing the
working registrations. A failed reload leaves the last working version active.
Unload removes only registrations owned by that extension. An approved staged
upgrade keeps the prior files as a rollback version, and rollback atomically
swaps the versions.

## Generated extension proposals

`/evolve analyze` can stage an extension only when repeated successful events
provide evidence and self-extension is enabled. Analysis writes a manifest,
source, tests, and explanation under `~/.radsim/extension_staging/`; it does
not import or activate them.

Review shows the proposal and requires typing `activate`. After that approval
RadSim compiles the source, runs any generated `test_extension.py` in an
isolated subprocess, then imports the entrypoint in the RadSim process to
confirm `setup(api)` registers cleanly before installing atomically and
loading. The entrypoint import is not sandboxed: typing `activate` is the point
at which generated Python gains the right to run with your permissions.

Activation installs into the global extension directory and approves that exact
fingerprint, so the extension loads automatically at the start of every later
session, including non-interactive `-p` runs, until it is unloaded or
extensions are turned off.

Rejection removes only the staged candidate, and analysis discards the staged
files for any candidate it does not keep. RadSim core source is never modified
by this proposal type. Generated files, proposal history, canonical events, and
extension storage all have explicit size or record bounds.

## Sample

The repository includes
[`examples/extensions/targeted-tests`](../examples/extensions/targeted-tests).
Copy that directory into the global extension directory, enable extensions,
approve its exact version, and load it.
