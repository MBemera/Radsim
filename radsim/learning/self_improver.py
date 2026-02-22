"""Self-Improvement System.

Bridges passive learning data to active improvement proposals.
Analyzes patterns from errors, preferences, reflections, and tool usage
to generate rule-based proposals that users approve before applying.

Safety: disabled by default, every change requires explicit user approval,
NEVER modifies source code — only config, preferences, and memory files.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Minimum thresholds for generating proposals
MIN_REFLECTIONS_FOR_ANALYSIS = 5
MIN_TOOL_USES_FOR_PATTERN = 10
MIN_ERROR_FREQUENCY_FOR_PROPOSAL = 3
PREFERENCE_CONFIDENCE_THRESHOLD = 0.8


class ImprovementProposal:
    """A single proposed improvement for user review."""

    def __init__(self, proposal_type, title, description, action, reason):
        self.proposal_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
        self.proposal_type = proposal_type  # config_change, preference_update, prompt_adjustment, tool_pattern
        self.title = title
        self.description = description
        self.action = action  # Dict describing what to change
        self.reason = reason  # Why this is proposed
        self.status = "pending"  # pending, approved, rejected, skipped
        self.created_at = datetime.now().isoformat()
        self.resolved_at = None

    def to_dict(self):
        return {
            "proposal_id": self.proposal_id,
            "proposal_type": self.proposal_type,
            "title": self.title,
            "description": self.description,
            "action": self.action,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data):
        proposal = cls(
            proposal_type=data["proposal_type"],
            title=data["title"],
            description=data["description"],
            action=data["action"],
            reason=data["reason"],
        )
        proposal.proposal_id = data["proposal_id"]
        proposal.status = data["status"]
        proposal.created_at = data["created_at"]
        proposal.resolved_at = data.get("resolved_at")
        return proposal


class SelfImprover:
    """Analyzes learning data and proposes improvements.

    Flow:
    1. analyze() - scans learning modules for actionable patterns
    2. propose() - generates improvement proposals
    3. User reviews via /evolve command
    4. apply() - writes approved changes through existing modules
    """

    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".radsim" / "learning"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_file = self.storage_dir / "improvement_proposals.json"
        self._proposals: list[dict] = []
        self._load()

    def _load(self):
        """Load proposals from disk."""
        if self.proposals_file.exists():
            try:
                self._proposals = json.loads(self.proposals_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._proposals = []

    def _save(self):
        """Write proposals to disk."""
        try:
            self.proposals_file.write_text(
                json.dumps(self._proposals, indent=2, default=str) + "\n"
            )
        except OSError as error:
            logger.error("Failed to save proposals: %s", error)

    def analyze_and_propose(self) -> list[dict]:
        """Run all analyzers and generate proposals.

        Returns:
            List of new proposal dicts
        """
        new_proposals = []

        new_proposals.extend(self._analyze_unused_tools())
        new_proposals.extend(self._analyze_error_patterns())
        new_proposals.extend(self._analyze_preferences())
        new_proposals.extend(self._analyze_tool_patterns())
        new_proposals.extend(self._analyze_improvement_opportunities())

        # Deduplicate against existing pending proposals
        existing_titles = {p["title"] for p in self._proposals if p["status"] == "pending"}
        unique_new = [p for p in new_proposals if p["title"] not in existing_titles]

        # Respect max pending limit
        from ..agent_config import get_agent_config_manager
        config = get_agent_config_manager()
        max_pending = config.get("self_improvement.max_pending_proposals", 10)
        pending_count = sum(1 for p in self._proposals if p["status"] == "pending")
        slots_available = max(0, max_pending - pending_count)

        proposals_to_add = unique_new[:slots_available]
        self._proposals.extend(proposals_to_add)
        self._save()

        return proposals_to_add

    def _analyze_unused_tools(self) -> list[dict]:
        """Propose disabling tools with zero usage over many sessions."""
        proposals = []
        try:
            from .tool_optimizer import get_tool_optimizer
            optimizer = get_tool_optimizer()
            rankings = optimizer.get_tool_rankings()

            if not rankings:
                return proposals

            # Find tools that are enabled but never used
            from ..agent_config import TOOL_CONFIG_MAP, get_agent_config_manager
            config = get_agent_config_manager()

            # Invert map: config_key -> [tool_names]
            config_to_tools = {}
            for tool_name, config_key in TOOL_CONFIG_MAP.items():
                config_to_tools.setdefault(config_key, []).append(tool_name)

            ranked_tool_names = {r["tool_name"] for r in rankings}
            total_uses = sum(r["total_uses"] for r in rankings)

            # Only suggest if we have significant usage data
            if total_uses < 50:
                return proposals

            for config_key, tool_names in config_to_tools.items():
                is_enabled = config.get(f"tools.{config_key}", True)
                if not is_enabled:
                    continue

                # Check if ANY tool in this category was used
                any_used = any(name in ranked_tool_names for name in tool_names)
                if not any_used:
                    proposal = ImprovementProposal(
                        proposal_type="config_change",
                        title=f"Disable unused tool category: {config_key}",
                        description=(
                            f"The '{config_key}' tools ({', '.join(tool_names)}) "
                            f"have never been used across {total_uses} total tool executions. "
                            f"Disabling reduces attack surface."
                        ),
                        action={
                            "type": "set_config",
                            "key": f"tools.{config_key}",
                            "value": False,
                        },
                        reason=f"Zero usage across {total_uses} total tool executions",
                    )
                    proposals.append(proposal.to_dict())

        except Exception:
            logger.debug("Unused tool analysis failed")

        return proposals

    def _analyze_error_patterns(self) -> list[dict]:
        """Propose guards for frequently failing tools."""
        proposals = []
        try:
            from .error_analyzer import get_error_analyzer
            analyzer = get_error_analyzer()
            patterns = analyzer.get_error_patterns(min_frequency=MIN_ERROR_FREQUENCY_FOR_PROPOSAL)

            for pattern in patterns[:3]:  # Top 3 most frequent
                tools_affected = pattern.get("tools_affected", [])
                solutions = pattern.get("solutions", [])

                if not tools_affected:
                    continue

                best_solution = solutions[0] if solutions else "Review error pattern"

                proposal = ImprovementProposal(
                    proposal_type="config_change",
                    title=f"Recurring error in {', '.join(tools_affected[:2])}",
                    description=(
                        f"Error pattern '{pattern['message'][:80]}' "
                        f"has occurred {pattern['frequency']} times. "
                        f"Tools affected: {', '.join(tools_affected)}."
                    ),
                    action={
                        "type": "save_memory",
                        "key": f"error_guard:{pattern['pattern'][:50]}",
                        "value": f"Known issue: {pattern['message'][:100]}. Fix: {best_solution[:100]}",
                    },
                    reason=f"{pattern['frequency']} occurrences of this error pattern",
                )
                proposals.append(proposal.to_dict())

        except Exception:
            logger.debug("Error pattern analysis failed")

        return proposals

    def _analyze_preferences(self) -> list[dict]:
        """Propose solidifying high-confidence preferences."""
        proposals = []
        try:
            from .preference_learner import get_preference_learner
            learner = get_preference_learner()
            prefs = learner.get_learned_preferences()
            feedback = learner.get_feedback_summary()

            total_feedback = feedback.get("total", 0)
            if total_feedback < 10:
                return proposals

            avg_quality = feedback.get("avg_quality", 0)

            # If quality is consistently high, note it
            if avg_quality >= PREFERENCE_CONFIDENCE_THRESHOLD:
                code_style = prefs.get("code_style", {})
                indent = code_style.get("indentation", 4)
                naming = code_style.get("naming_convention", "snake_case")

                proposal = ImprovementProposal(
                    proposal_type="preference_update",
                    title=f"Lock in code style: {indent}-space {naming}",
                    description=(
                        f"Based on {total_feedback} feedback signals "
                        f"(avg quality: {avg_quality:.0%}), your preferred style is: "
                        f"{indent}-space indentation, {naming} naming. "
                        f"Saving as a permanent skill prevents style drift."
                    ),
                    action={
                        "type": "save_skill",
                        "value": (
                            f"Always use {indent}-space indentation and {naming} naming convention. "
                            f"User preference confidence: {avg_quality:.0%}."
                        ),
                    },
                    reason=f"High confidence ({avg_quality:.0%}) across {total_feedback} interactions",
                )
                proposals.append(proposal.to_dict())

        except Exception:
            logger.debug("Preference analysis failed")

        return proposals

    def _analyze_tool_patterns(self) -> list[dict]:
        """Propose saving successful tool chains as patterns."""
        proposals = []
        try:
            from .tool_optimizer import get_tool_optimizer
            optimizer = get_tool_optimizer()

            # Look for highly successful tool chains
            chains = optimizer._chains if hasattr(optimizer, "_chains") else []
            if len(chains) < MIN_TOOL_USES_FOR_PATTERN:
                return proposals

            # Find tool sequences that succeed consistently
            chain_success = {}
            for chain in chains:
                key = "->".join(chain.get("tools_used", [])[:5])
                if not key:
                    continue
                if key not in chain_success:
                    chain_success[key] = {"total": 0, "success": 0, "desc": chain.get("task_description", "")}
                chain_success[key]["total"] += 1
                if chain.get("success"):
                    chain_success[key]["success"] += 1

            for chain_key, stats in chain_success.items():
                if stats["total"] < 3:
                    continue
                success_rate = stats["success"] / stats["total"]
                if success_rate >= 0.9:
                    tools_list = chain_key.replace("->", " -> ")
                    proposal = ImprovementProposal(
                        proposal_type="tool_pattern",
                        title=f"Save tool pattern: {tools_list[:60]}",
                        description=(
                            f"Tool sequence [{tools_list}] succeeds "
                            f"{success_rate:.0%} of the time ({stats['total']} uses). "
                            f"Typical task: {stats['desc'][:80]}"
                        ),
                        action={
                            "type": "save_memory",
                            "key": f"tool_pattern:{chain_key[:50]}",
                            "value": f"Effective tool chain: {tools_list}. Success rate: {success_rate:.0%}",
                        },
                        reason=f"{success_rate:.0%} success rate across {stats['total']} uses",
                    )
                    proposals.append(proposal.to_dict())

        except Exception:
            logger.debug("Tool pattern analysis failed")

        return proposals

    def _analyze_improvement_opportunities(self) -> list[dict]:
        """Convert reflection insights into actionable proposals."""
        proposals = []
        try:
            from .reflection_engine import get_reflection_engine
            engine = get_reflection_engine()
            opportunities = engine.get_improvement_opportunities()

            for opp in opportunities[:2]:  # Top 2 opportunities
                category = opp.get("category", "general")
                suggestion = opp.get("suggestion", "")
                failure_count = opp.get("failure_count", 0)

                if not suggestion or failure_count < MIN_REFLECTIONS_FOR_ANALYSIS:
                    continue

                proposal = ImprovementProposal(
                    proposal_type="prompt_adjustment",
                    title=f"Improve {category} handling",
                    description=(
                        f"Category '{category}' has {failure_count} recorded failures. "
                        f"Suggestion: {suggestion}"
                    ),
                    action={
                        "type": "save_skill",
                        "value": f"When working on {category} tasks: {suggestion}",
                    },
                    reason=f"{failure_count} failures in '{category}' category",
                )
                proposals.append(proposal.to_dict())

        except Exception:
            logger.debug("Improvement opportunity analysis failed")

        return proposals

    def get_pending_proposals(self) -> list[dict]:
        """Get all proposals awaiting user review."""
        return [p for p in self._proposals if p["status"] == "pending"]

    def get_proposal_by_id(self, proposal_id: str) -> dict | None:
        """Find a proposal by its ID."""
        for proposal in self._proposals:
            if proposal["proposal_id"] == proposal_id:
                return proposal
        return None

    def approve_proposal(self, proposal_id: str) -> dict:
        """Approve and apply a proposal.

        Returns:
            Dict with success status and what was changed
        """
        proposal = self.get_proposal_by_id(proposal_id)
        if not proposal:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}

        if proposal["status"] != "pending":
            return {"success": False, "error": f"Proposal already {proposal['status']}"}

        # Apply the action
        result = self._apply_action(proposal["action"])

        if result["success"]:
            proposal["status"] = "approved"
            proposal["resolved_at"] = datetime.now().isoformat()
            self._save()

        return result

    def reject_proposal(self, proposal_id: str) -> dict:
        """Reject a proposal."""
        proposal = self.get_proposal_by_id(proposal_id)
        if not proposal:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}

        proposal["status"] = "rejected"
        proposal["resolved_at"] = datetime.now().isoformat()
        self._save()
        return {"success": True, "message": "Proposal rejected"}

    def skip_proposal(self, proposal_id: str) -> dict:
        """Skip a proposal (keep for later)."""
        proposal = self.get_proposal_by_id(proposal_id)
        if not proposal:
            return {"success": False, "error": f"Proposal {proposal_id} not found"}

        proposal["status"] = "skipped"
        proposal["resolved_at"] = datetime.now().isoformat()
        self._save()
        return {"success": True, "message": "Proposal skipped"}

    def _apply_action(self, action: dict) -> dict:
        """Apply an approved action through existing modules.

        Supported action types:
        - set_config: Change agent_config.json setting
        - save_memory: Store a learning note in memory
        - save_skill: Add a custom skill/instruction
        """
        action_type = action.get("type")

        if action_type == "set_config":
            return self._apply_config_change(action)
        elif action_type == "save_memory":
            return self._apply_memory_save(action)
        elif action_type == "save_skill":
            return self._apply_skill_save(action)
        else:
            return {"success": False, "error": f"Unknown action type: {action_type}"}

    def _apply_config_change(self, action: dict) -> dict:
        """Apply a config change through AgentConfigManager."""
        try:
            from ..agent_config import get_agent_config_manager
            config = get_agent_config_manager()
            key = action["key"]
            value = action["value"]
            config.set(key, value)
            return {"success": True, "message": f"Config updated: {key} = {value}"}
        except Exception as error:
            return {"success": False, "error": str(error)}

    def _apply_memory_save(self, action: dict) -> dict:
        """Save a learning note to memory."""
        try:
            from ..memory import save_memory
            key = action.get("key", "self_improvement_note")
            value = action.get("value", "")
            result = save_memory(key, value)
            if result.get("success"):
                return {"success": True, "message": f"Memory saved: {key}"}
            return {"success": False, "error": result.get("error", "Memory save failed")}
        except ImportError:
            # Fallback: save directly to a file
            try:
                memory_file = self.storage_dir / "improvement_notes.json"
                notes = []
                if memory_file.exists():
                    notes = json.loads(memory_file.read_text())
                notes.append({
                    "key": action.get("key", ""),
                    "value": action.get("value", ""),
                    "timestamp": datetime.now().isoformat(),
                })
                memory_file.write_text(json.dumps(notes, indent=2) + "\n")
                return {"success": True, "message": f"Note saved: {action.get('key', '')}"}
            except Exception as error:
                return {"success": False, "error": str(error)}

    def _apply_skill_save(self, action: dict) -> dict:
        """Add a custom skill/instruction."""
        try:
            from ..skill_registry import add_skill
            value = action.get("value", "")
            result = add_skill(value)
            if result.get("success"):
                return {"success": True, "message": f"Skill added: {value[:60]}..."}
            return {"success": False, "error": result.get("error", "Skill save failed")}
        except ImportError:
            # Fallback: save to improvement notes
            return self._apply_memory_save(action)

    def get_history(self, limit: int = 20) -> list[dict]:
        """Get resolved proposals (approved/rejected/skipped)."""
        resolved = [p for p in self._proposals if p["status"] != "pending"]
        return sorted(resolved, key=lambda p: p.get("resolved_at", ""), reverse=True)[:limit]

    def get_stats(self) -> dict:
        """Get self-improvement statistics."""
        total = len(self._proposals)
        by_status = {}
        by_type = {}

        for proposal in self._proposals:
            status = proposal["status"]
            ptype = proposal["proposal_type"]
            by_status[status] = by_status.get(status, 0) + 1
            by_type[ptype] = by_type.get(ptype, 0) + 1

        return {
            "total_proposals": total,
            "by_status": by_status,
            "by_type": by_type,
            "pending_count": by_status.get("pending", 0),
            "approved_count": by_status.get("approved", 0),
            "rejected_count": by_status.get("rejected", 0),
            "skipped_count": by_status.get("skipped", 0),
            "approval_rate": (
                by_status.get("approved", 0) / (by_status.get("approved", 0) + by_status.get("rejected", 0))
                if (by_status.get("approved", 0) + by_status.get("rejected", 0)) > 0
                else 0.0
            ),
        }

    def get_reflection_count_since_last_analysis(self) -> int:
        """Count reflections since last analysis for auto-propose triggering."""
        try:
            from .reflection_engine import get_reflection_engine
            engine = get_reflection_engine()
            reflections = engine._reflections if hasattr(engine, "_reflections") else []

            if not self._proposals:
                return len(reflections)

            # Find the timestamp of the most recent proposal
            latest_proposal_time = max(
                (p.get("created_at", "") for p in self._proposals),
                default=""
            )

            # Count reflections newer than the latest proposal
            new_count = sum(
                1 for r in reflections
                if r.get("timestamp", "") > latest_proposal_time
            )
            return new_count

        except Exception:
            return 0


# Singleton instance
_self_improver: SelfImprover | None = None


def get_self_improver() -> SelfImprover:
    """Get or create the global SelfImprover instance."""
    global _self_improver
    if _self_improver is None:
        _self_improver = SelfImprover()
    return _self_improver


def analyze_and_propose_improvements() -> list[dict]:
    """Convenience function to run analysis and generate proposals."""
    return get_self_improver().analyze_and_propose()


def get_pending_proposals() -> list[dict]:
    """Convenience function to get pending proposals."""
    return get_self_improver().get_pending_proposals()


def approve_proposal(proposal_id: str) -> dict:
    """Convenience function to approve a proposal."""
    return get_self_improver().approve_proposal(proposal_id)


def reject_proposal(proposal_id: str) -> dict:
    """Convenience function to reject a proposal."""
    return get_self_improver().reject_proposal(proposal_id)
