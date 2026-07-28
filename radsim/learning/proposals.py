"""User-reviewed improvement and staged-extension proposals."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..persistence import atomic_write_json
from .events import LearningEvent, TaskOutcome, bounded_text
from .store import LearningStore

logger = logging.getLogger(__name__)

MIN_REFLECTIONS_FOR_ANALYSIS = 5
MIN_TOOL_USES_FOR_PATTERN = 3
MIN_ERROR_FREQUENCY_FOR_PROPOSAL = 3
PROPOSAL_SCHEMA_VERSION = 1
MAX_PROPOSAL_RECORDS = 500
MAX_GENERATED_FILE_BYTES = 512 * 1024
MAX_GENERATED_EXPLANATION_BYTES = 32 * 1024


class ImprovementProposal:
    """A structured proposal that cannot apply itself."""

    def __init__(
        self,
        proposal_type: str,
        title: str,
        description: str,
        action: dict[str, Any],
        reason: str,
        *,
        evidence_event_ids: list[str] | None = None,
    ):
        self.proposal_id = uuid.uuid4().hex[:18]
        self.proposal_type = proposal_type
        self.title = bounded_text(title, 160)
        self.description = bounded_text(description, 1_000)
        self.action = dict(action)
        self.reason = bounded_text(reason, 500)
        self.evidence_event_ids = list(evidence_event_ids or [])
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "title": self.title,
            "description": self.description,
            "action": self.action,
            "reason": self.reason,
            "evidence_event_ids": self.evidence_event_ids,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ProposalEngine:
    """Analyze canonical events and apply only explicitly approved safe actions."""

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = Path(storage_dir or Path.home() / ".radsim" / "learning")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_file = self.storage_dir / "improvement_proposals.json"
        self.staging_root = self.storage_dir.parent / "extension_staging"
        self.store = LearningStore(storage_dir=self.storage_dir)
        self._proposals: list[dict[str, Any]] = []
        self.last_analysis_at = ""
        self.last_analysis_duration_ms = 0.0
        self._load()

    def _load(self) -> None:
        if not self.proposals_file.is_file():
            return
        try:
            data = json.loads(self.proposals_file.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, list):
            self._proposals = [
                item for item in data if isinstance(item, dict)
            ][-MAX_PROPOSAL_RECORDS:]
            return
        if not isinstance(data, dict):
            return
        proposals = data.get("proposals", [])
        self._proposals = [
            item for item in proposals if isinstance(item, dict)
        ][-MAX_PROPOSAL_RECORDS:]
        self.last_analysis_at = str(data.get("last_analysis_at") or "")
        self.last_analysis_duration_ms = float(data.get("last_analysis_duration_ms") or 0)

    def _save(self) -> None:
        self._proposals = self._proposals[-MAX_PROPOSAL_RECORDS:]
        atomic_write_json(
            self.proposals_file,
            {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                "last_analysis_at": self.last_analysis_at,
                "last_analysis_duration_ms": self.last_analysis_duration_ms,
                "proposals": self._proposals,
            },
            default=str,
        )

    def analyze_and_propose(self) -> list[dict[str, Any]]:
        """Generate bounded rule-based proposals from verified events."""
        import time

        started = time.perf_counter()
        candidates = [
            *self._analyze_error_patterns(),
            *self._analyze_tool_patterns(),
            *self._analyze_failure_categories(),
        ]
        extension_candidate = self._analyze_extension_candidate()
        if extension_candidate is not None:
            candidates.append(extension_candidate)

        existing_titles = {
            proposal["title"]
            for proposal in self._proposals
            if proposal.get("status") == "pending"
        }
        unique = [proposal for proposal in candidates if proposal["title"] not in existing_titles]

        from ..agent_config import get_agent_config_manager

        maximum = int(
            get_agent_config_manager().get("self_improvement.max_pending_proposals", 10)
        )
        pending = len(self.get_pending_proposals())
        accepted = unique[: max(0, maximum - pending)]
        self._proposals.extend(accepted)
        self.last_analysis_at = datetime.now(timezone.utc).isoformat()
        self.last_analysis_duration_ms = (time.perf_counter() - started) * 1000
        self._save()
        return accepted

    def _analyze_error_patterns(self) -> list[dict[str, Any]]:
        from .retrieval import ErrorAnalyzer

        proposals = []
        analyzer = ErrorAnalyzer(storage_dir=self.storage_dir)
        for pattern in analyzer.get_error_patterns(MIN_ERROR_FREQUENCY_FOR_PROPOSAL)[:3]:
            if not pattern["tools_affected"]:
                continue
            solution = pattern["solutions"][0] if pattern["solutions"] else "Review this error"
            proposals.append(
                ImprovementProposal(
                    proposal_type="memory_note",
                    title=f"Remember recurring {pattern['error_type']} failure",
                    description=(
                        f"{pattern['message'][:100]} occurred {pattern['frequency']} times "
                        f"with {', '.join(pattern['tools_affected'][:3])}."
                    ),
                    action={
                        "type": "save_memory",
                        "key": f"error_guard:{pattern['pattern'][:50]}",
                        "value": f"Known issue: {pattern['message']}. Fix: {solution}",
                    },
                    reason=f"{pattern['frequency']} verified failures",
                ).to_dict()
            )
        return proposals

    def _analyze_tool_patterns(self) -> list[dict[str, Any]]:
        from .retrieval import ToolOptimizer

        proposals = []
        for chain in ToolOptimizer(storage_dir=self.storage_dir).get_common_chains():
            if chain["count"] < MIN_TOOL_USES_FOR_PATTERN:
                continue
            tools = " -> ".join(chain["tools"])
            proposals.append(
                ImprovementProposal(
                    proposal_type="tool_pattern",
                    title=f"Save verified tool pattern: {tools[:70]}",
                    description=(
                        f"This exact tool sequence completed {chain['count']} verified tasks."
                    ),
                    action={
                        "type": "save_memory",
                        "key": f"tool_pattern:{uuid.uuid5(uuid.NAMESPACE_URL, tools).hex[:16]}",
                        "value": f"Verified tool sequence: {tools}",
                    },
                    reason=f"{chain['count']} verified successful task outcomes",
                ).to_dict()
            )
        return proposals

    def _analyze_failure_categories(self) -> list[dict[str, Any]]:
        events = self.store.query(
            event_types={"task_completion"},
            outcomes={
                TaskOutcome.FAILED.value,
                TaskOutcome.PARTIALLY_SUCCESSFUL.value,
                TaskOutcome.REVERTED.value,
            },
            limit=500,
        )
        completions = {
            event.task_id: event
            for event in self.store.query(event_types={"task_completion"}, limit=500)
        }
        existing_ids = {event.task_id for event in events}
        for revert in self.store.query(event_types={"task_revert"}, limit=500):
            completion = completions.get(revert.task_id)
            if completion is not None and completion.task_id not in existing_ids:
                events.append(completion)
                existing_ids.add(completion.task_id)
        counts = Counter(event.task_category for event in events)
        proposals = []
        for category, count in counts.most_common(2):
            if count < MIN_REFLECTIONS_FOR_ANALYSIS:
                continue
            evidence = [
                event.event_id for event in events if event.task_category == category
            ][-10:]
            proposals.append(
                ImprovementProposal(
                    proposal_type="prompt_adjustment",
                    title=f"Require stronger verification for {category}",
                    description=(
                        f"{count} tasks in {category} failed, were partial, or were reverted."
                    ),
                    action={
                        "type": "save_skill",
                        "value": (
                            f"For {category} tasks, collect execution evidence and run the "
                            "relevant checks before reporting success."
                        ),
                    },
                    reason=f"{count} non-successful verified outcomes",
                    evidence_event_ids=evidence,
                ).to_dict()
            )
        return proposals

    def _analyze_extension_candidate(self) -> dict[str, Any] | None:
        """Stage a tiny workflow-hint command only after repeated verified evidence."""
        from ..agent_config import get_agent_config_manager

        if not get_agent_config_manager().get("tools.self_extension", False):
            return None
        from .retrieval import verified_success_events

        events = verified_success_events(
            self.store,
            event_types={"task_completion"},
            limit=500,
        )
        groups: dict[tuple[str, tuple[str, ...]], list[LearningEvent]] = {}
        for event in events:
            tools = tuple(event.metadata.get("tools_used", []))
            if tools:
                groups.setdefault((event.task_category, tools), []).append(event)
        if not groups:
            return None
        (category, tools), evidence = max(groups.items(), key=lambda item: len(item[1]))
        if len(evidence) < 5:
            return None
        suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{category}:{tools}").hex[:8]
        extension_id = f"workflow-{category.replace('_', '-')}-{suffix}"
        command_name = f"workflow-{category.replace('_', '-')}"
        chain = " -> ".join(tools)
        source = (
            f"WORKFLOW = {chain!r}\n\n"
            "def setup(api):\n"
            "    def show_workflow(agent):\n"
            "        print(f\"  Verified workflow: {WORKFLOW}\")\n"
            f"    api.register_command({command_name!r}, show_workflow, "
            f"{'Show a verified workflow for ' + category!r})\n"
        )
        manifest = {
            "id": extension_id,
            "name": f"Verified {category.replace('_', ' ').title()} Workflow",
            "version": "1.0.0",
            "entrypoint": "extension.py",
            "permissions": ["commands.register"],
        }
        staged = self.stage_extension_proposal(
            manifest=manifest,
            source=source,
            tests="from extension import WORKFLOW\n\nassert WORKFLOW\n",
            explanation=f"Adds /{command_name} for the verified sequence: {chain}.",
            evidence_event_ids=[event.event_id for event in evidence[-10:]],
            save=False,
        )
        return staged.get("proposal") if staged.get("success") else None

    def stage_extension_proposal(
        self,
        *,
        manifest: dict[str, Any],
        source: str,
        tests: str,
        explanation: str,
        evidence_event_ids: list[str],
        save: bool = True,
    ) -> dict[str, Any]:
        """Write a generated candidate to staging without importing or executing it."""
        from ..agent_config import get_agent_config_manager
        from ..extension_loader import validate_manifest_data

        if not get_agent_config_manager().get("tools.self_extension", False):
            return {"success": False, "error": "Self-extension is disabled"}
        from .retrieval import verified_success_events

        verified_ids = {
            event.event_id
            for event in verified_success_events(
                self.store,
                event_types={"task_completion"},
                limit=self.store.max_events,
            )
        }
        evidence = [event_id for event_id in evidence_event_ids if event_id in verified_ids]
        if not evidence:
            return {"success": False, "error": "Verified task evidence is required"}
        if len(source.encode("utf-8")) > MAX_GENERATED_FILE_BYTES:
            return {"success": False, "error": "Generated extension source is too large"}
        if len((tests or "").encode("utf-8")) > MAX_GENERATED_FILE_BYTES:
            return {"success": False, "error": "Generated extension tests are too large"}
        if len(explanation.encode("utf-8")) > MAX_GENERATED_EXPLANATION_BYTES:
            return {"success": False, "error": "Generated extension explanation is too large"}
        try:
            compile(source, "extension.py", "exec")
            compile(tests or "", "test_extension.py", "exec")
            validated = validate_manifest_data(manifest)
        except (SyntaxError, ValueError) as error:
            return {"success": False, "error": f"Invalid extension candidate: {error}"}

        proposal = ImprovementProposal(
            proposal_type="extension_proposal",
            title=f"Stage extension: {validated.name}",
            description=bounded_text(explanation, 1_000),
            action={
                "type": "activate_extension",
                "extension_id": validated.extension_id,
                "permissions": list(validated.permissions),
            },
            reason=f"Supported by {len(evidence)} verified task outcomes",
            evidence_event_ids=evidence,
        ).to_dict()
        staging_dir = self.staging_root / proposal["proposal_id"]
        staging_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_json(staging_dir / "manifest.json", manifest)
        entrypoint = (staging_dir / validated.entrypoint).resolve()
        if staging_dir.resolve() not in entrypoint.parents:
            return {"success": False, "error": "Extension entrypoint escapes staging"}
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        entrypoint.write_text(source)
        (staging_dir / "test_extension.py").write_text(tests or "")
        (staging_dir / "EXPLANATION.md").write_text(bounded_text(explanation, 4_000) + "\n")
        proposal["action"]["staging_dir"] = str(staging_dir)
        if save:
            self._proposals.append(proposal)
            self._save()
        return {"success": True, "proposal": proposal, "staging_dir": str(staging_dir)}

    def get_pending_proposals(self) -> list[dict[str, Any]]:
        return [
            proposal for proposal in self._proposals if proposal.get("status") == "pending"
        ]

    def get_proposal_by_id(self, proposal_id: str) -> dict[str, Any] | None:
        return next(
            (
                proposal
                for proposal in self._proposals
                if proposal.get("proposal_id") == proposal_id
            ),
            None,
        )

    def approve_proposal(
        self,
        proposal_id: str,
        *,
        allow_generated_code: bool = False,
        command_registry=None,
    ) -> dict[str, Any]:
        proposal = self.get_proposal_by_id(proposal_id)
        if proposal is None:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}
        if proposal.get("status") != "pending":
            return {"success": False, "error": f"Proposal already {proposal.get('status')}"}
        if proposal.get("proposal_type") == "extension_proposal" and not allow_generated_code:
            return {
                "success": False,
                "error": "Generated extension activation requires explicit approval",
            }
        result = self._apply_action(
            proposal.get("action", {}),
            command_registry=command_registry,
        )
        if result.get("success"):
            proposal["status"] = "approved"
            proposal["resolved_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            self._record_decision(proposal, "approved", TaskOutcome.SUCCESSFUL)
        else:
            self._record_decision(
                proposal,
                "approval_failed",
                TaskOutcome.FAILED,
                result.get("error", ""),
            )
        return result

    def reject_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get_proposal_by_id(proposal_id)
        if proposal is None:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}
        proposal["status"] = "rejected"
        proposal["resolved_at"] = datetime.now(timezone.utc).isoformat()
        self._remove_staging(proposal)
        self._save()
        self._record_decision(proposal, "rejected", TaskOutcome.USER_REJECTED)
        return {"success": True, "message": "Proposal rejected"}

    def skip_proposal(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get_proposal_by_id(proposal_id)
        if proposal is None:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}
        proposal["status"] = "skipped"
        proposal["resolved_at"] = datetime.now(timezone.utc).isoformat()
        self._remove_staging(proposal)
        self._save()
        self._record_decision(proposal, "skipped", TaskOutcome.CANCELLED)
        return {"success": True, "message": "Proposal skipped"}

    def _remove_staging(self, proposal: dict[str, Any]) -> None:
        """Remove only this proposal's real directory inside the staging root."""
        if proposal.get("proposal_type") != "extension_proposal":
            return
        staging = Path(str(proposal.get("action", {}).get("staging_dir", "")))
        try:
            if (
                staging.is_dir()
                and not staging.is_symlink()
                and self.staging_root.resolve() in staging.resolve().parents
            ):
                shutil.rmtree(staging)
        except OSError:
            logger.warning("Could not remove rejected extension staging directory")

    def _record_decision(
        self,
        proposal: dict[str, Any],
        decision: str,
        outcome: TaskOutcome,
        error: str = "",
    ) -> None:
        """Store one bounded proposal decision in the canonical event path."""
        from ..agent_config import get_agent_config_manager

        if not get_agent_config_manager().get("learning.enabled", True):
            return
        self.store.append(
            LearningEvent.create(
                event_type="proposal_decision",
                action_signature=proposal.get("proposal_id"),
                outcome=outcome,
                error_type="proposal_error" if error else None,
                error_message=error,
                user_decision=decision,
                summary=proposal.get("title", "Evolution proposal"),
                metadata={"proposal_type": proposal.get("proposal_type", "unknown")},
            )
        )

    def _apply_action(self, action: dict[str, Any], command_registry=None) -> dict[str, Any]:
        action_type = action.get("type")
        if action_type == "set_config":
            from ..agent_config import get_agent_config_manager

            get_agent_config_manager().set(str(action["key"]), action.get("value"))
            return {
                "success": True,
                "message": f"Config updated: {action['key']} = {action.get('value')}",
            }
        if action_type == "save_memory":
            from ..memory import save_memory

            return save_memory(action.get("key", "self_improvement_note"), action.get("value", ""))
        if action_type == "save_skill":
            from ..skill_registry import add_skill

            return add_skill(action.get("value", ""))
        if action_type == "activate_extension":
            from ..extension_loader import get_extension_loader

            return get_extension_loader(command_registry).install_staged_extension(
                Path(str(action.get("staging_dir", "")))
            )
        return {"success": False, "error": f"Unknown action type: {action_type}"}

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        resolved = [
            proposal for proposal in self._proposals if proposal.get("status") != "pending"
        ]
        return sorted(
            resolved,
            key=lambda proposal: proposal.get("resolved_at") or "",
            reverse=True,
        )[:limit]

    def get_stats(self) -> dict[str, Any]:
        by_status = Counter(proposal.get("status", "unknown") for proposal in self._proposals)
        by_type = Counter(proposal.get("proposal_type", "unknown") for proposal in self._proposals)
        decisions = by_status["approved"] + by_status["rejected"]
        return {
            "total_proposals": len(self._proposals),
            "by_status": dict(by_status),
            "by_type": dict(by_type),
            "pending_count": by_status["pending"],
            "approved_count": by_status["approved"],
            "rejected_count": by_status["rejected"],
            "skipped_count": by_status["skipped"],
            "approval_rate": by_status["approved"] / decisions if decisions else 0.0,
            "last_analysis": self.last_analysis_at,
            "last_analysis_duration_ms": self.last_analysis_duration_ms,
        }

    def get_reflection_count_since_last_analysis(self) -> int:
        return len(
            self.store.query(
                event_types={"task_completion"},
                since=self.last_analysis_at or None,
                limit=self.store.max_events,
            )
        )


SelfImprover = ProposalEngine
_proposal_engine: ProposalEngine | None = None


def get_self_improver() -> ProposalEngine:
    global _proposal_engine
    if _proposal_engine is None:
        _proposal_engine = ProposalEngine()
    return _proposal_engine


def analyze_and_propose_improvements() -> list[dict[str, Any]]:
    return get_self_improver().analyze_and_propose()


def get_pending_proposals() -> list[dict[str, Any]]:
    return get_self_improver().get_pending_proposals()


def approve_proposal(proposal_id: str) -> dict[str, Any]:
    return get_self_improver().approve_proposal(proposal_id)


def reject_proposal(proposal_id: str) -> dict[str, Any]:
    return get_self_improver().reject_proposal(proposal_id)
