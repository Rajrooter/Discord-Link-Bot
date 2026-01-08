#!/usr/bin/env python3
"""
Test script to verify MongoDB connectivity.
Run this before deploying to ensure MongoDB is properly configured.

Usage:
    python test_mongo.py
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def check_mongodb_connection() -> bool:
    """Return True on success, False on failure."""
    mongodb_uri = os.environ.get("MONGODB_URI")
    db_name = os.environ.get("DB_NAME", "discord_link_manager")

    if not mongodb_uri:
        print("❌ MONGODB_URI not set in environment variables")
        print("💡 Set MONGODB_URI in your .env file to test MongoDB connection")
        print("   Example: MONGODB_URI=mongodb://localhost:27017")
        return False

    print("🔍 Testing MongoDB connection...")
    print(f"   URI: {mongodb_uri[:20]}... (truncated for security)")
    print(f"   Database: {db_name}")

    try:
        from pymongo import MongoClient
    except ImportError:
        print("❌ pymongo not installed")
        print("💡 Install with: pip install pymongo")
        return False

    try:
        # Attempt connection
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)

        # Test connection by pinging
        client.admin.command("ping")
        print("✅ MongoDB connection successful!")

        # Test database access
        db = client[db_name]
        collections = db.list_collection_names()
        print(f"✅ Database '{db_name}' accessible")
        print(f"   Existing collections: {collections if collections else 'None (new database)'}")

        # Test basic operations
        test_collection = db["_connection_test"]
        test_doc = {"test": "connection", "timestamp": "test"}
        result = test_collection.insert_one(test_doc)
        print(f"✅ Write test successful (ID: {result.inserted_id})")

        # Clean up test document
        test_collection.delete_one({"_id": result.inserted_id})
        print("✅ Delete test successful")

        client.close()
        print("\n🎉 All MongoDB tests passed!")
        return True

    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print("\n💡 Troubleshooting tips:")
        print("   1. Check if MongoDB URI is correct")
        print("   2. Ensure special characters in password are URL-encoded (# → %23)")
        print("   3. Check if MongoDB server is running and accessible")
        print("   4. Verify network connectivity and firewall settings")
        print("   5. Confirm MongoDB user has proper permissions")
        return False


def test_mongodb_connection():
    """Pytest entrypoint: assert the connection check passes (no return)."""
    assert check_mongodb_connection()


if __name__ == "__main__":
    print("=" * 60)
    print("MongoDB Connection Test for Discord Link Manager Bot")
    print("=" * 60)
    print()

    success = check_mongodb_connection()

    print()
    print("=" * 60)

    sys.exit(0 if success else 1)
