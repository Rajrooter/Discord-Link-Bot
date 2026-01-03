"""
Storage adapter for Discord Link Manager Bot.
Provides MongoDB storage with JSON file fallback.
"""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

# Try to import MongoDB dependencies
try:
    from pymongo import MongoClient
    from bson import ObjectId
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    print("⚠️ pymongo not installed - using JSON file fallback")

# Environment configuration
MONGODB_URI = os.environ.get("MONGODB_URI")
DB_NAME = os.environ.get("DB_NAME", "discord_link_manager")

# JSON file paths for fallback
PENDING_LINKS_FILE = "pending_links.json"
SAVED_LINKS_FILE = "saved_links.json"
CATEGORIES_FILE = "categories.json"
ONBOARDING_FILE = "onboarding_data.json"

# Global storage backend
_storage_backend = None


class MongoDBStorage:
    """MongoDB storage backend"""
    
    def __init__(self, uri: str, db_name: str):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.pending_links = self.db["pending_links"]
        self.saved_links = self.db["saved_links"]
        self.categories = self.db["categories"]
        self.onboarding = self.db["onboarding"]
        print(f"✅ MongoDB connected: {db_name}")
    
    def add_pending_link(self, entry: Dict) -> str:
        """Add a pending link and return the inserted ID as string"""
        result = self.pending_links.insert_one(entry)
        return str(result.inserted_id)
    
    def update_pending_with_bot_msg_id(self, pending_id: str, bot_msg_id: int):
        """Update pending entry with bot message ID"""
        self.pending_links.update_one(
            {"_id": ObjectId(pending_id)},
            {"$set": {"bot_msg_id": bot_msg_id}}
        )
    
    def get_pending_links_for_user(self, user_id: int) -> List[Dict]:
        """Get all pending links for a specific user"""
        docs = list(self.pending_links.find({"user_id": user_id}))
        # Convert ObjectId to string for JSON serialization
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs
    
    def delete_pending_link_by_bot_msg_id(self, bot_msg_id: int):
        """Delete a pending link by bot message ID"""
        self.pending_links.delete_one({"bot_msg_id": bot_msg_id})
    
    def delete_pending_link_by_id(self, _id_str: str):
        """Delete a pending link by its ID"""
        self.pending_links.delete_one({"_id": ObjectId(_id_str)})
    
    def add_saved_link(self, entry: Dict):
        """Add a saved link"""
        self.saved_links.insert_one(entry)
    
    def get_saved_links(self) -> List[Dict]:
        """Get all saved links"""
        docs = list(self.saved_links.find())
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        return docs
    
    def add_link_to_category(self, category_name: str, link: str):
        """Add a link to a category"""
        self.categories.update_one(
            {"name": category_name},
            {"$push": {"links": link}},
            upsert=True
        )
    
    def get_categories(self) -> Dict:
        """Get all categories as dict"""
        result = {}
        for doc in self.categories.find():
            result[doc["name"]] = doc.get("links", [])
        return result
    
    def delete_category(self, category_name: str):
        """Delete a category"""
        self.categories.delete_one({"name": category_name})
    
    def clear_categories(self):
        """Clear all categories"""
        self.categories.delete_many({})
    
    def clear_saved_links(self):
        """Clear all saved links"""
        self.saved_links.delete_many({})
    
    def load_onboarding_data(self) -> Dict:
        """Load onboarding data"""
        doc = self.onboarding.find_one({"_id": "onboarding_data"})
        if doc:
            doc.pop("_id", None)
            return doc
        return {}
    
    def save_onboarding_data(self, data: Dict):
        """Save onboarding data"""
        self.onboarding.update_one(
            {"_id": "onboarding_data"},
            {"$set": data},
            upsert=True
        )


