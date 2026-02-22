"""RADSIM Learning System - Self-improving agent capabilities.

This package provides machine learning and recursive learning features
that allow RADSIM to improve over time without custom model training.

Modules:
- error_analyzer: Track and prevent repeated mistakes
- preference_learner: Learn user preferences from feedback
- few_shot_assembler: Include relevant examples in prompts
- active_learner: Ask clarifying questions when uncertain
- tool_optimizer: Learn which tools work best for which tasks
- reflection_engine: Post-task analysis for continuous improvement
- analytics: Learning dashboard and statistics
- self_improver: Propose and apply improvements from learning data
"""

from .active_learner import (
    ActiveLearner,
    assess_uncertainty,
    generate_clarifying_questions,
    get_active_learner,
)
from .analytics import (
    LearningAnalytics,
    export_learning_report,
    get_analytics,
    get_learning_stats,
    reset_learning_category,
)
from .error_analyzer import (
    ErrorAnalyzer,
    check_similar_error,
    get_error_analyzer,
    get_error_patterns,
    record_error,
)
from .few_shot_assembler import (
    FewShotAssembler,
    get_examples_for_task,
    get_few_shot_assembler,
    inject_examples_into_prompt,
)
from .preference_learner import (
    PreferenceLearner,
    adjust_prompt_for_preferences,
    get_learned_preferences,
    get_preference_learner,
    record_feedback,
)
from .reflection_engine import (
    ReflectionEngine,
    get_improvement_opportunities,
    get_reflection_engine,
    reflect_on_completion,
)
from .self_improver import (
    SelfImprover,
    analyze_and_propose_improvements,
    approve_proposal,
    get_pending_proposals,
    get_self_improver,
    reject_proposal,
)
from .tool_optimizer import (
    ToolOptimizer,
    get_tool_optimizer,
    get_tool_rankings,
    suggest_tool_chain,
    track_tool_execution,
)

__all__ = [
    # Error Analyzer
    "ErrorAnalyzer",
    "get_error_analyzer",
    "record_error",
    "check_similar_error",
    "get_error_patterns",
    # Preference Learner
    "PreferenceLearner",
    "get_preference_learner",
    "record_feedback",
    "get_learned_preferences",
    "adjust_prompt_for_preferences",
    # Few-Shot Assembler
    "FewShotAssembler",
    "get_few_shot_assembler",
    "get_examples_for_task",
    "inject_examples_into_prompt",
    # Active Learner
    "ActiveLearner",
    "get_active_learner",
    "assess_uncertainty",
    "generate_clarifying_questions",
    # Tool Optimizer
    "ToolOptimizer",
    "get_tool_optimizer",
    "track_tool_execution",
    "suggest_tool_chain",
    "get_tool_rankings",
    # Reflection Engine
    "ReflectionEngine",
    "get_reflection_engine",
    "reflect_on_completion",
    "get_improvement_opportunities",
    # Self-Improver
    "SelfImprover",
    "get_self_improver",
    "analyze_and_propose_improvements",
    "get_pending_proposals",
    "approve_proposal",
    "reject_proposal",
    # Analytics
    "LearningAnalytics",
    "get_analytics",
    "get_learning_stats",
    "export_learning_report",
    "reset_learning_category",
]
