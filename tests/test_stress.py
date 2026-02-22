"""Stress tests for RadSim rate limiter, budget guard, and memory system.

These tests push the system to its limits with rapid-fire calls,
large inputs, deep nesting, concurrent access, and boundary values.
"""

import json
import threading
import time

import pytest

from radsim.rate_limiter import (
    BudgetExceeded,
    BudgetGuard,
    CircuitBreaker,
    CircuitBreakerOpen,
    ProtectionManager,
    RateLimiter,
    RateLimitExceeded,
)
from radsim.tools.file_ops import read_file, write_file
from radsim.tools.validation import validate_path, validate_shell_command
from radsim.vector_memory import (
    COLLECTION_CODE_PATTERNS,
    COLLECTION_CONVERSATIONS,
    COLLECTION_PROJECT_CONTEXT,
    COLLECTION_USER_PREFERENCES,
    JsonMemoryFallback,
    VectorMemory,
)

# =============================================================================
# Rate Limiter Stress Tests
# =============================================================================


class TestRateLimiterStress:
    """Rapid-fire rate limiter to verify it blocks at the limit."""

    def test_rapid_fire_1000_calls(self):
        """Fire 1000 calls in a tight loop; verify the limiter stops us."""
        limiter = RateLimiter(max_calls_per_turn=100, cooldown_ms=0)
        call_count = 0
        blocked = False

        for _ in range(1000):
            try:
                limiter.check()
                call_count += 1
            except RateLimitExceeded:
                blocked = True
                break

        assert blocked is True
        assert call_count < 1000
        # Should have blocked at exactly max_calls_per_turn
        assert call_count == 99  # Blocked on the 100th call

    def test_rapid_fire_small_limit(self):
        """Small limit (5) with 100 calls."""
        limiter = RateLimiter(max_calls_per_turn=5, cooldown_ms=0)
        blocked_at = None

        for i in range(100):
            try:
                limiter.check()
            except RateLimitExceeded:
                blocked_at = i
                break

        assert blocked_at is not None
        assert blocked_at == 4  # 0-indexed: blocked on 5th call (index 4)

    def test_reset_allows_more_calls(self):
        """After reset, calls should be allowed again."""
        limiter = RateLimiter(max_calls_per_turn=10, cooldown_ms=0)

        # Use up all calls
        for _ in range(9):
            limiter.check()

        limiter.reset()

        # Should allow calls again
        for _ in range(9):
            limiter.check()

        # And block at limit again
        with pytest.raises(RateLimitExceeded):
            limiter.check()

    def test_failure_tracking_rapid(self):
        """Record many failures rapidly; verify the failure limit triggers."""
        limiter = RateLimiter(max_calls_per_turn=1000, max_failures_per_turn=5, cooldown_ms=0)
        blocked = False

        for _ in range(100):
            try:
                limiter.record_failure()
            except RateLimitExceeded:
                blocked = True
                break

        assert blocked is True

    def test_success_resets_failure_count(self):
        """Success after failures should reset the failure counter."""
        limiter = RateLimiter(max_calls_per_turn=1000, max_failures_per_turn=5, cooldown_ms=0)

        # Record 4 failures (just under the limit)
        for _ in range(4):
            limiter.record_failure()

        # Success should reset
        limiter.record_success()

        # Should be able to record failures again
        for _ in range(4):
            limiter.record_failure()

        # 5th should now trip
        with pytest.raises(RateLimitExceeded):
            limiter.record_failure()

    def test_get_status_accuracy(self):
        """Verify status reporting under stress."""
        limiter = RateLimiter(max_calls_per_turn=50, cooldown_ms=0)

        for _ in range(25):
            limiter.check()

        status = limiter.get_status()
        assert status["calls"] == 25
        assert status["max"] == 50
        assert status["remaining"] == 25
        assert status["percentage"] == 50.0


# =============================================================================
# Circuit Breaker Stress Tests
# =============================================================================


