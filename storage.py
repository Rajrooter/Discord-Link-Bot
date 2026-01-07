import json
import os
import threading
import uuid
from typing import Any, Dict, List

BASE_DIR = os.path.dirname(__file__) or "."
SAVED_LINKS_PATH = os.path.join(BASE_DIR, "saved_links.json")
CATEGORIES_PATH = os.path.join(BASE_DIR, "categories.json")
PENDING_PATH = os.path.join(BASE_DIR, "pending_links.json")
ONBOARDING_PATH = os.path.join(BASE_DIR, "onboarding_data.json")

_lock = threading.Lock()

def _read_json(path: str, default: Any):
    with _lock:
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

def _write_json(path: str, data: Any):
    with _lock:
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)

# Saved links
def get_saved_links() -> List[Dict]:
    return _read_json(SAVED_LINKS_PATH, [])

def add_saved_link(link: Dict):
    links = get_saved_links()
    links.append(link)
    _write_json(SAVED_LINKS_PATH, links)

def clear_saved_links():
    _write_json(SAVED_LINKS_PATH, [])

# Categories
def get_categories() -> Dict[str, List[str]]:
    return _read_json(CATEGORIES_PATH, {})

def add_link_to_category(category: str, link_url: str):
    categories = get_categories()
    categories.setdefault(category, [])
    if link_url not in categories[category]:
        categories[category].append(link_url)
    _write_json(CATEGORIES_PATH, categories)

def clear_categories():
    _write_json(CATEGORIES_PATH, {})

# Pending links
def add_pending_link(entry: Dict) -> str:
    pend = _read_json(PENDING_PATH, {})
    pending_id = str(uuid.uuid4())
    pend[pending_id] = entry
    _write_json(PENDING_PATH, pend)
    return pending_id

def get_pending_links_for_user(user_id: int) -> List[Dict]:
    pend = _read_json(PENDING_PATH, {})
    results = []
    for pid, entry in pend.items():
        if str(entry.get("user_id")) == str(user_id):
            entry["_id"] = pid
            results.append(entry)
    return results

def delete_pending_link_by_id(pending_id: str):
    pend = _read_json(PENDING_PATH, {})
    if pending_id in pend:
        del pend[pending_id]
        _write_json(PENDING_PATH, pend)

def update_pending_with_bot_msg_id(pending_id: str, bot_msg_id: int):
    pend = _read_json(PENDING_PATH, {})
    if pending_id in pend:
        pend[pending_id]["bot_msg_id"] = bot_msg_id
        _write_json(PENDING_PATH, pend)

# Onboarding
def load_onboarding_data() -> Dict:
    return _read_json(ONBOARDING_PATH, {})

def save_onboarding_data(data: Dict):
    _write_json(ONBOARDING_PATH, data)

def get_storage():
    class JSONStorage: ...
    return JSONStorage()
