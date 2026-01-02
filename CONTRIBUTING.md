# Contributing to Discord Link Manager Bot

Thank you for considering contributing to the Discord Link Manager Bot! This document provides comprehensive guidelines to help you contribute effectively.

---

## 📖 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Contribution Workflow](#contribution-workflow)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)
- [Issue Guidelines](#issue-guidelines)
- [Community](#community)

---

## 📜 Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inspiring community for all. By participating in this project, you agree to:

- **Be Respectful**: Treat all community members with respect and kindness
- **Be Constructive**: Provide helpful feedback and be open to receiving it
- **Be Inclusive**: Welcome contributors of all backgrounds and experience levels
- **Be Professional**: Maintain professional conduct in all interactions
- **Be Patient**: Remember that everyone is learning and growing

### Unacceptable Behavior

- Harassment, discrimination, or offensive comments
- Trolling, insulting remarks, or personal attacks
- Publishing others' private information
- Any conduct that would be inappropriate in a professional setting

**Reporting**: If you experience or witness unacceptable behavior, please report it to [maintainer@email.com].

---

## 🚀 Getting Started

### Prerequisites

Before contributing, ensure you have:

- **Python 3.8+** installed
- **Git** for version control
- **Discord Developer Account** for testing
- **Text Editor/IDE** (VS Code, PyCharm, etc.)
- **Basic Knowledge** of Python and Discord.py

### Find an Issue to Work On

1. **Browse Issues**: Check the [issue tracker](https://github.com/yourusername/discord-link-manager-bot/issues)
2. **Good First Issues**: Look for issues labeled `good first issue` or `beginner-friendly`
3. **Ask Questions**: Comment on issues if you need clarification
4. **Claim an Issue**: Comment "I'd like to work on this" to avoid duplicate efforts

### Types of Contributions

We welcome various types of contributions:

- **Bug Fixes**: Resolve existing bugs
- **New Features**: Implement new functionality
- **Documentation**: Improve or expand documentation
- **Testing**: Add or improve test coverage
- **Code Quality**: Refactor code for better performance
- **UI/UX**: Enhance user experience
- **Translation**: Add language support

---

## 💻 Development Setup

### Step 1: Fork and Clone

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/discord-link-manager-bot.git
cd discord-link-manager-bot

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/discord-link-manager-bot.git
```

### Step 2: Create Development Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies
```

### Step 3: Configure Development Environment

Create a `.env.dev` file:

```env
DISCORD_TOKEN=your_test_bot_token
BOT_PREFIX=!dev
DATABASE_URL=sqlite:///dev_links.db
LOG_LEVEL=DEBUG
DEVELOPMENT_MODE=true
```

### Step 4: Set Up Pre-commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install
```

### Step 5: Run Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_link_management.py
```

---

## 🔄 Contribution Workflow

### 1. Sync Your Fork

```bash
# Fetch upstream changes
git fetch upstream

# Merge upstream changes into your main branch
git checkout main
git merge upstream/main
```

### 2. Create a Feature Branch

```bash
# Create and switch to new branch
git checkout -b feature/your-feature-name

# Branch naming conventions:
# feature/add-link-categories
# bugfix/fix-duplicate-detection
# docs/update-installation-guide
# refactor/optimize-database-queries
```

### 3. Make Your Changes

- Write clean, readable code
- Follow the coding standards (see below)
- Add comments for complex logic
- Update documentation as needed
- Write tests for new features

### 4. Test Your Changes

```bash
# Run linting
flake8 .

# Run type checking
mypy .

# Run tests
pytest

# Check formatting
black --check .

# Auto-format code
black .
```

### 5. Commit Your Changes

```bash
# Stage changes
git add .

# Commit with descriptive message
git commit -m "feat: add link category filtering

- Implement category-based filtering
- Add tests for category functionality
- Update documentation"
```

**Commit Message Format:**

```
<type>: <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance tasks

### 6. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 7. Create Pull Request

1. Go to your fork on GitHub
2. Click "Compare & pull request"
3. Fill out the PR template completely
4. Link related issues using keywords: `Fixes #123`, `Closes #456`
5. Request review from maintainers

---

## 📏 Coding Standards

### Python Style Guide

Follow **PEP 8** standards with these specific guidelines:

**Naming Conventions:**
```python
# Classes: PascalCase
class LinkManager:
    pass

# Functions and variables: snake_case
def validate_url(url_string):
    is_valid = True
    return is_valid

# Constants: UPPER_CASE
MAX_LINKS_PER_USER = 100

# Private methods: _leading_underscore
def _internal_helper():
    pass
```

**Import Organization:**
```python
# Standard library imports
import os
import sys
from typing import List, Optional

# Third-party imports
import discord
from discord.ext import commands

# Local imports
from utils.validators import validate_url
from models.link import Link
```

**Code Formatting:**
- **Line Length**: Maximum 88 characters (Black default)
- **Indentation**: 4 spaces
- **Quotes**: Prefer double quotes for strings
- **Trailing Commas**: Use in multi-line structures
- **Whitespace**: Follow PEP 8 guidelines

**Type Hints:**
```python
def process_link(url: str, user_id: int) -> Optional[Link]:
    """Process and store a link.
    
    Args:
        url: The URL to process
        user_id: Discord user ID
        
    Returns:
        Link object if successful, None otherwise
    """
    pass
```

**Error Handling:**
```python
# Specific exception handling
try:
    link = validate_url(url)
except ValidationError as e:
    logger.error(f"Validation failed: {e}")
    raise
except Exception as e:
    logger.exception("Unexpected error occurred")
    return None
```

### Discord.py Best Practices

**Cog Structure:**
```python
from discord.ext import commands

class LinkManagement(commands.Cog):
    """Cog for managing links."""
    
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command()
    async def link(self, ctx, action: str):
        """Main link command."""
        pass
        
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for links in messages."""
        pass

async def setup(bot):
    await bot.add_cog(LinkManagement(bot))
```

**Async/Await Usage:**
```python
# Correct
async def fetch_user_data(user_id: int) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"/api/users/{user_id}") as resp:
            return await resp.json()

# Avoid blocking operations
# Bad: time.sleep(5)
# Good: await asyncio.sleep(5)
```

---

## 🧪 Testing Guidelines

### Test Structure

```python
import pytest
from unittest.mock import Mock, AsyncMock
from utils.validators import validate_url

class TestURLValidation:
    """Test suite for URL validation."""
    
    def test_valid_url(self):
        """Test that valid URLs are accepted."""
        assert validate_url("https://example.com") is True
        
    def test_invalid_url(self):
        """Test that invalid URLs are rejected."""
        assert validate_url("not a url") is False
        
    @pytest.mark.asyncio
    async def test_async_function(self):
        """Test async functionality."""
        result = await async_function()
        assert result is not None
```

### Test Coverage Requirements

- **Minimum Coverage**: 80% overall
- **Critical Functions**: 100% coverage
- **New Features**: Must include tests
- **Bug Fixes**: Add regression tests

### Running Tests

```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_validators.py::TestURLValidation::test_valid_url

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Run only fast tests (skip slow integration tests)
pytest -m "not slow"

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x
```

---

## 📚 Documentation

### Code Documentation

**Docstrings:**
```python
def calculate_link_score(link: Link, factors: dict) -> float:
    """Calculate a quality score for a link.
    
    This function analyzes multiple factors to determine the 
    quality and relevance of a shared link.
    
    Args:
        link: Link object to score
        factors: Dictionary containing scoring parameters
            - clicks: int, number of clicks
            - age: int, days since posting
            - reports: int, number of reports
            
    Returns:
        Float score between 0.0 and 100.0
        
    Raises:
        ValueError: If link object is invalid
        
    Example:
        >>> link = Link(url="https://example.com")
        >>> score = calculate_link_score(link, {"clicks": 50})
        >>> print(score)
        85.5
    """
    pass
```

### README Updates

When adding features:
- Update the Features section
- Add new commands to the Commands table
- Update usage examples
- Add to FAQ if needed

### Wiki and Guides

For major features, create wiki pages:
- **User Guides**: Step-by-step tutorials
- **Developer Guides**: Technical documentation
- **API Reference**: Detailed API documentation
- **Troubleshooting**: Common issues and solutions

---

## 🔀 Pull Request Process

### Before Submitting

**Checklist:**
- [ ] Code follows style guidelines
- [ ] All tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow conventions
- [ ] No merge conflicts with main branch
- [ ] Self-review completed

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactoring
- [ ] Other: ___________

## Related Issues
Fixes #(issue number)

## Testing
Describe testing performed

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Code follows style guide
- [ ] Tests pass
- [ ] Documentation updated
```

### Review Process

1. **Automated Checks**: CI/CD pipeline runs tests
2. **Code Review**: Maintainer reviews code
3. **Feedback**: Address any requested changes
4. **Approval**: PR approved by maintainer
5. **Merge**: PR merged into main branch

### After Merging

- Update your local repository
- Close related issues
- Celebrate your contribution! 🎉

---

## 🐛 Issue Guidelines

### Creating Issues

**Bug Reports:**
```markdown
**Bug Description**
Clear description of the bug

**Steps to Reproduce**
1. Step one
2. Step two
3. See error

**Expected Behavior**
What should happen

**Actual Behavior**
What actually happens

**Environment**
- OS: Windows 10
- Python: 3.9
- Discord.py: 2.0

**Screenshots/Logs**
Include if applicable
```

**Feature Requests:**
```markdown
**Feature Description**
Clear description of the feature

**Problem it Solves**
What problem does this address?

**Proposed Solution**
How should it work?

**Alternatives Considered**
Other approaches you've thought of

**Additional Context**
Any other relevant information
```

### Issue Labels

- `bug`: Something isn't working
- `enhancement`: New feature request
- `documentation`: Documentation improvements
- `good first issue`: Suitable for beginners
- `help wanted`: Extra attention needed
- `question`: Further information requested
- `wontfix`: Will not be worked on
- `duplicate`: Already reported
- `priority: high`: Urgent issues

---

## 👥 Community

### Getting Help

- **Discord Server**: [Join here](https://discord.gg/TYvWXF3U9N)

### Recognition

Contributors are recognized in:
- README.md acknowledgments
- CONTRIBUTORS.md file
- Release notes
- Social media shoutouts

### Communication Channels

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: General questions and ideas
- **Discord**: Real-time community chat
- **Email**: For private matters only

---

## 📝 Additional Resources

- [Python Best Practices](https://docs.python-guide.org/)
- [Discord.py Documentation](https://discordpy.readthedocs.io/)
- [Git Workflow Guide](https://guides.github.com/introduction/flow/)
- [Writing Good Commit Messages](https://chris.beams.io/posts/git-commit/)

---

## 🙏 Thank You

Thank you for contributing to Discord Link Manager Bot! Every contribution, no matter how small, helps make this project better for everyone.

**Questions?** Don't hesitate to ask! We're here to help.

---

*Last Updated: January 2026*
