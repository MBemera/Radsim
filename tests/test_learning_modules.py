"""Tests for the Learning System modules."""


from radsim.learning.active_learner import ActiveLearner
from radsim.learning.error_analyzer import ErrorAnalyzer
from radsim.learning.few_shot_assembler import FewShotAssembler
from radsim.learning.preference_learner import PreferenceLearner
from radsim.learning.reflection_engine import ReflectionEngine
from radsim.learning.tool_optimizer import ToolOptimizer


class TestErrorAnalyzer:
    """Test error pattern tracking."""

    def test_create_analyzer(self, tmp_path):
        analyzer = ErrorAnalyzer(storage_dir=tmp_path)
        assert analyzer is not None

    def test_record_error(self, tmp_path):
        analyzer = ErrorAnalyzer(storage_dir=tmp_path)
        analyzer.record_error(
            error_type="FileNotFoundError",
            error_message="No such file: test.py",
            context={"tool": "write_file"},
        )
        patterns = analyzer.get_error_patterns()
        assert isinstance(patterns, list)

    def test_check_similar_error(self, tmp_path):
        analyzer = ErrorAnalyzer(storage_dir=tmp_path)
        analyzer.record_error(
            error_type="ValueError",
            error_message="invalid literal",
            context={"tool": "parse_input"},
        )
        result = analyzer.check_similar_error("parse some input", "parse_input")
        assert isinstance(result, dict)

    def test_get_error_stats(self, tmp_path):
        analyzer = ErrorAnalyzer(storage_dir=tmp_path)
        stats = analyzer.get_error_stats()
        assert isinstance(stats, dict)

    def test_clear_history(self, tmp_path):
        analyzer = ErrorAnalyzer(storage_dir=tmp_path)
        analyzer.record_error(
            error_type="RuntimeError",
            error_message="test error",
        )
        analyzer.clear_history()
        patterns = analyzer.get_error_patterns()
        assert isinstance(patterns, list)


class TestPreferenceLearner:
    """Test preference learning from feedback."""

    def test_create_learner(self, tmp_path):
        learner = PreferenceLearner(storage_dir=tmp_path)
        assert learner is not None

    def test_record_feedback(self, tmp_path):
        learner = PreferenceLearner(storage_dir=tmp_path)
        learner.record_feedback(
            action="code_generation",
            suggestion="def hello(): pass",
        )
        prefs = learner.get_learned_preferences()
        assert isinstance(prefs, dict)

    def test_record_feedback_with_modification(self, tmp_path):
        learner = PreferenceLearner(storage_dir=tmp_path)
        learner.record_feedback(
            action="code_generation",
            suggestion="x = lambda: 1",
            modification="x = 1",
            metadata={"language": "python"},
        )
        prefs = learner.get_learned_preferences()
        assert isinstance(prefs, dict)

    def test_set_and_get_preference(self, tmp_path):
        learner = PreferenceLearner(storage_dir=tmp_path)
        learner.set_preference("style", "concise")
        assert learner.get_preference("style") == "concise"

    def test_get_feedback_summary(self, tmp_path):
        learner = PreferenceLearner(storage_dir=tmp_path)
        summary = learner.get_feedback_summary()
        assert isinstance(summary, dict)


class TestFewShotAssembler:
    """Test few-shot example assembly."""

    def test_create_assembler(self, tmp_path):
        assembler = FewShotAssembler(storage_dir=tmp_path)
        assert assembler is not None

    def test_get_examples_empty(self, tmp_path):
        assembler = FewShotAssembler(storage_dir=tmp_path)
        examples = assembler.get_examples_for_task("write a function")
        assert isinstance(examples, list)

    def test_inject_examples_into_prompt(self, tmp_path):
        assembler = FewShotAssembler(storage_dir=tmp_path)
        prompt = "Write a sorting function"
        result = assembler.inject_examples_into_prompt(prompt, "sorting")
        assert isinstance(result, str)

    def test_get_examples_stats(self, tmp_path):
        assembler = FewShotAssembler(storage_dir=tmp_path)
        stats = assembler.get_examples_stats()
        assert isinstance(stats, dict)


class TestActiveLearner:
    """Test active learning and uncertainty assessment."""

    def test_create_learner(self, tmp_path):
        learner = ActiveLearner(storage_dir=tmp_path)
        assert learner is not None

    def test_assess_uncertainty(self, tmp_path):
        learner = ActiveLearner(storage_dir=tmp_path)
        result = learner.assess_uncertainty("Build a REST API with auth")
        assert hasattr(result, "uncertainty_score")
        assert hasattr(result, "should_ask")

    def test_generate_clarifying_questions(self, tmp_path):
        learner = ActiveLearner(storage_dir=tmp_path)
        questions = learner.generate_clarifying_questions("Do something complex")
        assert isinstance(questions, list)


class TestToolOptimizer:
    """Test tool usage optimization."""

    def test_create_optimizer(self, tmp_path):
        optimizer = ToolOptimizer(storage_dir=tmp_path)
        assert optimizer is not None

    def test_track_execution(self, tmp_path):
        optimizer = ToolOptimizer(storage_dir=tmp_path)
        optimizer.track_tool_execution(
            tool_name="read_file",
            success=True,
            duration_ms=50,
        )
        rankings = optimizer.get_tool_rankings()
        assert isinstance(rankings, list)

    def test_suggest_tool_chain(self, tmp_path):
        optimizer = ToolOptimizer(storage_dir=tmp_path)
        suggestions = optimizer.suggest_tool_chain("search for imports")
        assert isinstance(suggestions, list)

    def test_get_tool_stats(self, tmp_path):
        optimizer = ToolOptimizer(storage_dir=tmp_path)
        optimizer.track_tool_execution(
            tool_name="grep_search",
            success=True,
            duration_ms=30,
        )
        stats = optimizer.get_tool_stats("grep_search")
        assert isinstance(stats, dict)


class TestReflectionEngine:
    """Test post-task reflection."""

    def test_create_engine(self, tmp_path):
        engine = ReflectionEngine(storage_dir=tmp_path)
        assert engine is not None

    def test_reflect_on_completion(self, tmp_path):
        engine = ReflectionEngine(storage_dir=tmp_path)
        reflection = engine.reflect_on_completion(
            task_description="Write a hello world",
            approach_taken="Created a simple Python script",
            result="File written successfully",
            success=True,
            tools_used=["write_file"],
            duration_seconds=0.5,
        )
        assert hasattr(reflection, "task_description")
        assert hasattr(reflection, "success")

    def test_get_improvement_opportunities(self, tmp_path):
        engine = ReflectionEngine(storage_dir=tmp_path)
        opportunities = engine.get_improvement_opportunities()
        assert isinstance(opportunities, list)

    def test_get_success_rate_by_category(self, tmp_path):
        engine = ReflectionEngine(storage_dir=tmp_path)
        rates = engine.get_success_rate_by_category()
        assert isinstance(rates, dict)
