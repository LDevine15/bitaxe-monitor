# Discord Bot Setup Guide

Quick guide to get your Discord bot token and channel ID for auto-reporting.

---

## Step 1: Create Discord Bot

### 1.1 Go to Discord Developer Portal
Visit: https://discord.com/developers/applications

### 1.2 Create New Application
1. Click **"New Application"** (top right)
2. Name it: `Bitaxe Monitor` (or whatever you prefer)
3. Click **"Create"**

### 1.3 Configure Bot
1. Go to the **"Bot"** tab (left sidebar)
2. Click **"Add Bot"** → **"Yes, do it!"**
3. Under **"Token"**, click **"Reset Token"** → **"Copy"**
   - ⚠️ **Save this token** - you'll need it for `.env` file
   - Never share this token publicly!

### 1.4 Enable Intents (Important!)
Still on the "Bot" tab, scroll down to **"Privileged Gateway Intents"**:
- ✅ Enable **"MESSAGE CONTENT INTENT"** (required for commands)
- ✅ Enable **"SERVER MEMBERS INTENT"** (optional, for user info)

### 1.5 Set Bot Permissions
1. Go to **"OAuth2"** → **"URL Generator"** (left sidebar)
2. Under **SCOPES**, check:
   - ✅ `bot`
   - ✅ `applications.commands` (for slash commands)
3. Under **BOT PERMISSIONS**, check:
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Attach Files
   - ✅ Read Message History
   - ✅ Add Reactions (optional)

4. Copy the generated URL at the bottom
5. Paste it in your browser
6. Select your Discord server
7. Click **"Authorize"**

Your bot should now appear in your server (offline until you run it)!

---

## Step 2: Get Channel ID for "swarm"

### 2.1 Enable Developer Mode
1. Open Discord desktop/web app
2. Go to **User Settings** (gear icon, bottom left)
3. Go to **Advanced** → Enable **"Developer Mode"**

### 2.2 Copy Channel ID
1. In your Discord server, find your **#swarm** channel (or create it if it doesn't exist)
2. Right-click the **#swarm** channel name
3. Click **"Copy Channel ID"**
4. Save this ID - you'll need it for `config.yaml`

Example: `1234567890123456789`

**Note**: The invite link (https://discord.gg/bneaFHwT) is for joining the server, but we need the specific channel ID to post messages to #swarm.

---

## Step 3: Configure Environment Variables

Create a `.env` file in your project root:

```bash
# .env
DISCORD_BOT_TOKEN=your_bot_token_here
```

**Important**: Never commit `.env` to git! It's already in `.gitignore`.

---

## Step 4: Update config.yaml

Add the Discord section to `config.yaml` (see `config.yaml.example` for all options):

```yaml
discord:
  enabled: true
  token: "${DISCORD_BOT_TOKEN}"   # Reads from .env file
  command_prefix: "!"

  auto_report:
    enabled: true
    channel_id: 1234567890123456789   # ← Paste your channel ID here
    schedule: "0 * * * *"             # Every hour
    include_charts: true
```

---

## Step 5: Test the Bot

### 5.1 Install Discord Dependencies

```bash
pip install -r requirements-discord.txt
```

### 5.2 Run the Bot

```bash
# Make sure logger is running first
python run_logger.py &

# Start Discord bot
python discord_bot.py
```

You should see:
```
[INFO] Connected to Discord as Bitaxe Monitor#1234
[INFO] Auto-report scheduled: 0 * * * * (every hour)
[INFO] Bot ready! Use !status or !report in Discord
```

### 5.3 Test Commands

In your Discord channel, try:
```
!status              ← Quick text summary
!report              ← Full report with charts (24h)
!report 12           ← 12-hour report
!miner bitaxe-1      ← Detailed stats for one miner
!health              ← Check for warnings
```

---

## Troubleshooting

### Bot appears offline
- Check token is correct in `.env`
- Make sure you enabled MESSAGE CONTENT INTENT
- Verify bot has permissions in the channel

### Commands don't respond
- Check `command_prefix` in config (default: `!`)
- Make sure bot has "Send Messages" permission
- Try `!help` to see available commands

### Auto-report not posting
- Verify `channel_id` is correct
- Check bot has permissions in that channel
- Wait for the top of the next hour (schedule: `0 * * * *`)
- Check bot logs for errors

### Charts not generating
- Make sure matplotlib is installed: `pip install matplotlib`
- Check `data/charts/` directory exists and is writable
- Verify database has data: `python stats.py summary bitaxe-1`

---

## Security Best Practices

1. ✅ Store token in `.env` file (gitignored)
2. ✅ Never commit `.env` to git
3. ✅ Regenerate token if accidentally exposed
4. ✅ Use `allowed_channels` to restrict bot access
5. ✅ Review bot permissions - only grant what's needed

---

## Production Deployment (systemd)

Create `/etc/systemd/system/bitaxe-discord-bot.service`:

```ini
[Unit]
Description=Bitaxe Discord Bot
After=network.target bitaxe-logger.service
Requires=bitaxe-logger.service

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/bitaxe-monitor
EnvironmentFile=/path/to/bitaxe-monitor/.env
ExecStart=/path/to/bitaxe-monitor/venv/bin/python discord_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bitaxe-discord-bot
sudo systemctl start bitaxe-discord-bot
sudo systemctl status bitaxe-discord-bot
```

---

## Next Steps

Once the bot is working:
1. Customize chart styling in `config.yaml`
2. Adjust auto-report schedule if needed
3. Set up role permissions for sensitive commands
4. Consider adding custom commands for your workflow

See `docs/discord-bot.md` for full implementation details.
