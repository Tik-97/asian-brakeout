import json

from app_paths import ensure_parent_dir, resolve_runtime_path

RUNTIME_STATE_FILE = resolve_runtime_path("AB_RUNTIME_STATE_FILE", "runtime_state.json")
DEFAULT_RUNTIME_STATE = {
    "bot_enabled": True,
}


def _ensure_runtime_state():
    if not RUNTIME_STATE_FILE.exists():
        save_runtime_state(DEFAULT_RUNTIME_STATE.copy())


def load_runtime_state():
    _ensure_runtime_state()

    try:
        with RUNTIME_STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        data = {}

    runtime_state = DEFAULT_RUNTIME_STATE.copy()
    if isinstance(data, dict):
        runtime_state.update(data)
    return runtime_state


def save_runtime_state(data):
    runtime_state_path = ensure_parent_dir(RUNTIME_STATE_FILE)
    with runtime_state_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def is_bot_enabled():
    return bool(load_runtime_state().get("bot_enabled", True))


def set_bot_enabled(enabled):
    runtime_state = load_runtime_state()
    runtime_state["bot_enabled"] = bool(enabled)
    save_runtime_state(runtime_state)
    return runtime_state["bot_enabled"]
