"""Vector-based long-term memory for RadSim Agent.

Uses JSON-based storage with TF-IDF cosine similarity for semantic search
across conversations, code patterns, user preferences, and project context.

Pure Python — no native dependencies required. Works on all Python 3.10+ versions.
"""

import hashlib
import json
import logging
import math
import re
from datetime import datetime
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# Default storage location
DEFAULT_PERSIST_DIRECTORY = Path.home() / ".radsim" / "vector_store"

# Collection names for different memory types
COLLECTION_CONVERSATIONS = "conversations"
COLLECTION_CODE_PATTERNS = "code_patterns"
COLLECTION_USER_PREFERENCES = "user_preferences"
COLLECTION_PROJECT_CONTEXT = "project_context"

ALL_COLLECTIONS = [
    COLLECTION_CONVERSATIONS,
    COLLECTION_CODE_PATTERNS,
    COLLECTION_USER_PREFERENCES,
    COLLECTION_PROJECT_CONTEXT,
]


# =============================================================================
# JSON-based Fallback Memory (works without ChromaDB)
# =============================================================================


class JsonMemoryFallback:
    """Simple JSON-based memory storage with keyword matching.

    Used when ChromaDB is not available. Provides basic memory
    functionality using file-based storage and keyword search.
    """

    def __init__(self, persist_directory: Path):
        """Initialize JSON memory storage.

        Args:
            persist_directory: Directory to store memory JSON files
        """
        self.persist_directory = persist_directory
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collections: dict[str, list[dict]] = {}
        self._load_all_collections()

    def _get_collection_path(self, collection: str) -> Path:
        """Get the file path for a collection."""
        return self.persist_directory / f"{collection}.json"

    def _load_all_collections(self) -> None:
        """Load all collections from disk."""
        for collection_name in ALL_COLLECTIONS:
            self._load_collection(collection_name)

    def _load_collection(self, collection: str) -> None:
        """Load a single collection from disk."""
        path = self._get_collection_path(collection)
        if path.exists():
            try:
                with open(path) as f:
                    self.collections[collection] = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load {collection}: {e}")
                self.collections[collection] = []
        else:
            self.collections[collection] = []

    def _save_collection(self, collection: str) -> None:
        """Save a collection to disk."""
        path = self._get_collection_path(collection)
        try:
            with open(path, "w") as f:
                json.dump(self.collections[collection], f, indent=2)
        except OSError as e:
            logger.error(f"Failed to save {collection}: {e}")

    def add(self, collection: str, memory_id: str, content: str, metadata: dict) -> None:
        """Add a memory entry."""
        if collection not in self.collections:
            self.collections[collection] = []

        entry = {
            "id": memory_id,
            "content": content,
            "metadata": metadata,
            "keywords": list(self._extract_keywords(content)),  # Convert set to list for JSON
        }
        self.collections[collection].append(entry)
        self._save_collection(collection)

    def search(self, collection: str, query: str, top_k: int) -> list[dict]:
        """Search using TF-IDF cosine similarity and return scored results."""
        if collection not in self.collections:
            return []

        entries = self.collections[collection]
        if not entries:
            return []

        query_keywords = self._extract_keywords(query)
        if not query_keywords:
            # If no keywords extracted, return recent entries
            recent = entries[-top_k:]
            return [
                {
                    "id": e["id"],
                    "content": e["content"],
                    "metadata": e["metadata"],
                    "distance": 0.5,
                }
                for e in reversed(recent)
            ]

        # Build document frequency (DF) for IDF calculation
        num_docs = len(entries)
        doc_freq: dict[str, int] = {}
        entry_keyword_sets = []
        for entry in entries:
            kw_set = set(entry.get("keywords", []))
            entry_keyword_sets.append(kw_set)
            for kw in kw_set:
                doc_freq[kw] = doc_freq.get(kw, 0) + 1

        scored_results = []
        for idx, entry in enumerate(entries):
            entry_keywords = entry_keyword_sets[idx]
            if not entry_keywords:
                continue

            # Compute TF-IDF cosine similarity between query and entry
            shared_terms = query_keywords & entry_keywords
            if not shared_terms:
                continue

            # IDF weight: log(N / df) — higher for rarer terms
            dot_product = 0.0
            query_norm_sq = 0.0
            entry_norm_sq = 0.0

            all_terms = query_keywords | entry_keywords
            for term in all_terms:
                idf = math.log((num_docs + 1) / (doc_freq.get(term, 0) + 1)) + 1.0
                q_tfidf = idf if term in query_keywords else 0.0
                e_tfidf = idf if term in entry_keywords else 0.0
                dot_product += q_tfidf * e_tfidf
                query_norm_sq += q_tfidf * q_tfidf
                entry_norm_sq += e_tfidf * e_tfidf

            norm = math.sqrt(query_norm_sq) * math.sqrt(entry_norm_sq)
            similarity = dot_product / norm if norm > 0 else 0.0

            scored_results.append({
                "id": entry["id"],
                "content": entry["content"],
                "metadata": entry["metadata"],
                "distance": 1.0 - similarity,  # Lower distance = better match
            })

        # Sort by distance (ascending) and return top_k
        scored_results.sort(key=lambda x: x["distance"])
        return scored_results[:top_k]

    def delete(self, collection: str, memory_id: str) -> bool:
        """Delete a memory by ID."""
        if collection not in self.collections:
            return False

        original_len = len(self.collections[collection])
        self.collections[collection] = [
            e for e in self.collections[collection] if e["id"] != memory_id
        ]

        if len(self.collections[collection]) < original_len:
            self._save_collection(collection)
            return True
        return False

    def count(self, collection: str) -> int:
        """Get the count of memories in a collection."""
        return len(self.collections.get(collection, []))

    def clear(self, collection: str) -> None:
        """Clear all memories in a collection."""
        self.collections[collection] = []
        self._save_collection(collection)

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract keywords from text for matching.

        Simple tokenization: lowercase, split on non-alphanumeric,
        filter short words and common stopwords.
        """
        if not text:
            return set()

        # Tokenize: lowercase and split on non-word characters
        words = re.findall(r'\b[a-z0-9]+\b', text.lower())

        # Common stopwords to filter
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'can',
            'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
            'it', 'we', 'they', 'what', 'which', 'who', 'when', 'where',
            'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
            'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
            'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and',
            'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of',
            'at', 'by', 'for', 'with', 'about', 'against', 'between',
            'into', 'through', 'during', 'before', 'after', 'above',
            'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off',
        }

        # Filter: keep words with 3+ chars that aren't stopwords
        keywords = {w for w in words if len(w) >= 3 and w not in stopwords}

        return keywords


def generate_memory_id(content: str, timestamp: str) -> str:
    """Generate a unique ID for a memory entry.

    Args:
        content: The content to hash
        timestamp: ISO timestamp for uniqueness

    Returns:
        A unique hash-based ID
    """
    combined = f"{content}:{timestamp}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


class VectorMemory:
    """Vector-based long-term memory using JSON storage with TF-IDF search.

    Stores and retrieves memories using TF-IDF cosine similarity.
    Pure Python — no native dependencies required.

    Supports multiple collections for different types of memories:
    - conversations: Summarized conversation history
    - code_patterns: Learned code patterns and snippets
    - user_preferences: Semantic user preferences
    - project_context: Project-specific knowledge
    """

    def __init__(self, persist_directory: str | None = None):
        """Initialize the vector memory system.

        Args:
            persist_directory: Path to store the memory JSON files.
                             Defaults to ~/.radsim/vector_store/
        """
        self.persist_directory = Path(persist_directory or DEFAULT_PERSIST_DIRECTORY)
        self.is_available = True
        self.fallback = JsonMemoryFallback(self.persist_directory)
        logger.debug("VectorMemory initialized (JSON + TF-IDF backend)")

    def _validate_collection(self, collection: str) -> bool:
        """Validate that a collection name is valid.

        Args:
            collection: The collection name to validate

        Returns:
            True if valid, False otherwise
        """
        if collection not in ALL_COLLECTIONS:
            logger.warning(
                f"Invalid collection: {collection}. "
                f"Valid collections: {ALL_COLLECTIONS}"
            )
            return False
        return True

    def add_memory(
        self,
        collection: str,
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """Add a memory to a collection.

        Args:
            collection: The collection to add to (conversations, code_patterns,
                       user_preferences, or project_context)
            content: The text content to store and embed
            metadata: Optional metadata dict (e.g., source, timestamp, tags)

        Returns:
            The generated memory ID, or empty string if failed
        """
        if not self._validate_collection(collection):
            return ""

        if not content or not content.strip():
            logger.warning("Cannot add empty content to memory")
            return ""

        try:
            # Generate unique ID
            timestamp = datetime.now().isoformat()
            memory_id = generate_memory_id(content, timestamp)

            # Build metadata
            full_metadata = {
                "created_at": timestamp,
                "content_length": len(content),
            }
            if metadata:
                # Filter out None values and convert non-string values
                for key, value in metadata.items():
                    if value is not None:
                        if isinstance(value, (list, dict)):
                            full_metadata[key] = str(value)
                        else:
                            full_metadata[key] = value

            self.fallback.add(collection, memory_id, content, full_metadata)
            logger.debug(f"Added memory {memory_id} to {collection}")
            return memory_id

        except Exception as error:
            logger.error(f"Failed to add memory to {collection}: {error}")
            return ""

    def search_memories(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for relevant memories using semantic similarity.

        Uses ChromaDB vector search when available, falls back to
        keyword-based search otherwise.

        Args:
            collection: The collection to search
            query: The search query
            top_k: Maximum number of results to return

        Returns:
            List of matching memories with id, content, metadata, and distance
        """
        if not self._validate_collection(collection):
            return []

        if not query or not query.strip():
            logger.warning("Cannot search with empty query")
            return []

        try:
            results = self.fallback.search(collection, query, top_k)
            logger.debug(f"Found {len(results)} memories in {collection}")
            return results

        except Exception as error:
            logger.error(f"Failed to search memories in {collection}: {error}")
            return []

    def delete_memory(self, collection: str, memory_id: str) -> bool:
        """Delete a memory by its ID.

        Args:
            collection: The collection containing the memory
            memory_id: The ID of the memory to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self._validate_collection(collection):
            return False

        if not memory_id:
            logger.warning("Cannot delete memory: no ID provided")
            return False

        try:
            result = self.fallback.delete(collection, memory_id)
            if result:
                logger.debug(f"Deleted memory {memory_id} from {collection}")
            return result

        except Exception as error:
            logger.error(f"Failed to delete memory {memory_id}: {error}")
            return False

    def get_relevant_context(
        self,
        query: str,
        max_tokens: int = 2000,
    ) -> str:
        """Get relevant context from all collections for a query.

        Searches across all collections and combines the most relevant
        memories into a single context string.

        Args:
            query: The query to find context for
            max_tokens: Approximate maximum tokens for the response
                       (uses character estimation: ~4 chars per token)

        Returns:
            Combined context string from relevant memories
        """
        if not query or not query.strip():
            return ""

        try:
            # Estimate character limit (roughly 4 chars per token)
            max_chars = max_tokens * 4

            # Search each collection
            all_memories = []
            for collection_name in ALL_COLLECTIONS:
                memories = self.search_memories(collection_name, query, top_k=3)
                for memory in memories:
                    memory["source_collection"] = collection_name
                    all_memories.append(memory)

            # Sort by distance (lower is better)
            all_memories.sort(key=lambda m: m.get("distance", float("inf")))

            # Build context string
            context_parts = []
            current_length = 0

            for memory in all_memories:
                content = memory.get("content", "")
                collection = memory.get("source_collection", "unknown")

                # Format the memory entry
                entry = f"[{collection}]: {content}"

                # Check if adding this would exceed limit
                if current_length + len(entry) + 2 > max_chars:
                    break

                context_parts.append(entry)
                current_length += len(entry) + 2  # +2 for newlines

            result = "\n\n".join(context_parts)
            logger.debug(f"Built context of {len(result)} chars from {len(context_parts)} memories")
            return result

        except Exception as error:
            logger.error(f"Failed to get relevant context: {error}")
            return ""

    def get_collection_stats(self, collection: str) -> dict:
        """Get statistics about a collection.

        Args:
            collection: The collection name

        Returns:
            Dict with count and other stats
        """
        if not self._validate_collection(collection):
            return {"available": False, "count": 0, "error": "Invalid collection"}

        try:
            count = self.fallback.count(collection)
            return {
                "available": True,
                "count": count,
                "collection": collection,
                "backend": "json",
            }

        except Exception as error:
            return {"available": False, "count": 0, "error": str(error)}

    def clear_collection(self, collection: str) -> bool:
        """Clear all memories from a collection.

        Args:
            collection: The collection to clear

        Returns:
            True if cleared successfully, False otherwise
        """
        if not self._validate_collection(collection):
            return False

        try:
            self.fallback.clear(collection)
            logger.info(f"Cleared collection: {collection}")
            return True

        except Exception as error:
            logger.error(f"Failed to clear collection {collection}: {error}")
            return False


# =============================================================================
# Convenience Functions
# =============================================================================

# Module-level singleton for convenience functions
_default_memory: VectorMemory | None = None


def _get_default_memory() -> VectorMemory:
    """Get or create the default VectorMemory instance."""
    global _default_memory
    if _default_memory is None:
        _default_memory = VectorMemory()
    return _default_memory


def remember(content: str, category: str, metadata: dict | None = None) -> str:
    """Store a memory in the vector store.

    This is a convenience function for explicit memory storage.

    Args:
        content: The text content to remember
        category: Category of memory. One of:
                  - 'conversation' - Conversation summaries
                  - 'code' - Code patterns and snippets
                  - 'preference' - User preferences
                  - 'project' - Project-specific knowledge
        metadata: Optional additional metadata

    Returns:
        The memory ID if successful, empty string otherwise

    Example:
        >>> memory_id = remember(
        ...     "User prefers TypeScript over JavaScript",
        ...     "preference",
        ...     {"confidence": "high"}
        ... )
    """
    # Map friendly category names to collection names
    category_map = {
        "conversation": COLLECTION_CONVERSATIONS,
        "conversations": COLLECTION_CONVERSATIONS,
        "code": COLLECTION_CODE_PATTERNS,
        "code_pattern": COLLECTION_CODE_PATTERNS,
        "code_patterns": COLLECTION_CODE_PATTERNS,
        "preference": COLLECTION_USER_PREFERENCES,
        "preferences": COLLECTION_USER_PREFERENCES,
        "user_preference": COLLECTION_USER_PREFERENCES,
        "user_preferences": COLLECTION_USER_PREFERENCES,
        "project": COLLECTION_PROJECT_CONTEXT,
        "project_context": COLLECTION_PROJECT_CONTEXT,
    }

    collection = category_map.get(category.lower())
    if not collection:
        logger.warning(
            f"Unknown category: {category}. "
            f"Valid categories: conversation, code, preference, project"
        )
        return ""

    memory = _get_default_memory()
    return memory.add_memory(collection, content, metadata)


def recall(query: str, max_results: int = 5) -> list[dict]:
    """Retrieve memories relevant to a query.

    This is a convenience function for semantic retrieval.

    Args:
        query: The search query
        max_results: Maximum number of results per collection

    Returns:
        List of relevant memories from all collections

    Example:
        >>> memories = recall("user's coding preferences")
        >>> for mem in memories:
        ...     print(f"[{mem['source']}]: {mem['content']}")
    """
    memory = _get_default_memory()

    all_results = []
    for collection in ALL_COLLECTIONS:
        results = memory.search_memories(collection, query, top_k=max_results)
        for result in results:
            result["source"] = collection
        all_results.extend(results)

    # Sort by distance (similarity score)
    all_results.sort(key=lambda r: r.get("distance", float("inf")))

    # Return top results across all collections
    return all_results[:max_results * 2]  # Allow some overflow for variety


def get_context(query: str, max_tokens: int = 2000) -> str:
    """Get relevant context for a query from all memory collections.

    This is a convenience wrapper around VectorMemory.get_relevant_context().

    Args:
        query: The query to find context for
        max_tokens: Approximate maximum tokens for the response

    Returns:
        Combined context string from relevant memories

    Example:
        >>> context = get_context("How does the user prefer error handling?")
        >>> print(context)
        [user_preferences]: User prefers explicit error handling with try/catch
        [code_patterns]: def handle_error(e): return {"error": str(e)}
    """
    memory = _get_default_memory()
    return memory.get_relevant_context(query, max_tokens)


def is_vector_memory_available() -> bool:
    """Check if vector memory functionality is available.

    Returns:
        True (memory is always available — pure Python backend)
    """
    return True


def get_memory_backend() -> str:
    """Get the current memory backend being used.

    Returns:
        'json' — JSON storage with TF-IDF cosine similarity
    """
    return "json"
