"""Trusted discovery and transactional lifecycle for RadSim Python extensions."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extension_api import ExtensionAPI
from .persistence import atomic_write_json

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 32 * 1024
MAX_EXTENSION_SOURCE_BYTES = 512 * 1024
MAX_EXTENSION_TOTAL_BYTES = 2 * 1024 * 1024
MAX_EXTENSION_FILES = 100
EXTENSION_TEST_TIMEOUT_SECONDS = 15
ALLOWED_PERMISSIONS = frozenset(
    {
        "tools.register",
        "commands.register",
        "hooks.observe",
        "storage.read_write",
    }
)
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _record_extension_event(
    extension_id: str,
    action: str,
    outcome: str,
    *,
    scope: str = "",
    error: str = "",
) -> None:
    """Record bounded lifecycle evidence when learning collection is enabled."""
    try:
        from .agent_config import get_agent_config_manager
        from .learning import LearningEvent, get_learning_store
        from .learning.events import stable_identifier

        if not get_agent_config_manager().get("learning.enabled", True):
            return
        get_learning_store().append(
            LearningEvent.create(
                event_type="extension_lifecycle",
                action_signature=stable_identifier(extension_id, action),
                outcome=outcome,
                error_type="extension_error" if error else None,
                error_message=error,
                summary=f"{action} extension {extension_id}",
                metadata={"extension_id": extension_id, "action": action, "scope": scope},
            )
        )
    except Exception:
        logger.debug("Could not record extension lifecycle event", exc_info=True)


@dataclass(frozen=True)
class ExtensionManifest:
    """Validated, non-executable extension metadata."""

    extension_id: str
    name: str
    version: str
    entrypoint: str
    permissions: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionCandidate:
    """One validated extension directory found at a known scope."""

    manifest: ExtensionManifest
    directory: Path
    scope: str
    fingerprint: str


@dataclass
class LoadedExtension:
    """The last known working registrations for a loaded extension."""

    candidate: ExtensionCandidate
    api: ExtensionAPI
    module_name: str


def validate_manifest_data(data: dict[str, Any]) -> ExtensionManifest:
    """Validate manifest values without importing the entrypoint."""
    if not isinstance(data, dict):
        raise ValueError("manifest.json must contain an object")
    extension_id = data.get("id")
    if not isinstance(extension_id, str) or not _ID_PATTERN.fullmatch(extension_id):
        raise ValueError(
            "Manifest id must use 3-64 lowercase letters, digits, or hyphens"
        )
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("Manifest name must contain 1-100 characters")
    version = data.get("version")
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise ValueError("Manifest version must be valid semantic versioning")
    entrypoint = data.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint.endswith(".py"):
        raise ValueError("Manifest entrypoint must be a Python file")
    entrypoint_path = Path(entrypoint)
    if entrypoint_path.is_absolute() or ".." in entrypoint_path.parts:
        raise ValueError("Manifest entrypoint must stay inside the extension directory")
    permissions = data.get("permissions", [])
    if not isinstance(permissions, list) or any(
        not isinstance(permission, str) for permission in permissions
    ):
        raise ValueError("Manifest permissions must be a list of names")
    unknown = sorted(set(permissions) - ALLOWED_PERMISSIONS)
    if unknown:
        raise ValueError(f"Unknown extension permission(s): {', '.join(unknown)}")
    if len(set(permissions)) != len(permissions):
        raise ValueError("Manifest permissions cannot contain duplicates")
    return ExtensionManifest(
        extension_id=extension_id,
        name=name.strip(),
        version=version,
        entrypoint=entrypoint,
        permissions=tuple(permissions),
    )


def _contained_path(directory: Path, relative_path: str) -> Path:
    root = directory.resolve()
    target = (directory / relative_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Extension entrypoint escapes its extension directory")
    if not target.is_file():
        raise ValueError(f"Extension entrypoint does not exist: {relative_path}")
    if target.stat().st_size > MAX_EXTENSION_SOURCE_BYTES:
        raise ValueError("Extension entrypoint exceeds the source size limit")
    return target


def _extension_files(directory: Path) -> list[Path]:
    """Return every approved extension file, rejecting links and caches."""
    files = []
    total_bytes = 0
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(directory)
        if path.is_symlink():
            raise ValueError(f"Extension files cannot be symlinks: {relative}")
        if path.is_dir():
            if path.name == "__pycache__":
                raise ValueError("Extension directories cannot contain __pycache__")
            continue
        if not path.is_file():
            raise ValueError(f"Extension contains a non-regular file: {relative}")
        if path.suffix in {".pyc", ".pyo"}:
            raise ValueError(f"Extension bytecode is not allowed: {relative}")
        size = path.stat().st_size
        if size > MAX_EXTENSION_SOURCE_BYTES:
            raise ValueError(f"Extension file exceeds the size limit: {relative}")
        total_bytes += size
        if total_bytes > MAX_EXTENSION_TOTAL_BYTES:
            raise ValueError("Extension exceeds the total size limit")
        files.append(path)
        if len(files) > MAX_EXTENSION_FILES:
            raise ValueError(f"Extension is limited to {MAX_EXTENSION_FILES} files")
    return files


def _fingerprint_directory(directory: Path) -> str:
    """Hash paths and bytes for the complete executable extension tree."""
    digest = hashlib.sha256()
    for path in _extension_files(directory):
        relative = path.relative_to(directory).as_posix()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative.encode("utf-8"))
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_candidate(directory: Path, scope: str) -> ExtensionCandidate:
    if directory.is_symlink():
        raise ValueError("Extension directory cannot be a symlink")
    directory = directory.resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("Missing manifest.json")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest.json exceeds the size limit")
    try:
        manifest_data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid manifest JSON: {error}") from error
    manifest = validate_manifest_data(manifest_data)
    if directory.name != manifest.extension_id:
        raise ValueError("Extension directory name must match manifest id")
    _contained_path(directory, manifest.entrypoint)
    return ExtensionCandidate(
        manifest=manifest,
        directory=directory,
        scope=scope,
        fingerprint=_fingerprint_directory(directory),
    )


class ExtensionLoader:
    """Discover approved extensions and preserve working registrations on reload."""

    def __init__(
        self,
        command_registry=None,
        *,
        global_root: Path | None = None,
        project_root: Path | None = None,
        state_file: Path | None = None,
    ):
        self.command_registry = command_registry
        self.global_root = Path(global_root or Path.home() / ".radsim" / "extensions")
        self.project_root = Path(project_root or Path.cwd() / ".radsim" / "extensions")
        self.state_file = Path(
            state_file or Path.home() / ".radsim" / "extension_approvals.json"
        )
        self.staging_root = self.global_root.parent / "extension_staging"
        self.backup_root = self.global_root.parent / "extension_backups"
        self.loaded: dict[str, LoadedExtension] = {}

    def set_command_registry(self, command_registry) -> None:
        if command_registry is not None:
            self.command_registry = command_registry

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.is_file():
            return {"schema_version": 1, "projects": {}, "extensions": {}}
        try:
            state = json.loads(self.state_file.read_text())
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "projects": {}, "extensions": {}}
        if not isinstance(state, dict):
            return {"schema_version": 1, "projects": {}, "extensions": {}}
        state.setdefault("projects", {})
        state.setdefault("extensions", {})
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_file, state, secure=True)

    @staticmethod
    def _project_key(path: Path) -> str:
        return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]

    def _approval_key(self, candidate: ExtensionCandidate) -> str:
        if candidate.scope == "project":
            project_key = self._project_key(self.project_root.parent.parent)
            return f"project:{project_key}:{candidate.manifest.extension_id}"
        return f"global:{candidate.manifest.extension_id}"

    def _is_project_trusted(self, state=None) -> bool:
        state = state or self._load_state()
        project = self.project_root.parent.parent.resolve()
        record = state["projects"].get(self._project_key(project), {})
        return record.get("path") == str(project)

    def _is_approved(self, candidate: ExtensionCandidate, state=None) -> bool:
        state = state or self._load_state()
        if candidate.scope == "project" and not self._is_project_trusted(state):
            return False
        record = state["extensions"].get(self._approval_key(candidate), {})
        return record.get("fingerprint") == candidate.fingerprint

    def discover(self) -> list[ExtensionCandidate]:
        """Discover and validate manifests without importing executable code."""
        candidates = []
        for scope, root in (("global", self.global_root), ("project", self.project_root)):
            if not root.is_dir() or root.is_symlink():
                continue
            resolved_root = root.resolve()
            for directory in sorted(root.iterdir(), key=lambda path: path.name):
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                resolved_directory = directory.resolve()
                if directory.is_symlink() or resolved_root not in resolved_directory.parents:
                    logger.warning(
                        "Extension directory rejected [%s/%s]: symlink escape",
                        scope,
                        directory.name,
                    )
                    continue
                try:
                    candidates.append(_read_candidate(directory, scope))
                except ValueError as error:
                    logger.warning(
                        "Extension manifest rejected [%s/%s]: %s",
                        scope,
                        directory.name,
                        error,
                    )
        return candidates

    def _candidate(self, extension_id: str) -> ExtensionCandidate:
        matches = [
            candidate
            for candidate in self.discover()
            if candidate.manifest.extension_id == extension_id
        ]
        if not matches:
            raise ValueError(f"Extension not found: {extension_id}")
        if len(matches) > 1:
            scopes = ", ".join(sorted(candidate.scope for candidate in matches))
            raise ValueError(f"Duplicate extension id '{extension_id}' in: {scopes}")
        return matches[0]

    def trust_project(self) -> dict[str, Any]:
        """Trust this exact project and approve its current extension fingerprints."""
        state = self._load_state()
        project = self.project_root.parent.parent.resolve()
        project_key = self._project_key(project)
        state["projects"][project_key] = {
            "path": str(project),
            "trusted_at": datetime.now(timezone.utc).isoformat(),
        }
        approved = []
        for candidate in self.discover():
            if candidate.scope != "project":
                continue
            state["extensions"][self._approval_key(candidate)] = {
                "fingerprint": candidate.fingerprint,
                "permissions": list(candidate.manifest.permissions),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            approved.append(candidate.manifest.extension_id)
        self._save_state(state)
        return {
            "success": True,
            "message": f"Trusted project and approved {len(approved)} current extension(s).",
            "approved": approved,
        }

    def approve(self, extension_id: str) -> dict[str, Any]:
        """Approve one current manifest and source fingerprint."""
        try:
            candidate = self._candidate(extension_id)
        except ValueError as error:
            return {"success": False, "error": str(error)}
        state = self._load_state()
        if candidate.scope == "project" and not self._is_project_trusted(state):
            return {
                "success": False,
                "error": "Project extensions require explicit project trust first",
            }
        state["extensions"][self._approval_key(candidate)] = {
            "fingerprint": candidate.fingerprint,
            "permissions": list(candidate.manifest.permissions),
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state(state)
        return {
            "success": True,
            "message": f"Approved extension {extension_id} {candidate.manifest.version}.",
        }

    def _prepare(self, candidate: ExtensionCandidate, *, replacing_owner=None):
        current = _read_candidate(candidate.directory, candidate.scope)
        if current.fingerprint != candidate.fingerprint:
            raise ValueError("Extension changed while it was being prepared")
        entrypoint = _contained_path(candidate.directory, candidate.manifest.entrypoint)
        module_name = (
            f"_radsim_extension_{candidate.manifest.extension_id.replace('-', '_')}_"
            f"{candidate.fingerprint[:12]}"
        )
        module = types.ModuleType(module_name)
        module.__file__ = str(entrypoint)
        module.__package__ = ""
        sys.modules[module_name] = module
        try:
            source = entrypoint.read_bytes()
            exec(compile(source, str(entrypoint), "exec"), module.__dict__)
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise ValueError("Extension entrypoint must define setup(api)")
            api = ExtensionAPI(
                candidate.manifest.extension_id,
                candidate.manifest.permissions,
                self.command_registry,
            )
            setup(api)
            api.preflight(replacing_owner=replacing_owner)
            return api, module_name
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    def _extensions_enabled(self) -> bool:
        from .agent_config import get_agent_config_manager

        return bool(get_agent_config_manager().get("tools.self_extension", False))

    def load(self, extension_id: str) -> dict[str, Any]:
        """Load one approved extension."""
        if not self._extensions_enabled():
            return {"success": False, "error": "Self-extension is disabled"}
        if extension_id in self.loaded:
            return {"success": True, "message": f"Extension {extension_id} is already loaded."}
        try:
            candidate = self._candidate(extension_id)
            if not self._is_approved(candidate):
                return {
                    "success": False,
                    "error": "Extension approval is missing or changed",
                }
            api, module_name = self._prepare(candidate)
            api.activate()
        except Exception as error:
            logger.warning("Extension load failed [%s]: %s", extension_id, error)
            _record_extension_event(extension_id, "load", "failed", error=str(error))
            return {"success": False, "error": f"Extension load failed: {error}"}
        self.loaded[extension_id] = LoadedExtension(candidate, api, module_name)
        logger.info(
            "Extension loaded: id=%s scope=%s version=%s",
            extension_id,
            candidate.scope,
            candidate.manifest.version,
        )
        _record_extension_event(
            extension_id,
            "load",
            "successful",
            scope=candidate.scope,
        )
        return {"success": True, "message": f"Loaded extension {extension_id}."}

    def load_approved(self) -> list[dict[str, Any]]:
        """Load only uniquely identified, approved extensions."""
        if not self._extensions_enabled():
            return []
        candidates = self.discover()
        counts: dict[str, int] = {}
        for candidate in candidates:
            extension_id = candidate.manifest.extension_id
            counts[extension_id] = counts.get(extension_id, 0) + 1
        results = []
        for candidate in candidates:
            extension_id = candidate.manifest.extension_id
            if counts[extension_id] > 1 or not self._is_approved(candidate):
                continue
            results.append(self.load(extension_id))
        return results

    def reload(self, extension_id: str) -> dict[str, Any]:
        """Prepare first, then replace registrations while preserving fallback."""
        if not self._extensions_enabled():
            return {"success": False, "error": "Self-extension is disabled"}
        current = self.loaded.get(extension_id)
        if current is None:
            return self.load(extension_id)
        try:
            candidate = self._candidate(extension_id)
            if not self._is_approved(candidate):
                return {
                    "success": False,
                    "error": "Updated extension requires another approval",
                }
            if candidate.fingerprint == current.candidate.fingerprint:
                return {
                    "success": True,
                    "message": f"Extension {extension_id} is already current.",
                }
            candidate_api, module_name = self._prepare(
                candidate,
                replacing_owner=current.api.owner,
            )
        except Exception as error:
            _record_extension_event(extension_id, "reload", "failed", error=str(error))
            return {
                "success": False,
                "error": f"Reload validation failed; previous version remains active: {error}",
            }

        current.api.deactivate()
        try:
            candidate_api.activate()
        except Exception as error:
            sys.modules.pop(module_name, None)
            try:
                current.api.activate()
            except Exception:
                logger.exception("Could not restore working extension %s", extension_id)
            _record_extension_event(extension_id, "reload", "failed", error=str(error))
            return {
                "success": False,
                "error": f"Reload failed; previous version restored: {error}",
            }

        sys.modules.pop(current.module_name, None)
        self.loaded[extension_id] = LoadedExtension(candidate, candidate_api, module_name)
        logger.info("Extension reloaded: id=%s version=%s", extension_id, candidate.manifest.version)
        _record_extension_event(
            extension_id,
            "reload",
            "successful",
            scope=candidate.scope,
        )
        return {"success": True, "message": f"Reloaded extension {extension_id}."}

    def unload(self, extension_id: str) -> dict[str, Any]:
        """Unload only extension-owned registrations."""
        current = self.loaded.pop(extension_id, None)
        if current is None:
            return {"success": False, "error": f"Extension is not loaded: {extension_id}"}
        current.api.deactivate()
        sys.modules.pop(current.module_name, None)
        logger.info("Extension unloaded: id=%s", extension_id)
        _record_extension_event(
            extension_id,
            "unload",
            "successful",
            scope=current.candidate.scope,
        )
        return {"success": True, "message": f"Unloaded extension {extension_id}."}

    def _run_staged_tests(self, staging_dir: Path) -> None:
        test_file = staging_dir / "test_extension.py"
        if not test_file.exists():
            return
        if test_file.is_symlink() or staging_dir.resolve() not in test_file.resolve().parents:
            raise ValueError("Generated extension tests must stay inside staging")
        if not test_file.is_file() or not test_file.read_text().strip():
            return
        if test_file.stat().st_size > MAX_EXTENSION_SOURCE_BYTES:
            raise ValueError("Generated extension tests exceed the size limit")
        script = (
            "import runpy,sys;"
            "sys.path.insert(0,sys.argv[1]);"
            "runpy.run_path(sys.argv[2],run_name='__main__')"
        )
        from .tools.environment import build_child_environment

        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                script,
                str(staging_dir),
                str(test_file),
            ],
            cwd=staging_dir,
            env=build_child_environment(),
            text=True,
            capture_output=True,
            timeout=EXTENSION_TEST_TIMEOUT_SECONDS,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "unknown failure")[-1_000:]
            raise ValueError(f"Generated extension tests failed: {detail}")

    def _validate_staging_path(self, staging_dir: Path) -> Path:
        if staging_dir.is_symlink():
            raise ValueError("Staged extension directory cannot be a symlink")
        root = self.staging_root.resolve()
        staging = staging_dir.resolve()
        if root not in staging.parents:
            raise ValueError("Staged extension path is outside the staging directory")
        if not staging.is_dir():
            raise ValueError("Staged extension directory does not exist")
        return staging

    def install_staged_extension(self, staging_dir: Path) -> dict[str, Any]:
        """Validate after explicit approval, install atomically, then activate."""
        if not self._extensions_enabled():
            return {"success": False, "error": "Self-extension is disabled"}
        destination = None
        backup = None
        temporary = None
        installed_new = False
        was_loaded = False
        try:
            staging = self._validate_staging_path(Path(staging_dir))
            manifest_data = json.loads((staging / "manifest.json").read_text())
            manifest = validate_manifest_data(manifest_data)
            candidate_dir = staging
            if staging.name != manifest.extension_id:
                candidate_dir = staging / manifest.extension_id
                candidate_dir.mkdir(exist_ok=False)
                for name in (
                    "manifest.json",
                    manifest.entrypoint,
                    "test_extension.py",
                    "EXPLANATION.md",
                ):
                    source = staging / name
                    if source.is_file():
                        target = candidate_dir / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
            staged_candidate = _read_candidate(candidate_dir, "global")
            compile(
                _contained_path(candidate_dir, manifest.entrypoint).read_text(),
                manifest.entrypoint,
                "exec",
            )
            self._run_staged_tests(candidate_dir)
            prepared_api, prepared_module = self._prepare(
                staged_candidate,
                replacing_owner=f"extension:{manifest.extension_id}",
            )
            prepared_api.deactivate()
            sys.modules.pop(prepared_module, None)

            self.global_root.mkdir(parents=True, exist_ok=True)
            destination = self.global_root / manifest.extension_id
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{manifest.extension_id}-", dir=self.global_root)
            )
            shutil.rmtree(temporary)
            shutil.copytree(candidate_dir, temporary)
            was_loaded = manifest.extension_id in self.loaded
            if destination.exists():
                self.backup_root.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                backup = self.backup_root / f"{manifest.extension_id}-{stamp}"
                os.replace(destination, backup)
            os.replace(temporary, destination)
            installed_new = True

            installed = _read_candidate(destination, "global")
            self._approve_candidate(installed)
            result = (
                self.reload(manifest.extension_id)
                if was_loaded
                else self.load(manifest.extension_id)
            )
            if not result.get("success"):
                raise RuntimeError(result.get("error", "activation failed"))
            shutil.rmtree(staging)
            logger.info(
                "Staged extension activated: id=%s version=%s",
                manifest.extension_id,
                manifest.version,
            )
            _record_extension_event(
                manifest.extension_id,
                "activate",
                "successful",
                scope="global",
            )
            return {
                "success": True,
                "message": f"Validated and activated extension {manifest.extension_id}.",
            }
        except Exception as error:
            if installed_new and destination is not None and destination.exists() and backup is not None:
                failed = destination.with_name(f".{destination.name}-failed")
                os.replace(destination, failed)
                os.replace(backup, destination)
                shutil.rmtree(failed, ignore_errors=True)
                if was_loaded:
                    self._approve_candidate(_read_candidate(destination, "global"))
                    self.reload(destination.name)
            elif installed_new and destination is not None and destination.exists():
                if destination.name in self.loaded:
                    self.unload(destination.name)
                shutil.rmtree(destination, ignore_errors=True)
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
            failed_id = destination.name if destination is not None else "unknown"
            _record_extension_event(failed_id, "activate", "failed", error=str(error))
            return {"success": False, "error": f"Extension activation failed: {error}"}

    def _approve_candidate(self, candidate: ExtensionCandidate) -> None:
        state = self._load_state()
        state["extensions"][self._approval_key(candidate)] = {
            "fingerprint": candidate.fingerprint,
            "permissions": list(candidate.manifest.permissions),
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state(state)

    def rollback(self, extension_id: str) -> dict[str, Any]:
        """Atomically swap the active files with the newest backup."""
        if not self._extensions_enabled():
            return {"success": False, "error": "Self-extension is disabled"}
        backups = sorted(self.backup_root.glob(f"{extension_id}-*"), reverse=True)
        destination = self.global_root / extension_id
        if not backups or not destination.is_dir():
            return {"success": False, "error": f"No rollback version for {extension_id}"}
        backup = backups[0]
        temporary = self.global_root / f".{extension_id}-rollback"
        try:
            if temporary.exists():
                shutil.rmtree(temporary)
            os.replace(destination, temporary)
            os.replace(backup, destination)
            candidate = _read_candidate(destination, "global")
            self._approve_candidate(candidate)
            result = self.reload(extension_id)
            if not result.get("success"):
                raise RuntimeError(result.get("error", "reload failed"))
            os.replace(temporary, backup)
            _record_extension_event(
                extension_id,
                "rollback",
                "reverted",
                scope="global",
            )
            return {"success": True, "message": f"Rolled back extension {extension_id}."}
        except Exception as error:
            if destination.exists() and temporary.exists():
                os.replace(destination, backup)
                os.replace(temporary, destination)
            _record_extension_event(extension_id, "rollback", "failed", error=str(error))
            return {"success": False, "error": f"Extension rollback failed: {error}"}

    def status(self) -> list[dict[str, str]]:
        """Report scope and approval state without importing code."""
        state = self._load_state()
        enabled = self._extensions_enabled()
        records = []
        counts: dict[str, int] = {}
        candidates = self.discover()
        for candidate in candidates:
            extension_id = candidate.manifest.extension_id
            counts[extension_id] = counts.get(extension_id, 0) + 1
        for candidate in candidates:
            extension_id = candidate.manifest.extension_id
            if counts[extension_id] > 1:
                status = "duplicate-id"
            elif extension_id in self.loaded:
                status = "loaded"
            elif not enabled:
                status = "disabled"
            elif candidate.scope == "project" and not self._is_project_trusted(state):
                status = "project-untrusted"
            elif not self._is_approved(candidate, state):
                status = "approval-required"
            else:
                status = "approved"
            records.append(
                {
                    "id": extension_id,
                    "name": candidate.manifest.name,
                    "version": candidate.manifest.version,
                    "scope": candidate.scope,
                    "status": status,
                }
            )
        return records


_extension_loader: ExtensionLoader | None = None


def get_extension_loader(command_registry=None) -> ExtensionLoader:
    """Return the process loader and attach the interactive registry when known."""
    global _extension_loader
    if _extension_loader is None:
        _extension_loader = ExtensionLoader(command_registry)
    else:
        _extension_loader.set_command_registry(command_registry)
    return _extension_loader