class TestCircuitBreakerStress:
    """Push the circuit breaker with rapid consecutive errors."""

    def test_rapid_errors_same_type(self):
        """Rapid errors of the same type should trip the breaker."""
        breaker = CircuitBreaker(threshold=5, cooldown_seconds=60.0)
        tripped = False

        for _ in range(100):
            try:
                breaker.record_error("api_error")
            except CircuitBreakerOpen:
                tripped = True
                break

        assert tripped is True

    def test_mixed_error_types(self):
        """Different error types should be tracked independently."""
        breaker = CircuitBreaker(threshold=3, cooldown_seconds=60.0)

        # Alternate between error types - neither should trip
        for _ in range(2):
            breaker.record_error("type_a")
            breaker.record_error("type_b")

        # Add one more of type_a -> should trip
        with pytest.raises(CircuitBreakerOpen):
            breaker.record_error("type_a")

    def test_many_error_types(self):
        """50 different error types, each below threshold."""
        breaker = CircuitBreaker(threshold=5, cooldown_seconds=60.0)

        # Each error type gets 4 errors (under threshold of 5)
        for i in range(50):
            for _ in range(4):
                breaker.record_error(f"error_type_{i}")

        # None should trip - verify no exception was raised

    def test_circuit_open_check(self):
        """After tripping, is_open should return True."""
        breaker = CircuitBreaker(threshold=2, cooldown_seconds=60.0)

        breaker.record_error("test_error")
        with pytest.raises(CircuitBreakerOpen):
            breaker.record_error("test_error")

        assert breaker.is_open("test_error") is True
        assert breaker.is_open("other_error") is False

    def test_circuit_cooldown(self):
        """After cooldown period, circuit should close."""
        breaker = CircuitBreaker(threshold=2, cooldown_seconds=0.1)

        breaker.record_error("test_error")
        with pytest.raises(CircuitBreakerOpen):
            breaker.record_error("test_error")

        assert breaker.is_open("test_error") is True

        # Wait for cooldown
        time.sleep(0.15)

        assert breaker.is_open("test_error") is False

    def test_reset_clears_all(self):
        """Reset should clear all error counts and open circuits."""
        breaker = CircuitBreaker(threshold=2, cooldown_seconds=60.0)

        breaker.record_error("error_a")
        with pytest.raises(CircuitBreakerOpen):
            breaker.record_error("error_a")

        breaker.reset()

        # Should be able to record errors again
        breaker.record_error("error_a")
        # And not trip on the second one (count was reset)
        assert breaker.is_open("error_a") is False


# =============================================================================
# Budget Guard Stress Tests
# =============================================================================


class TestBudgetGuardStress:
    """Stress the budget guard with large token counts."""

    def test_large_token_count(self):
        """Single large token usage should trigger budget exceeded."""
        guard = BudgetGuard(max_input_tokens=1000, max_output_tokens=500)

        with pytest.raises(BudgetExceeded):
            guard.record_usage(input_tokens=2000, output_tokens=0)

    def test_cumulative_small_usage(self):
        """Many small usages should eventually exceed the budget."""
        guard = BudgetGuard(max_input_tokens=1000, max_output_tokens=500)
        exceeded = False

        for _ in range(200):
            try:
                guard.record_usage(input_tokens=10, output_tokens=5)
            except BudgetExceeded:
                exceeded = True
                break

        assert exceeded is True
        assert guard.input_tokens >= 1000

    def test_output_budget_enforcement(self):
        """Output token budget should also be enforced."""
        guard = BudgetGuard(max_input_tokens=1_000_000, max_output_tokens=100)

        with pytest.raises(BudgetExceeded):
            guard.record_usage(input_tokens=0, output_tokens=200)

    def test_warning_before_exceeded(self):
        """Warning should fire before budget is exceeded."""
        guard = BudgetGuard(
            max_input_tokens=1000, max_output_tokens=500, warn_threshold=0.5
        )

        # Use 49% - no warning
        warning = guard.record_usage(input_tokens=490, output_tokens=0)
        assert warning is None

        # Use to 51% - should warn
        warning = guard.record_usage(input_tokens=20, output_tokens=0)
        assert warning is not None

    def test_unlimited_budget(self):
        """With max=0, budget should be unlimited."""
        guard = BudgetGuard(max_input_tokens=0, max_output_tokens=0)

        # Should never raise even with huge usage
        for _ in range(100):
            guard.record_usage(input_tokens=100_000, output_tokens=50_000)

        assert guard.input_tokens == 10_000_000
        assert guard.output_tokens == 5_000_000

    def test_percentage_properties(self):
        """Verify percentage calculations under stress."""
        guard = BudgetGuard(max_input_tokens=10000, max_output_tokens=5000)

        guard.record_usage(input_tokens=5000, output_tokens=2500)

        assert guard.input_percentage == 50.0
        assert guard.output_percentage == 50.0

    def test_percentage_unlimited(self):
        """Percentage should be 0 when budget is unlimited."""
        guard = BudgetGuard(max_input_tokens=0, max_output_tokens=0)

        guard.record_usage(input_tokens=999999, output_tokens=999999)

        assert guard.input_percentage == 0
        assert guard.output_percentage == 0

    def test_reset_clears_usage(self):
        """Reset should clear all tracked usage."""
        guard = BudgetGuard(max_input_tokens=1000, max_output_tokens=500)

        guard.record_usage(input_tokens=900, output_tokens=400)
        guard.reset()

        assert guard.input_tokens == 0
        assert guard.output_tokens == 0

        # Should be able to use budget again
        guard.record_usage(input_tokens=900, output_tokens=400)


