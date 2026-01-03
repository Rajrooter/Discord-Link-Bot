# 🤖 Labour Bot - AI-Powered Discord Link Manager

A sophisticated Discord bot that helps students and researchers manage educational resources with GPT-5 AI-powered link evaluation and smart categorization.

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

### 🔗 Smart Link Management
- **AI-Powered Evaluation**: Automatic assessment of links using Google Gemini 2.0 for educational value
- **Security Scanning**: Built-in phishing and spam detection with AI safety analysis
- **Interactive Button UI**: Modern Discord buttons for Save/Ignore with confirmation flows
- **Persistent Storage**: MongoDB support with JSON file fallback for reliable data persistence
- **Smart Filtering**: Automatically ignores media files (images, GIFs, videos)
- **Auto-Delete**: Configurable auto-deletion of unresponded links to keep channels clean

### 📚 Organization Tools
- **Custom Categories**: Organize links into unlimited custom categories
- **Pending Links**: Review accumulated links from burst periods with `!pendinglinks`
- **Search Functionality**: Quickly find links by keyword or category
- **Statistics Dashboard**: Track usage patterns and popular domains
- **Recent Links**: View your most recently saved resources

### 🗄️ Storage Options
- **MongoDB**: Production-ready database with proper IDs and queries
- **JSON Files**: Automatic fallback for development and testing
- **Dual-Mode**: Seamlessly switches based on configuration

### 👥 Member Onboarding
- **Automated Welcome**: DM-based onboarding flow for new members
- **Role Assignment**: Automatic role assignment based on member information
- **Rule Distribution**: Automated server rules delivery

### 🎨 Beautiful UI/UX
- **Custom Embeds**: Adorable, color-coded Discord embeds
- **Interactive Commands**: React-based interactions for intuitive navigation
- **Help System**: Comprehensive help command with command details

## 📋 Prerequisites

