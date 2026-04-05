import json

from app_paths import ensure_parent_dir, resolve_runtime_path


CACHE_FILE = resolve_runtime_path("AB_MARGIN_CACHE_FILE", "margin_cache.json")


def load_margin_cache():
    if not CACHE_FILE.exists():
        return {}

    with CACHE_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_margin_cache(data):
    cache_path = ensure_parent_dir(CACHE_FILE)
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_margin_per_unit(symbol):
    data = load_margin_cache()
    return data.get(symbol)


def set_margin_per_unit(symbol, value):
    data = load_margin_cache()
    data[symbol] = value
    save_margin_cache(data)