# =============================================================================
# Protection Manager Stress
# =============================================================================


class TestProtectionManagerStress:
    """Stress the unified protection manager."""

    def test_rapid_api_calls(self):
        """Rapid API calls should be rate limited."""
        manager = ProtectionManager()
        manager.rate_limiter = RateLimiter(max_calls_per_turn=20, cooldown_ms=0)
        blocked = False

        for _ in range(100):
            try:
                manager.check_before_api_call()
            except RateLimitExceeded:
                blocked = True
                break

        assert blocked is True

    def test_rapid_api_errors(self):
        """Rapid API errors should trip the circuit breaker."""
        manager = ProtectionManager()
        manager.circuit_breaker = CircuitBreaker(threshold=3, cooldown_seconds=60.0)
        tripped = False

        for _ in range(100):
            try:
                manager.record_api_error("api_error")
            except (CircuitBreakerOpen, RateLimitExceeded):
                tripped = True
                break

        assert tripped is True

    def test_user_input_resets(self):
        """on_user_input should reset rate limiter and circuit breaker."""
        manager = ProtectionManager()
        manager.rate_limiter = RateLimiter(max_calls_per_turn=10, cooldown_ms=0)

        for _ in range(9):
            manager.check_before_api_call()

        manager.on_user_input()

        # Should be fully reset
        for _ in range(9):
            manager.check_before_api_call()


# =============================================================================
# Oversized Input Tests
# =============================================================================


class TestOversizedInput:
    """Test handling of very large content."""

    def test_write_large_content(self, tmp_path):
        """Write 1MB+ content and verify handling."""
        import os

        large_content = "x" * (1024 * 1024 + 1)  # 1MB + 1 byte

        # Create a test file inside a temp directory
        test_file = tmp_path / "large_file.txt"

        # Use the cwd trick to make validate_path accept the tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = write_file(str(test_file), large_content, show_diff=False)
            # Should succeed - write_file doesn't limit content size
            assert result["success"] is True
            assert result["bytes_written"] >= 1024 * 1024
        finally:
            os.chdir(original_cwd)

    def test_read_large_file_rejection(self, tmp_path):
        """Reading a file larger than MAX_FILE_SIZE should fail."""
        import os

        from radsim.tools.constants import MAX_FILE_SIZE

        # Create a file just over MAX_FILE_SIZE
        large_file = tmp_path / "oversized.txt"
        large_file.write_text("x" * (MAX_FILE_SIZE + 1))

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = read_file(str(large_file))
            assert result["success"] is False
            assert "too large" in result.get("error", "").lower()
        finally:
            os.chdir(original_cwd)

    def test_shell_command_very_long(self):
        """Very long shell command string."""
        long_command = "echo " + "a" * 100_000
        is_valid, error = validate_shell_command(long_command)
        # Should not crash - either accepts or rejects gracefully
        assert isinstance(is_valid, bool)


