# CTF Task-Tracker Discord Bot

A Discord bot to manage CTF challenges, track who's working on what, and organize write-ups in a GitHub repository with automatic GitHub scaffolding and Git workflow management.

## Features

- **CTF Management**: Create, track, and archive different CTF competitions
- **Challenge Tracking**: Organize challenges by category with customizable attributes
- **GitHub Integration**: 
  - Automatic folder structure scaffolding for each challenge
  - Branch creation for claims to prevent conflicts
  - Solved markers and writeup templates
  - Automatic privacy management (private during active CTF, can be made public after)
- **Team Coordination**:
  - Real-time board updates showing who's working on what
  - Claim/unclaim system with conflict prevention
  - Solved challenge tracking
- **Git Workflow Automation**:
  - Automatic DMs with contextual Git instructions
  - Branch management to prevent conflicts
  - Step-by-step merge instructions when challenges are solved
- **Role-Based Permissions**: Team lead controls for CTF management
- **Bulk Operations**: Add multiple challenges at once with simple formatting

## Architecture

```
┌────────────┐
│ Discord UI │  ← slash commands & button clicks
└──────┬─────┘
       │      asyncio
┌──────▼──────────────────────────────────────────┐
│ bot.py  (Discord client + logging bootstrap)    │
│   ├─ cogs.ctf        – CTF-lifecycle commands   │
│   ├─ cogs.challenge  – challenge CRUD & buttons │
│   ├─ views.py        – board embed + UI layer   │
│   ├─ db.py           – async SQLite DAO         │
│   ├─ github_utils.py – PyGithub (thread-pooled) │
│   └─ logs/bot.log    – rotating diagnostics     │
└────────┬────────────────────────────────────────┘
         │         thread-pool tasks
┌────────▼────────┐  ┌──────────────┐
│ SQLite (tasks & │  │ GitHub Repo   │
│  state tables)  │  │  (write-ups) │
└─────────────────┘  └──────────────┘
```

## Setup

### Prerequisites

