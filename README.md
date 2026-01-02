# 🔗 Discord Link Manager Bot

A powerful and efficient Discord bot designed to manage, organize, and moderate links shared within your Discord server. This bot provides comprehensive link management capabilities, spam protection, and analytics to keep your community safe and organized.

---

## 📋 Table of Contents

- [Features](#-features)
- [Demo](#-demo)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Commands](#-commands)
- [Architecture](#-architecture)
- [Contributing](#-contributing)
- [License](#-license)
- [Support](#-support)
- [Acknowledgments](#-acknowledgments)

---

## ✨ Features

### Core Functionality
- **Link Detection & Storage**: Automatically detects and stores all links shared in the server
- **Link Categories**: Organize links into custom categories (Social Media, Documentation, Resources, etc.)
- **Spam Protection**: Identifies and blocks malicious or spam links
- **Link Analytics**: Track click counts, most shared domains, and link engagement
- **Blacklist Management**: Maintain a blacklist of prohibited domains and URLs
- **Whitelist System**: Configure trusted domains that bypass restrictions

### Advanced Capabilities
- **URL Shortening**: Create custom short links for frequently shared resources
- **Link Expiry**: Set automatic expiration for time-sensitive links
- **Permission System**: Role-based access control for link management
- **Export Functionality**: Export link databases to CSV/JSON formats
- **Search & Filter**: Advanced search capabilities across stored links
- **Duplicate Detection**: Prevents spam by identifying previously shared links

### Moderation Tools
- **Auto-Moderation**: Automatic removal of suspicious links
- **Link Reports**: Users can report problematic links for review
- **Audit Logs**: Comprehensive logging of all link-related activities
- **Rate Limiting**: Prevents link spam through configurable rate limits

---

## 🎬 Demo
Sending random link on the channel to any server

<img width="903" height="203" alt="image" src="https://github.com/user-attachments/assets/19c38d6b-3ea6-4ea5-99ec-c92bf632e20f" />
How the bot responded 

<img width="1143" height="347" alt="image" src="https://github.com/user-attachments/assets/0d4f1529-2c4b-47f3-bdfd-062c05210817" />

## 🔧 Prerequisites

Before installation, ensure you have the following:

- **Python**: Version 3.8 or higher
- **Discord Bot Token**: Obtained from [Discord Developer Portal](https://discord.com/developers/applications)
- **Database**: SQLite (included) or PostgreSQL for production
- **Dependencies**: Listed in `requirements.txt`
- **Operating System**: Windows, macOS, or Linux

**Recommended System Specifications:**
- RAM: Minimum 512MB, Recommended 1GB
- Storage: 100MB for bot files + database storage
- Network: Stable internet connection

---

## 📥 Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/discord-link-manager-bot.git
cd discord-link-manager-bot
```

### Step 2: Set Up Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the root directory:

```env
DISCORD_TOKEN=your_bot_token_here
BOT_PREFIX=!
LOG_LEVEL=INFO
ADMIN_ROLE_ID=your_admin_role_id
MODERATOR_ROLE_ID=your_moderator_role_id
```

### Step 5: Initialize Database

```bash
python setup_database.py
```

### Step 6: Run the Bot

```bash
python main.py
```

---

## ⚙️ Configuration

### config.yml Structure

```yaml
bot:
  prefix: "!"
  status: "Managing links | !help"
  activity_type: "watching"

links:
  max_per_message: 5
  auto_categorize: true
  default_category: "General"
  
moderation:
  auto_delete_suspicious: true
  suspicious_keywords: ["click here", "free money", "limited offer"]
  rate_limit:
    messages: 10
    per_seconds: 60
  
categories:
  - "Social Media"
  - "Documentation"
  - "Resources"
  - "Articles"
  - "Videos"
  - "Other"
```

 ### Customization Options

**1. Prefix Configuration**
- Change the command prefix in `config.yml` under `bot.prefix`
- Default: `!`

**2. Category Management**
- Add custom categories in the `categories` section
- Categories help organize links by type

---

## 🎮 Usage

<img width="1064" height="389" alt="image" src="https://github.com/user-attachments/assets/f8622a1f-f12d-44f0-a90b-e5d6f834dfda" />



## 📜 Commands

### Complete Command Reference

| Command | Permission | Description |
|---------|-----------|-------------|
| `!help` | Everyone | Display help menu with all commands |
| `!links [page]` | Everyone | View paginated list of recent links |
| `!link search <query>` | Everyone | Search links by URL, title, or user |
| `!link info <id>` | Everyone | Display detailed link information |
| `!link category <name>` | Everyone | View links in specific category |
| `!link report <id> <reason>` | Everyone | Report suspicious link |
| `!link delete <id>` | Moderator | Remove link from database |
| `!link blacklist add <domain>` | Moderator | Block domain server-wide |
| `!link blacklist remove <domain>` | Moderator | Unblock domain |
| `!link whitelist add <domain>` | Moderator | Trust domain (bypass filters) |
| `!link whitelist remove <domain>` | Moderator | Remove from whitelist |
| `!link stats [user]` | Moderator | View statistics for server or user |
| `!link export <format>` | Admin | Export database (csv/json) |
| `!link purge <days>` | Admin | Delete links older than X days |
| `!link config show` | Admin | Display current configuration |
| `!link config set <key> <value>` | Admin | Modify bot settings |

---


### Technology Stack

- **Framework**: Discord.py (Python Discord API wrapper)
- **Database**: SQLite / PostgreSQL
- **ORM**: SQLAlchemy
- **URL Validation**: validators, urllib
- **Configuration**: PyYAML
- **Environment Management**: python-dotenv
- **Logging**: Python logging module

### Database Schema

**Links Table:**
- `id` (Primary Key)
- `url` (Text)
- `short_url` (Text, nullable)
- `user_id` (BigInt)
- `guild_id` (BigInt)
- `channel_id` (BigInt)
- `category` (Text)
- `timestamp` (DateTime)
- `clicks` (Integer)
- `is_active` (Boolean)

**Blacklist Table:**
- `id` (Primary Key)
- `domain` (Text, unique)
- `added_by` (BigInt)
- `reason` (Text)
- `timestamp` (DateTime)

---

## 🤝 Contributing

Contributions are welcome and appreciated! Please follow these guidelines:

### How to Contribute

1. **Fork the Repository**
   ```bash
   git clone https://github.com/yourusername/discord-link-manager-bot.git
   ```

2. **Create a Feature Branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Commit Your Changes**
   ```bash
   git commit -m "Add amazing feature"
   ```

4. **Push to Branch**
   ```bash
   git push origin feature/amazing-feature
   ```

5. **Open a Pull Request**
   - Provide clear description of changes
   - Reference any related issues
   - Ensure all tests pass

### Contribution Guidelines

- Follow PEP 8 style guidelines
- Write clear, descriptive commit messages
- Add tests for new features
- Update documentation as needed
- Be respectful and constructive in discussions

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2024 [Your Name]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files...
```

---

## 💬 Support

### Getting Help

- **Discord**: [Join our support server]( https://discord.gg/TYvWXF3U9N)

### Frequently Asked Questions

**Q: How do I get a Discord Bot Token?**
A: Visit the [Discord Developer Portal](https://discord.com/developers/applications), create a new application, navigate to the Bot section, and copy the token.

**Q: Can I use this bot on multiple servers?**
A: Yes! The bot supports multi-server deployment with isolated data per server.

**Q: How do I update the bot?**
A: Pull the latest changes with `git pull` and restart the bot.

---

## 🙏 Acknowledgments

- **Discord.py Community**: For the excellent Discord API wrapper
- **Contributors**: Thank you to all who have contributed to this project
- **Open Source Libraries**: All dependencies that made this project possible
- **Beta Testers**: Special thanks to our testing community

---

## 📊 Project Stats

![GitHub stars](https://img.shields.io/github/stars/yourusername/discord-link-manager-bot?style=social)
![GitHub forks](https://img.shields.io/github/forks/yourusername/discord-link-manager-bot?style=social)
![GitHub issues](https://img.shields.io/github/issues/yourusername/discord-link-manager-bot)
![GitHub pull requests](https://img.shields.io/github/issues-pr/yourusername/discord-link-manager-bot)

---