# =============================================================================
# Deeply Nested JSON Tests
# =============================================================================


class TestDeeplyNestedJSON:
    """Test handling of deeply nested JSON structures."""

    def test_nested_dict_100_levels(self):
        """100-level deep nested dict should not cause stack overflow."""
        nested = {}
        current = nested
        for i in range(100):
            current[f"level_{i}"] = {}
            current = current[f"level_{i}"]
        current["value"] = "deep"

        # Serialize and deserialize
        json_str = json.dumps(nested)
        recovered = json.loads(json_str)
        assert isinstance(recovered, dict)

    def test_nested_list_100_levels(self):
        """100-level deep nested list should not cause stack overflow."""
        nested = current = []
        for _ in range(100):
            inner = []
            current.append(inner)
            current = inner
        current.append("deep_value")

        json_str = json.dumps(nested)
        recovered = json.loads(json_str)
        assert isinstance(recovered, list)

    def test_nested_json_in_memory(self, tmp_path):
        """Store deeply nested JSON as metadata in memory."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        nested_metadata = {}
        current = nested_metadata
        for i in range(50):
            current[f"level_{i}"] = {}
            current = current[f"level_{i}"]
        current["value"] = "deep"

        # add_memory converts non-string metadata values to str
        memory_id = memory.add_memory(
            COLLECTION_CONVERSATIONS,
            "Test content with nested metadata",
            nested_metadata,
        )
        assert memory_id != ""


# =============================================================================
# Empty and Null Input Tests
# =============================================================================


class TestEmptyNullInputs:
    """Test every tool function with empty and null inputs."""

    def test_validate_path_empty(self):
        is_safe, _, error = validate_path("")
        assert is_safe is False

    def test_validate_path_none(self):
        is_safe, _, error = validate_path(None)
        assert is_safe is False

    def test_validate_shell_empty(self):
        is_valid, error = validate_shell_command("")
        assert is_valid is False

    def test_validate_shell_none(self):
        is_valid, error = validate_shell_command(None)
        assert is_valid is False

    def test_read_file_empty(self):
        result = read_file("")
        assert result["success"] is False

    def test_read_file_none(self):
        result = read_file(None)
        assert result["success"] is False

    def test_write_file_empty_path(self):
        result = write_file("", "content")
        assert result["success"] is False

    def test_write_file_none_path(self):
        result = write_file(None, "content")
        assert result["success"] is False

    def test_memory_add_empty_content(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        memory_id = memory.add_memory(COLLECTION_CONVERSATIONS, "")
        assert memory_id == ""

    def test_memory_add_whitespace_content(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        memory_id = memory.add_memory(COLLECTION_CONVERSATIONS, "   ")
        assert memory_id == ""

    def test_memory_search_empty_query(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        results = memory.search_memories(COLLECTION_CONVERSATIONS, "")
        assert results == []

    def test_memory_search_whitespace_query(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        results = memory.search_memories(COLLECTION_CONVERSATIONS, "   ")
        assert results == []

    def test_memory_delete_empty_id(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        result = memory.delete_memory(COLLECTION_CONVERSATIONS, "")
        assert result is False

    def test_memory_invalid_collection(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        memory_id = memory.add_memory("invalid_collection", "test")
        assert memory_id == ""

    def test_memory_get_context_empty(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        context = memory.get_relevant_context("")
        assert context == ""

    def test_memory_get_context_whitespace(self, tmp_path):
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        context = memory.get_relevant_context("   ")
        assert context == ""


# =============================================================================
# Concurrent File Writes Tests
# =============================================================================


class TestConcurrentFileWrites:
    """Test concurrent writes to the same file path.

    Note: validate_path uses Path.cwd() to check if paths are inside the project.
    Since os.chdir is process-global (not thread-safe), we test concurrent writes
    by changing CWD once before spawning threads, and restoring after.
    """

    def test_concurrent_writes_to_same_file(self, tmp_path):
        """Multiple threads writing to the same file simultaneously."""
        import os

        test_file = tmp_path / "concurrent.txt"
        results = []
        errors = []

        # Change CWD once (process-global) so all threads see tmp_path as CWD
        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        def writer(thread_id):
            try:
                content = f"Written by thread {thread_id}\n" * 100
                result = write_file(str(test_file), content, show_diff=False)
                results.append(result)
            except Exception as exc:
                errors.append(str(exc))

        try:
            threads = []
            for i in range(10):
                thread = threading.Thread(target=writer, args=(i,))
                threads.append(thread)

            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            # No threads should have crashed
            assert len(errors) == 0, f"Thread errors: {errors}"
            # All writes should have reported success
            for result in results:
                assert result["success"] is True

            # The file should exist and have content from one of the threads
            assert test_file.exists()
            content = test_file.read_text()
            assert "Written by thread" in content
        finally:
            os.chdir(original_cwd)

    def test_concurrent_reads_and_writes(self, tmp_path):
        """Readers and writers accessing the same file."""
        import os

        test_file = tmp_path / "rw_concurrent.txt"
        test_file.write_text("initial content")
        errors = []

        original_cwd = os.getcwd()
        os.chdir(tmp_path)

        def reader():
            try:
                result = read_file(str(test_file))
                # Should not crash, though content may vary
                assert result["success"] is True or result["success"] is False
            except Exception as exc:
                errors.append(f"Reader error: {exc}")

        def writer(thread_id):
            try:
                write_file(
                    str(test_file), f"content from writer {thread_id}", show_diff=False
                )
            except Exception as exc:
                errors.append(f"Writer error: {exc}")

        try:
            threads = []
            for i in range(5):
                threads.append(threading.Thread(target=reader))
                threads.append(threading.Thread(target=writer, args=(i,)))

            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            assert len(errors) == 0, f"Errors: {errors}"
        finally:
            os.chdir(original_cwd)


# =============================================================================
# Memory System Stress Tests
# =============================================================================


class TestMemoryStress:
    """Stress tests for the vector memory system."""

    def test_add_many_entries(self, tmp_path):
        """Add 1,000 entries without crashing.

        Uses 1,000 instead of 10,000 because the JSON fallback writes
        to disk on every add, making 10K entries very slow in CI.
        """
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        for i in range(1_000):
            memory_id = memory.add_memory(
                COLLECTION_CONVERSATIONS,
                f"Memory entry number {i} with some content about topic {i % 100}",
                {"index": i},
            )
            assert memory_id != "", f"Failed to add memory at index {i}"

        stats = memory.get_collection_stats(COLLECTION_CONVERSATIONS)
        assert stats["count"] == 1_000

    def test_search_after_bulk_add(self, tmp_path):
        """Search should work correctly after bulk additions."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        # Add entries with distinct content
        for i in range(100):
            memory.add_memory(
                COLLECTION_CODE_PATTERNS,
                f"Python function for sorting algorithm variant {i}",
                {"language": "python"},
            )

        results = memory.search_memories(
            COLLECTION_CODE_PATTERNS, "sorting algorithm", top_k=10
        )
        assert len(results) > 0
        assert len(results) <= 10

    def test_memory_across_all_collections(self, tmp_path):
        """Add entries to all collections and query across them."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        collections = [
            COLLECTION_CONVERSATIONS,
            COLLECTION_CODE_PATTERNS,
            COLLECTION_USER_PREFERENCES,
            COLLECTION_PROJECT_CONTEXT,
        ]

        for collection in collections:
            for i in range(50):
                memory.add_memory(
                    collection,
                    f"Entry {i} in {collection} about data processing",
                    {"collection": collection, "index": i},
                )

        # Get context across all collections
        context = memory.get_relevant_context("data processing")
        assert len(context) > 0

    def test_clear_and_reuse_collection(self, tmp_path):
        """Clear a collection and verify it can be reused."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        # Add entries
        for i in range(100):
            memory.add_memory(COLLECTION_CONVERSATIONS, f"Entry {i}")

        stats = memory.get_collection_stats(COLLECTION_CONVERSATIONS)
        assert stats["count"] == 100

        # Clear
        memory.clear_collection(COLLECTION_CONVERSATIONS)

        stats = memory.get_collection_stats(COLLECTION_CONVERSATIONS)
        assert stats["count"] == 0

        # Reuse
        memory.add_memory(COLLECTION_CONVERSATIONS, "New entry after clear")
        stats = memory.get_collection_stats(COLLECTION_CONVERSATIONS)
        assert stats["count"] == 1

    def test_delete_nonexistent_memory(self, tmp_path):
        """Deleting a non-existent ID should not crash."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))
        result = memory.delete_memory(COLLECTION_CONVERSATIONS, "nonexistent_id_12345")
        assert result is False

    def test_large_content_memory(self, tmp_path):
        """Store a very large string in memory."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        large_content = "word " * 50_000  # ~250KB of text
        memory_id = memory.add_memory(COLLECTION_CONVERSATIONS, large_content)
        assert memory_id != ""

        # Should be searchable
        results = memory.search_memories(COLLECTION_CONVERSATIONS, "word", top_k=1)
        assert len(results) > 0

    def test_special_characters_in_content(self, tmp_path):
        """Memory should handle special characters without crashing."""
        memory = VectorMemory(persist_directory=str(tmp_path / "vectors"))

        special_contents = [
            "Content with null: \x00",
            "Content with newlines:\n\n\n",
            "Content with tabs:\t\t\t",
            "Content with unicode: \u2603 \u2764 \U0001f600",
            'Content with quotes: "hello" \'world\'',
            "Content with backslashes: C:\\Users\\test\\file",
            "Content with HTML: <script>alert('xss')</script>",
            "Content with SQL: DROP TABLE users; --",
        ]

        for content in special_contents:
            memory_id = memory.add_memory(COLLECTION_CONVERSATIONS, content)
            # Should either succeed or fail gracefully (no crash)
            assert isinstance(memory_id, str)