- Python 3.8 or higher
- Discord Bot Token ([Get one here](https://discord.com/developers/applications))
- OpenAI API access (via Replit AI Integrations or direct OpenAI API)

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/labour-bot.git
cd labour-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
# Discord Bot Token
DISCORD_TOKEN=your_discord_bot_token_here

# Google Gemini API Key (for AI link analysis)
GEMINI_API_KEY=your_gemini_api_key

# Auto-delete configuration
AUTO_DELETE_ENABLED=1
AUTO_DELETE_AFTER=5

# MongoDB configuration (optional - uses JSON files if not set)
# IMPORTANT: URL-encode special characters in password (e.g., # -> %23)
# Example: mongodb+srv://user:pass%23word@cluster.mongodb.net/
# MONGODB_URI=mongodb://localhost:27017
# DB_NAME=discord_link_manager
```

**⚠️ Security Note:** If you accidentally leak your credentials in commits:
1. Immediately rotate your Discord bot token and API keys
2. Update MongoDB user password if MONGODB_URI was exposed
3. Review commit history and force-push if necessary

### 4. (Optional) Set Up MongoDB

The bot supports two storage modes:

#### Option A: MongoDB (Recommended for Production)
- Provides persistent storage with proper IDs and queries
- Better for multiple bot instances and data integrity
- Set `MONGODB_URI` in `.env` to enable

**Example MongoDB Atlas setup:**
1. Create free cluster at [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create database user and get connection string
3. **URL-encode special characters** in password (e.g., `p@ss#word` → `p%40ss%23word`)
4. Set environment variables:
   ```env
   MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
   DB_NAME=discord_link_manager
   ```

**Test your MongoDB connection:**
```bash
python test_mongo.py
```

#### Option B: JSON Files (Default)
- Automatic fallback if `MONGODB_URI` is not set
- Good for development and testing
- Files: `pending_links.json`, `saved_links.json`, `categories.json`, `onboarding_data.json`

### 5. Set Up Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Navigate to the "Bot" section
4. Enable these Privileged Gateway Intents:
   - Message Content Intent
   - Server Members Intent
5. Copy your bot token and add it to `.env`
6. Use this invite link (replace CLIENT_ID with your application ID):
   ```
   https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=8&scope=bot
   ```

### 6. Run the Bot

```bash
python main.py
```

### 7. Testing

**Local Development Testing:**
1. Set up test MongoDB instance or use JSON file mode
2. Post a link in any channel: `https://example.com/test`
3. Bot should respond with AI analysis and Save/Ignore buttons
4. Click buttons to test functionality
5. Use `!pendinglinks` to test pending link retrieval
6. Test auto-delete by waiting (default 5 seconds)

**MongoDB Connection Test:**
```bash
python test_mongo.py
```

## 🎮 Commands

### Link Management Commands

| Command | Description | Usage |
|---------|-------------|-------|
| `!pendinglinks` | Review your pending links from DB | `!pendinglinks` |
| `!category [name]` | Assign category to pending link | `!category Computer Science` |
| `!cancel` | Cancel pending link save | `!cancel` |
| `!getlinks [category]` | Retrieve all links or by category | `!getlinks` or `!getlinks Python` |
| `!categories` | List all categories | `!categories` |
| `!deletelink [number]` | Delete a specific link | `!deletelink 5` |
| `!deletecategory [name]` | Delete category and its links | `!deletecategory Physics` |
| `!clearlinks` | Clear all links (Admin only) | `!clearlinks` |
| `!searchlinks [term]` | Search for links | `!searchlinks machine learning` |
| `!analyze [url]` | Get AI analysis of a link | `!analyze https://example.com` |
| `!stats` | Show statistics | `!stats` |
| `!recent` | Show 5 most recent links | `!recent` |

### General Commands

| Command | Description |
|---------|-------------|
| `!help` | Show all commands |
| `!help [command]` | Get help for specific command |

## 🔧 Configuration

### Customizing Categories

Edit `categories.json` to pre-define categories:

```json
{
  "Computer Science": [],
  "Mathematics": [],
  "Research Papers": []
}
```

### Customizing Server Rules

Edit `server_rules.txt` to set your server rules for onboarding.

### Customizing Ignored Media Extensions

In `main.py`, modify the `IGNORED_EXTENSIONS` list:

```python
IGNORED_EXTENSIONS = [
    '.gif', '.png', '.jpg', '.jpeg', '.webp', '.bmp'
]
```

## 🏗️ Architecture

### File Structure

```
discord-link-manager-bot/
├── main.py                 # Main bot code
├── storage.py             # MongoDB/JSON storage adapter
├── test_mongo.py          # MongoDB connection test script
├── requirements.txt       # Python dependencies
├── runtime.txt            # Python version
├── railway.toml           # Railway configuration
├── .env                   # Environment variables (not committed)
├── .env.example           # Template for environment variables
├── .gitignore            # Git ignore rules
├── README.md             # Documentation
└── LICENSE               # License file
```

### Technology Stack

- **Framework**: discord.py 2.3.2
- **AI Integration**: Google Gemini 2.0 Flash (Free)
- **Storage**: MongoDB with JSON file fallback
- **Database**: pymongo for MongoDB operations
- **Async**: Python asyncio for non-blocking operations
- **UI**: Discord Buttons (discord.ui.View) for interactive elements

## 🔒 Security Features

- **Phishing Detection**: Pre-AI keyword scanning for suspicious URLs
- **AI Security Analysis**: Google Gemini powered link safety evaluation (Safe/Suspect/Unsafe)
- **Spam Prevention**: Automatic filtering of common spam patterns
- **Media Filtering**: Ignores non-educational media content
- **Confirmation Flows**: Double-confirmation for destructive actions

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add docstrings to new functions
- Test thoroughly before submitting PR
- Update README if adding new features

## 🐛 Known Issues

- Large servers may experience rate limiting with onboarding
- AI analysis may timeout on slow connections
- JSON file storage has limitations for concurrent access (use MongoDB for production)

## 📝 Roadmap

- [x] Database integration (MongoDB with JSON fallback)
- [x] Interactive button UI for link management
- [ ] Web dashboard for link management
- [ ] Link expiration and archiving
- [ ] Export links to various formats (CSV, PDF)
- [ ] Advanced analytics and visualization
- [ ] Multi-server support with isolated data
- [ ] Collaborative categorization

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.md) file for details.

## 🙏 Acknowledgments

- [discord.py](https://github.com/Rapptz/discord.py) for the Discord API wrapper
- [discord.py](https://github.com/Rapptz/discord.py) for the Discord API wrapper
- [Google Gemini](https://ai.google.dev/) for AI-powered link analysis
- [MongoDB](https://www.mongodb.com/) for database support

## 📧 Support

- Join our [Discord Server](https://discord.gg/TYvWXF3U9N) for community support
- Email: rajaryan16610@gmail.com

## ⚠️ Disclaimer

This bot stores links and user data. Storage can be in local JSON files or MongoDB database. Ensure you comply with Discord's Terms of Service and your local data protection regulations. The AI analysis is provided as-is and should not be solely relied upon for security decisions.

---

Made with ❤️ by [RAJ ARYAN] | [GitHub](https://github.com/Rajrooter) | [Discord](https://discord.gg/TYvWXF3U9N)
