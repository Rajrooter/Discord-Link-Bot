# 🤖 Labour Bot - AI-Powered Discord Link Manager

A sophisticated Discord bot that helps students and researchers manage educational resources with GPT-5 AI-powered link evaluation and smart categorization.

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Discord.py](https://img.shields.io/badge/discord.py-2.3.2-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

### 🔗 Smart Link Management
- **AI-Powered Evaluation**: Automatic assessment of links using GPT-5 for educational value
- **Security Scanning**: Built-in phishing and spam detection
- **Interactive Saving**: React-based UI for saving and categorizing links
- **Smart Filtering**: Automatically ignores media files (images, GIFs, videos)

### 📚 Organization Tools
- **Custom Categories**: Organize links into unlimited custom categories
- **Search Functionality**: Quickly find links by keyword or category
- **Statistics Dashboard**: Track usage patterns and popular domains
- **Recent Links**: View your most recently saved resources

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
DISCORD_TOKEN=your_discord_bot_token_here
AI_INTEGRATIONS_OPENAI_API_KEY=your_openai_api_key
AI_INTEGRATIONS_OPENAI_BASE_URL=https://api.openai.com/v1
```

### 4. Set Up Discord Bot

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

### 5. Run the Bot

```bash
python main.py
```

## 🎮 Commands

### Link Management Commands

| Command | Description | Usage |
|---------|-------------|-------|
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
labour-bot/
├── main.py                 # Main bot file
├── .env                    # Environment variables (not in git)
├── .env.example            # Environment template
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── LICENSE                # MIT License
├── saved_links.json       # Saved links database
├── categories.json        # Categories database
├── onboarding_data.json   # Onboarding state
└── server_rules.txt       # Server rules
```

### Technology Stack

- **Framework**: discord.py 2.3.2
- **AI Integration**: OpenAI GPT-5 API
- **Storage**: JSON-based file storage
- **Async**: Python asyncio for non-blocking operations

## 🔒 Security Features

- **Phishing Detection**: Pre-AI keyword scanning for suspicious URLs
- **AI Security Analysis**: GPT-5 powered link safety evaluation
- **Spam Prevention**: Automatic filtering of common spam patterns
- **Media Filtering**: Ignores non-educational media content

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
- JSON storage is not suitable for very large datasets (>10,000 links)

## 📝 Roadmap

- [ ] Database integration (PostgreSQL/MongoDB)
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
- [OpenAI](https://openai.com/) for GPT-5 API
- [Replit](https://replit.com/) for AI Integrations service

## 📧 Support

- Join our [Discord Server](https://discord.gg/TYvWXF3U9N) for community support
- Email: rajaryan16610@gmail.com

## ⚠️ Disclaimer

This bot stores links and user data in local JSON files. Ensure you comply with Discord's Terms of Service and your local data protection regulations. The AI analysis is provided as-is and should not be solely relied upon for security decisions.

---

Made with ❤️ by [RAJ ARYAN] | [GitHub](https://github.com/Rajrooter) | [Discord](https://discord.gg/TYvWXF3U9N)
