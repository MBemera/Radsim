# Classifier branch review

Reviewed by Codex, 2026-09-09 AEST.

Fix status (2026-09-09, Codex): all four findings implemented locally. Bracket
expressions require approval, ordinary filenames retain `::`, Git revision/path
syntax requires approval, and only options before `--` establish read-only mode.
Git content diffs (including `--check`) now prompt; summary diffs remain automatic.
The shared option check also fixes the analogous `rg --files` ambiguity. Custom
test paths are classified in the final command, using pytest node-ID semantics
only for pytest. Unsupported tool fields cannot change the classification context.

Verification: 24 handler-denial regressions fail against the original classifier;
403 safety tests pass with the fixes. Final full suite: 2414 passed in 117.40s.
Repository Ruff lint, changed-file formatting and diff secret scanning passed.
The original findings and line numbers below refer to the reviewed commit.

Commit: `26c31d7d01e89a76bfdb39d86b9d67f1dd691d2b` (`origin/classifier`).
Scope: the seven-file classifier change relative to parent `e5f4f46`.
The parent tree is identical to fetched `origin/main`; no unrelated historical changes were reviewed.

Original recommendation: fix the following approval bypasses before merging. All four were
reproduced by calling the real classifier and shell executor with synthetic local
fixtures. No credentials, provider calls or network operations were used in the reproductions.

1. **[P1] Reject bracket globs before approving literal paths** —
   `radsim/request_classifier.py:85`.
   The expansion filter rejects `*` and `?` but omits bracket expressions. With a
   harmless literal file named `.en[v]` and a synthetic `.env` in the project,
   `cat .en[v]` is allowed: validation checks the harmless literal file, while Bash
   expands the argument to `.env`. The shell returns the protected file contents
   without a prompt. Reject active bracket glob syntax or execute validated literal
   argv without shell expansion. Include a regression with both files present.

2. **[P1] Resolve the full path for non-pytest arguments** —
   `radsim/request_classifier.py:139`.
   `_project_argument` strips everything after `::` for every command. A legal
   POSIX symlink named `alias::file` pointing to `.env` therefore passes
   `cat alias::file`: the secret check resolves `alias`, while `is_file` and Bash
   follow the actual symlink. The reproduction returned the synthetic protected
   content. Apply pytest node-ID parsing only to pytest targets; resolve the exact
   executed filename for ordinary commands.

3. **[P1] Validate Git object paths as Git paths** —
   `radsim/request_classifier.py:120`.
   Git diff operands are checked as filesystem paths. With a synthetic committed
   `credentials.json`, `git diff HEAD:credentials.json HEAD:sample.py` is allowed
   and prints the protected blob. The secret matcher sees the basename
   `HEAD:credentials.json`, which does not match `credentials.json`. Git interprets
   the operand as a revision plus repository path instead. Require approval for
   unsupported revision/path syntax or parse it before applying secret checks.
   Also consider unrestricted diff output when designing the fix: checking only
   explicit operands does not screen all files shown by Git.

4. **[P2] Require Ruff check/diff options before the option terminator** —
   `radsim/request_classifier.py:96`.
   The formatter guard searches all arguments for `--check` or `--diff`, including
   filenames after `--`. `ruff format -- --check sample.py` is allowed and actually
   reformats `sample.py` (and the fixture file named `--check`). Parse option
   semantics before deciding that formatting is read-only. Flags after `--` must
   not satisfy this guard.

Validation:

- Focused classifier/agent safety suite: 90 passed.
- Expanded safety suite: 360 passed in 8.12s. Test list is in `uptodate.md`.
- Ruff lint on all changed Python files: passed. `git diff --check HEAD^ HEAD`: passed.
- Formatter check: new classifier and new tests need formatting. The handler also
  needs formatting, but its parent version already fails that check.
- Dependencies unchanged; no dependency installation or audit performed.
- Full suite, Windows runtime, live providers and installed CLI: not verified in this review.
- Standards check: approval and protected-read controls fail the scoped OWASP
  access-control/input-validation and RadSim security expectations above. Code
  uses a small local classifier with no new dependencies; no standards certification
  is claimed. Reproduction data is synthetic. No new runtime exposure or auth changes.

Evidence: `/tmp/radsim-classifier-review-evidence/reproduce.py`,
`reproduction-results.jsonl`, `pytest.txt`. Reproduction creates its own temporary
project and synthetic HOME; run with this checkout on PYTHONPATH and the interpreter
recorded in `uptodate.md`. Successful reproduction is evidence of the defects,
not a passing security regression test.

No installation, pushes, PR comments or merges performed. Fixes are included in the local commit containing this report.
