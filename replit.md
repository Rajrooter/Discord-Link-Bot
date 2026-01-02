Discord Bot Link Manager (Labour Bot)
Overview
Labour Bot is a high-performance educational companion designed to streamline the way students and researchers manage digital resources. By leveraging GPT-5 AI technology, Labour automatically evaluates shared URLs to determine their educational value, helping users build a curated library of study materials.

Key Features:
AI-Powered Evaluation: Instant guidance on the importance of shared links for academic success.
Smart Categorization: Seamlessly organize links into custom categories with simple commands.
Onboarding System: Professional member verification to ensure a focused community environment.
Adorable UI/UX: Beautifully crafted Discord embeds that make studying feel more engaging.
Resource Management: Easy retrieval, searching, and filtering of all saved academic assets.
User Preferences
Preferred communication style: Simple, everyday language.

System Architecture
Bot Framework
Technology: discord.py library with Python
Command System: Hybrid prefix system supporting both ! commands and @mention triggers
Intents: Configured for message content and reactions to enable URL detection and interaction handling
Rationale: discord.py provides robust Discord API integration with built-in command handling and event management
Data Storage
Link Storage: JSON file (saved_links.json) storing link metadata including URL, timestamp, author, and category
Categories: JSON file (categories.json) organizing links into user-defined categories
Legacy Support: Handles migration from old text-based storage (saved_links.txt)
Rationale: File-based storage provides simplicity for small-scale deployments without requiring external database setup
URL Processing
Detection: Regular expression pattern matching to identify URLs in messages
Filtering: Automatic exclusion of media files (images, videos, audio) based on file extensions
Validation: URL parsing and validation using Python's urllib.parse module
Rationale: Client-side URL detection enables real-time processing without external API dependencies
Interaction Model
Reaction-Based: Uses Discord emoji reactions for user interactions (likely for saving/categorizing links)
Command Interface: Traditional text commands with flexible prefix handling
Asynchronous Processing: Built on asyncio for non-blocking Discord event handling
Rationale: Reaction-based UI provides intuitive user experience while maintaining command flexibility
Configuration Management
Environment Variables: Token and sensitive configuration stored in environment variables
JSON Configuration: User preferences and categories stored in editable JSON files
Hot Reloading: Configuration changes can be applied without bot restart
Rationale: Separates secrets from code while allowing dynamic configuration updates
External Dependencies
Discord Integration
discord.py: Primary library for Discord API interaction and bot functionality
Discord Developer Portal: Bot token and application management
Python Libraries
asyncio: Asynchronous programming support for Discord event handling
json: JSON file parsing and manipulation for data storage
re: Regular expression support for URL pattern matching
urllib.parse: URL parsing and validation utilities
datetime: Timestamp generation for link metadata
python-dotenv: Environment variable loading from .env files
Infrastructure
Replit: Hosting platform with integrated secret management
File System: Local storage for JSON data files and configuration
