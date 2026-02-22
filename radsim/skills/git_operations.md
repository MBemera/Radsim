# Git Operations Skills

Tools for Git version control in RadSim.

## Read-Only Tools (No confirmation needed)

### git_status
Get current repository status.

```python
git_status()
```

**Returns:**
```json
{
  "success": true,
  "branch": "main",
  "staged": ["src/new_file.py"],
  "modified": ["src/utils.py"],
  "untracked": ["temp.txt"],
  "clean": false
}
```

---

### git_diff
View changes (staged or unstaged).

```python
# Unstaged changes
git_diff()

# Staged changes
git_diff(staged=True)

# Specific file
git_diff(file_path="src/main.py")
```

**Parameters:**
- `staged` (optional): Show staged changes (default: False)
- `file_path` (optional): Diff specific file

---

### git_log
View commit history.

```python
# Recent commits
git_log(count=10)

# Commits for specific file
git_log(file_path="src/main.py", count=5)
```

**Parameters:**
- `count` (optional): Number of commits (default: 10)
- `file_path` (optional): Filter by file

**Returns:**
```json
{
  "success": true,
  "commits": [
    {
      "hash": "abc1234",
      "short_hash": "abc1234",
      "author": "User Name",
      "date": "2024-01-15",
      "message": "Add new feature"
    }
  ]
}
```

---

### git_branch
List branches.

```python
git_branch()
```

**Returns:**
```json
{
  "success": true,
  "current": "main",
  "branches": ["main", "feature/new-ui", "bugfix/login"]
}
```

## Write Tools (Require confirmation)

### git_add
Stage files for commit.

```python
# Stage specific files
git_add(file_paths=["src/main.py", "src/utils.py"])

# Stage all changes
git_add(all_files=True)
```

**Parameters:**
- `file_paths` (optional): List of files to stage
- `all_files` (optional): Stage all changes (default: False)

---

### git_commit
Create a commit.

```python
git_commit(message="Add user authentication feature")

# Amend last commit
git_commit(message="Updated message", amend=True)
```

**Parameters:**
- `message` (required): Commit message
- `amend` (optional): Amend last commit (default: False)

---

### git_checkout
Switch branches or restore files.

```python
# Switch branch
git_checkout(branch="feature/new-ui")

# Create and switch
git_checkout(branch="feature/new-ui", create=True)

# Restore file
git_checkout(file_path="src/main.py")
```

**Parameters:**
- `branch` (optional): Branch to switch to
- `create` (optional): Create branch if doesn't exist
- `file_path` (optional): Restore specific file

---

### git_stash
Stash or restore changes.

```python
# Stash current changes
git_stash(action="push")

# Restore stashed changes
git_stash(action="pop")

# List stashes
git_stash(action="list")
```

**Parameters:**
- `action` (required): "push", "pop", "list", or "drop"

## Best Practices

1. **Check status before commits** - Always run `git_status` before staging.

2. **Write good commit messages** - Start with verb, describe what changed.

3. **Stage specific files** - Avoid `all_files=True` to prevent accidental commits.

4. **Review diff before commit** - Use `git_diff(staged=True)` to verify changes.

## Common Patterns

### Standard commit workflow
```python
# 1. Check status
git_status()

# 2. Stage specific files
git_add(file_paths=["src/feature.py", "tests/test_feature.py"])

# 3. Review staged changes
git_diff(staged=True)

# 4. Commit
git_commit(message="Add user profile feature")
```

### Create feature branch
```python
# 1. Check current branch
git_branch()

# 2. Create and switch to new branch
git_checkout(branch="feature/user-auth", create=True)

# 3. Verify
git_status()
```

### Stash and restore
```python
# Save work in progress
git_stash(action="push")

# Do other work...
git_checkout(branch="main")

# Later, restore work
git_checkout(branch="feature/wip")
git_stash(action="pop")
```

## Destructive Commands

These require explicit confirmation:
- `git push` (via shell)
- `git reset`
- `git rebase`

Use `run_shell_command` for these operations.