class JSONFileStorage:
    """JSON file storage backend (fallback)"""
    
    def __init__(self):
        print("⚠️ Using JSON file storage (MongoDB not configured)")
    
    def _load_json(self, filepath: str) -> any:
        """Load JSON from file"""
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            if filepath == CATEGORIES_FILE:
                return {}
            return []
    
    def _save_json(self, filepath: str, data: any):
        """Save JSON to file"""
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    
    def add_pending_link(self, entry: Dict) -> Optional[str]:
        """Add a pending link (returns None for file fallback)"""
        pending = self._load_json(PENDING_LINKS_FILE)
        pending.append(entry)
        self._save_json(PENDING_LINKS_FILE, pending)
        return None  # File backend doesn't return IDs
    
    def update_pending_with_bot_msg_id(self, pending_id: str, bot_msg_id: int):
        """Update pending entry with bot message ID (no-op for file backend)"""
        # For file backend, we'll use bot_msg_id as the primary key
        pending = self._load_json(PENDING_LINKS_FILE)
        # Find by user_id and link, update with bot_msg_id
        # This is a limitation of file storage
        pass
    
    def get_pending_links_for_user(self, user_id: int) -> List[Dict]:
        """Get all pending links for a specific user"""
        pending = self._load_json(PENDING_LINKS_FILE)
        return [link for link in pending if link.get("user_id") == user_id]
    
    def delete_pending_link_by_bot_msg_id(self, bot_msg_id: int):
        """Delete a pending link by bot message ID"""
        pending = self._load_json(PENDING_LINKS_FILE)
        pending = [link for link in pending if link.get("bot_msg_id") != bot_msg_id]
        self._save_json(PENDING_LINKS_FILE, pending)
    
    def delete_pending_link_by_id(self, _id_str: str):
        """Delete a pending link by its ID (no-op for file backend)"""
        # File backend doesn't have proper IDs
        pass
    
    def add_saved_link(self, entry: Dict):
        """Add a saved link"""
        links = self._load_json(SAVED_LINKS_FILE)
        links.append(entry)
        self._save_json(SAVED_LINKS_FILE, links)
    
    def get_saved_links(self) -> List[Dict]:
        """Get all saved links"""
        return self._load_json(SAVED_LINKS_FILE)
    
    def add_link_to_category(self, category_name: str, link: str):
        """Add a link to a category"""
        categories = self._load_json(CATEGORIES_FILE)
        if category_name not in categories:
            categories[category_name] = []
        categories[category_name].append(link)
        self._save_json(CATEGORIES_FILE, categories)
    
    def get_categories(self) -> Dict:
        """Get all categories"""
        return self._load_json(CATEGORIES_FILE)
    
    def delete_category(self, category_name: str):
        """Delete a category"""
        categories = self._load_json(CATEGORIES_FILE)
        if category_name in categories:
            del categories[category_name]
        self._save_json(CATEGORIES_FILE, categories)
    
    def clear_categories(self):
        """Clear all categories"""
        self._save_json(CATEGORIES_FILE, {})
    
    def clear_saved_links(self):
        """Clear all saved links"""
        self._save_json(SAVED_LINKS_FILE, [])
    
    def load_onboarding_data(self) -> Dict:
        """Load onboarding data"""
        return self._load_json(ONBOARDING_FILE)
    
    def save_onboarding_data(self, data: Dict):
        """Save onboarding data"""
        self._save_json(ONBOARDING_FILE, data)


def _init_storage():
    """Initialize the storage backend based on environment"""
    global _storage_backend
    
    if MONGODB_URI and MONGODB_AVAILABLE:
        try:
            _storage_backend = MongoDBStorage(MONGODB_URI, DB_NAME)
            return
        except Exception as e:
            print(f"⚠️ MongoDB connection failed: {e}")
            print("⚠️ Falling back to JSON file storage")
    
    _storage_backend = JSONFileStorage()


def get_storage():
    """Get the storage backend instance"""
    if _storage_backend is None:
        _init_storage()
    return _storage_backend


# Public API functions
def add_pending_link(entry: Dict) -> Optional[str]:
    """Add a pending link and return the inserted ID (string) or None"""
    return get_storage().add_pending_link(entry)


def update_pending_with_bot_msg_id(pending_id: str, bot_msg_id: int):
    """Update pending entry with bot message ID"""
    if pending_id:  # Only if we have a valid ID (MongoDB)
        get_storage().update_pending_with_bot_msg_id(pending_id, bot_msg_id)


def get_pending_links_for_user(user_id: int) -> List[Dict]:
    """Get all pending links for a specific user"""
    return get_storage().get_pending_links_for_user(user_id)


def delete_pending_link_by_bot_msg_id(bot_msg_id: int):
    """Delete a pending link by bot message ID"""
    get_storage().delete_pending_link_by_bot_msg_id(bot_msg_id)


def delete_pending_link_by_id(_id_str: str):
    """Delete a pending link by its ID"""
    if _id_str:  # Only if we have a valid ID (MongoDB)
        get_storage().delete_pending_link_by_id(_id_str)


def add_saved_link(entry: Dict):
    """Add a saved link"""
    get_storage().add_saved_link(entry)


def get_saved_links() -> List[Dict]:
    """Get all saved links"""
    return get_storage().get_saved_links()


def add_link_to_category(category_name: str, link: str):
    """Add a link to a category"""
    get_storage().add_link_to_category(category_name, link)


def get_categories() -> Dict:
    """Get all categories"""
    return get_storage().get_categories()


def delete_category(category_name: str):
    """Delete a category"""
    get_storage().delete_category(category_name)


def clear_categories():
    """Clear all categories"""
    get_storage().clear_categories()


def clear_saved_links():
    """Clear all saved links"""
    get_storage().clear_saved_links()


def load_onboarding_data() -> Dict:
    """Load onboarding data"""
    return get_storage().load_onboarding_data()


def save_onboarding_data(data: Dict):
    """Save onboarding data"""
    get_storage().save_onboarding_data(data)
