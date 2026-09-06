"""Account model metadata for RadSim's subscription model and effort controls."""

import time

from .bounded_cache import MISSING, BoundedCache, path_signature
from .codex_transport import CodexError

CATALOG_TTL_SECONDS = 300
_catalog_cache = BoundedCache(max_entries=4)


def load_catalog(*, refresh=False) -> list[dict]:
    """Read the signed-in catalogue, caching only validated model metadata."""
    from .chatgpt_tokens import auth_file
    from .codex_auth import list_models
    from .codex_connection import open_connection

    path = auth_file()
    if not path.is_file() or path.is_symlink():
        raise CodexError("ChatGPT sign-in is required. Run: radsim login chatgpt")
    key = path_signature(path)
    cached = _catalog_cache.get(key)
    if not refresh and cached is not MISSING:
        saved_at, models = cached
        if time.monotonic() - saved_at < CATALOG_TTL_SECONDS:
            return models
    with open_connection() as connection:
        models = [_model_metadata(model) for model in list_models(connection)]
    _catalog_cache.set(key, (time.monotonic(), models))
    return models


def _model_metadata(model: dict) -> dict:
    """Allow only known effort values and retain no account identifiers."""
    from .config import REASONING_EFFORT_LEVELS

    supported = model.get("supportedReasoningEfforts", [])
    if not isinstance(supported, list) or len(supported) > 16:
        raise CodexError("Codex returned invalid reasoning settings.")
    efforts = []
    for entry in supported:
        effort = entry.get("reasoningEffort") if isinstance(entry, dict) else None
        if effort not in REASONING_EFFORT_LEVELS:
            raise CodexError("Codex returned an unsupported reasoning setting.")
        if effort not in efforts:
            efforts.append(effort)
    default = model.get("defaultReasoningEffort")
    return {
        "model": model["model"],
        "efforts": tuple(efforts),
        "default_effort": default if default in efforts else next(iter(efforts), None),
        "is_default": model.get("isDefault") is True,
    }


def model_capabilities(model: str) -> dict:
    """Return available controls; unavailable metadata never enables a setting."""
    try:
        return next((item for item in load_catalog() if item["model"] == model), {})
    except (CodexError, OSError):
        return {}


def select_model(agent) -> None:
    """Choose an account model and its effort within the running RadSim session."""
    from .commands_learning import LearningCommandHandlersMixin
    from .menu import interactive_menu
    from .output import print_info

    try:
        models = load_catalog(refresh=True)
        if not models:
            raise CodexError("No ChatGPT models are available for this account.")
        current = getattr(agent.config, "model", None)
        choice = interactive_menu(
            "CHATGPT MODEL",
            [
                (item["model"], item["model"] + (" (current)" if item["model"] == current else ""))
                for item in models
            ],
        )
        if choice is None:
            return
        agent.update_config("chatgpt", None, choice)
        LearningCommandHandlersMixin()._reasoning_effort_menu(agent)
    except (CodexError, OSError) as error:
        print_info(
            str(error) if isinstance(error, CodexError) else "Could not load ChatGPT models."
        )