- Python 3.10+
- A Discord bot token (https://discord.com/developers/applications)
- A GitHub Personal Access Token with repo scope
- A dedicated Discord server with appropriate channels

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd CTF-Task-Tracker-bot
   ```

2. Install the required dependencies:
   ```bash
   pip install -r ctf_task_tracker_bot/requirements.txt
   ```

3. Copy `ctf_task_tracker_bot/env.example` to `.env` in the same directory and fill in your details:
   ```bash
   cp ctf_task_tracker_bot/env.example ctf_task_tracker_bot/.env
   ```

4. Edit the `.env` file with your settings:

   ```ini
   # Discord Bot Token from https://discord.com/developers/applications
   DISCORD_TOKEN=your_discord_token_here
   
   # GitHub Personal Access Token (needs repo scope)
   GITHUB_TOKEN=your_github_token_here
   
   # GitHub repository in format "username/repo"
   GITHUB_REPO=username/repository_name
   
   # Discord channel ID for the CTF board
   BOARD_CHANNEL_ID=1234567890123456789
   
   # Discord guild ID for slash command registration
   DEFAULT_GUILD=1234567890123456789
   
   # Role name for CTF administrators (can be customized)
   LEAD_ROLE_NAME=CTF Lead
   
   # Logging level (DEBUG, INFO, WARNING, ERROR)
   LOG_LEVEL=INFO
   ```

### Discord Server Setup

1. Create a dedicated `#ctf-board` channel for the bot to post the task board
2. Find the channel ID (right-click channel → Copy ID) and add it to `.env`
3. Create a `CTF Lead` role (or customize the name in `.env`) for users who can manage CTFs
4. Find your Discord server ID (right-click server → Copy ID) and add it to `.env` as DEFAULT_GUILD
5. Give the bot these permissions:
   - `Send Messages`
   - `Embed Links`
   - `Manage Messages`
   - `Read Message History`
   - `Use Application Commands`
   - `Mention @everyone, @here, and All Roles`

### GitHub Setup

1. Create a new GitHub repository to store CTF challenges and write-ups
2. Generate a Personal Access Token with `repo` scope at https://github.com/settings/tokens
3. Add the repository name (`username/repo`) and token to the `.env` file

## Usage

### Starting the Bot

```bash
cd ctf_task_tracker_bot
python bot.py
```

Once started, the bot will automatically:
- Initialize the database if it doesn't exist
- Register slash commands with Discord
- Create a board message in the configured channel
- Set up hourly automatic board refreshes

### Commands

| Command                                    | Permission      | Description                                      |
| ------------------------------------------ | --------------- | ------------------------------------------------ |
| `/ctf_add name:<str> year:<int>`           | Lead            | Start a new CTF, reset challenges, set repo private |
| `/ctf_done`                                | Lead            | Mark the current CTF as finished                 |
| `/ctf_publish`                             | Lead            | Make the repository public when no active CTF    |
| `/ctf_delete name year`                    | Lead            | Delete a CTF including GitHub files              |
| `/ctf_clear name year`                     | Lead            | Clean up claim branches for repository tidiness  |
| `/ctf_list`                                | Everyone        | Display all CTFs in the repository               |
| `/challenge_add category:<str> name:<str>` | Everyone        | Add a single challenge to the active CTF         |
| `/challenges_add challenges:<str>`         | Everyone        | Add multiple challenges at once (see format below) |
| `/challenge_delete id:<int>`               | Manage Messages | Remove a challenge from board and GitHub         |
| `/help`                                    | Everyone        | Show command reference and workflow              |

#### Multi-Challenge Format

When using `/challenges_add`, format your challenges as a comma-separated list of `category:name` pairs:

```
/challenges_add challenges:web:login,pwn:shellcode,crypto:rsa,web:admin
```

This will add 4 challenges: 
- "login" in the web category
- "shellcode" in the pwn category 
- "rsa" in the crypto category
- "admin" in the web category

### Board Buttons

The challenge board provides interactive buttons for each challenge:

- **🔷 Claim**: Claim a challenge to work on it
  - Creates a GitHub branch automatically
  - DMs you Git instructions
  - Updates the board with your name
  - Prevents others from claiming the same challenge

- **⚪ Unclaim**: Release a challenge you've claimed
  - Makes it available for others
  - Updates the board

- **✅ Solved**: Mark your claimed challenge as solved
  - Creates a SOLVED marker in GitHub
  - DMs you Git instructions for merging
  - Updates the board

### Workflow Example

1. Team lead starts a CTF:
   ```
   /ctf_add name:dam year:2025
   ```
   This sets the repository to private for security during the competition.

2. Add challenges individually or in bulk:
   ```
   /challenge_add category:web name:login-portal
   /challenges_add challenges:pwn:ret2win,web:admin-panel,crypto:weak-prng
   ```

3. The challenge board is created showing all challenges by category

4. Team members claim challenges by clicking the **Claim** button on the board

5. After claiming, members receive Git instructions via DM:
   ```
   # First make sure you're on main and it's clean
   git switch main
   git pull

   # Create/switch to claim branch
   git switch claim-username-challenge 2>/dev/null || git switch -c claim-username-challenge origin/claim-username-challenge
   ```

6. When solved, members click **Solved** and receive merge instructions:
   ```
   # 1. Make sure all your changes are committed
   git status  # Check what files need to be added
   git add dam-2025/category/challenge/
   git commit -m "Solved category/challenge"

   # 2. Push your solution
   git push -u origin claim-username-challenge

   # 3. Merge to main (automated)
   git switch main
   git pull  # Get latest changes
   git merge --no-ff claim-username-challenge -m "Merge solution for category/challenge"
   git push
   ```

7. After the CTF, run `/ctf_done` to lock it and prepare for the next one

8. When ready to share your team's write-ups, run `/ctf_publish` to make the repository public

## GitHub Repository Structure

The bot organizes your CTF repository with a consistent structure:

```
repository/
├── ctf-name-year/
│   ├── README.md
│   ├── category1/
│   │   ├── challenge1/
│   │   │   ├── question/
│   │   │   │   └── README.md  # Challenge description
│   │   │   └── answer/
│   │   │       ├── Flag.md    # Captured flag
│   │   │       ├── SOLVED     # Marker file (if solved)
│   │   │       └── writeup.md # Solution approach
│   │   └── challenge2/
│   │       └── ...
│   └── category2/
│       └── ...
└── another-ctf-year/
    └── ...
```

## Troubleshooting

### Common Issues

1. **Bot not showing up**: Ensure the bot has proper permissions in Discord
2. **GitHub errors**: Check your Personal Access Token's scope and expiration date
3. **Board not updating**: Ensure the BOARD_CHANNEL_ID is correct
4. **Slash commands not registered**: Check your DEFAULT_GUILD setting

### Logs

The bot keeps detailed logs in:
- `ctf_task_tracker_bot/logs/bot.log`: General logging
- `ctf_task_tracker_bot/logs/error.log`: Error-specific logging

## License

This project is licensed under the MIT License - see the LICENSE file for details. 