class TestJsonMemoryFallbackStress:
    """Stress tests specifically for the JSON memory fallback."""

    def test_bulk_add_and_search(self, tmp_path):
        """Add 1000 entries and search."""
        fallback = JsonMemoryFallback(tmp_path / "json_memory")

        for i in range(1000):
            fallback.add(
                COLLECTION_CONVERSATIONS,
                f"entry_{i}",
                f"This is about topic {i % 10} with keyword alpha",
                {"index": i},
            )

        assert fallback.count(COLLECTION_CONVERSATIONS) == 1000

        results = fallback.search(COLLECTION_CONVERSATIONS, "topic alpha keyword", 10)
        assert len(results) <= 10

    def test_keyword_extraction_edge_cases(self, tmp_path):
        """Test keyword extraction with edge-case text."""
        fallback = JsonMemoryFallback(tmp_path / "json_memory")

        # Empty text
        keywords = fallback._extract_keywords("")
        assert len(keywords) == 0

        # Only stopwords
        keywords = fallback._extract_keywords("the a an is are was were")
        assert len(keywords) == 0

        # Only short words
        keywords = fallback._extract_keywords("a b c d e f g")
        assert len(keywords) == 0

        # Numbers
        keywords = fallback._extract_keywords("12345 678 901 abc123")
        assert "12345" in keywords or "abc123" in keywords

    def test_persistence_across_instances(self, tmp_path):
        """Data should persist when a new instance is created."""
        persist_dir = tmp_path / "persist_test"

        # First instance: add data
        fallback1 = JsonMemoryFallback(persist_dir)
        fallback1.add(COLLECTION_CONVERSATIONS, "test_1", "Persistent content", {})
        assert fallback1.count(COLLECTION_CONVERSATIONS) == 1

        # Second instance: data should still be there
        fallback2 = JsonMemoryFallback(persist_dir)
        assert fallback2.count(COLLECTION_CONVERSATIONS) == 1

    def test_clear_and_count(self, tmp_path):
        """Clear should remove all entries; count should reflect that."""
        fallback = JsonMemoryFallback(tmp_path / "json_memory")

        for i in range(50):
            fallback.add(COLLECTION_CONVERSATIONS, f"entry_{i}", f"Content {i}", {})

        assert fallback.count(COLLECTION_CONVERSATIONS) == 50

        fallback.clear(COLLECTION_CONVERSATIONS)
        assert fallback.count(COLLECTION_CONVERSATIONS) == 0
