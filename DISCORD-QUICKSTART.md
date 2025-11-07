# Discord Bot Quick Start

Phase 1 is complete! Here's how to run it.

## Step 1: Install Dependencies

```bash
pip install -r requirements-discord.txt
```

## Step 2: Verify Your .env File

Make sure your `.env` file has:

```bash
DISCORD_BOT_TOKEN=your_actual_bot_token_here
```

## Step 3: Add Discord Config to config.yaml

Add this section to your `config.yaml` (or copy from `config-discord-example.yaml`):

```yaml
# At the end of config.yaml, add:

discord:
  enabled: true
  token: "${DISCORD_BOT_TOKEN}"
  command_prefix: "!"

  auto_report:
    enabled: true
    channel_name: "swarm"
    channel_id: YOUR_CHANNEL_ID_HERE  # Replace with actual channel ID
    schedule: "0 * * * *"             # Every hour
    include_charts: true

    graph_lookback_hours: 12
    show_moving_averages: true
    show_1h_average: true
    show_24h_average: true
```

Replace `YOUR_CHANNEL_ID_HERE` with the channel ID you copied from Discord.

## Step 4: Run the Bot

**Make sure the logger is running first:**
```bash
python run_logger.py &
```

**Then start the Discord bot:**
```bash
python discord_bot.py
```

You should see:
```
INFO - Connected to Discord as Bitaxe Monitor#1234
INFO - Auto-report scheduled: 0 * * * * (every hour)
INFO - Auto-report channel: #swarm (1234567890123456789)
INFO - Bot ready! Monitoring 4 devices
```

## Step 5: Test Commands in Discord

Go to your #swarm channel and try:

```
!stats         # Quick stats of all miners (1h averages)
!report        # Full report (charts coming in Phase 2)
!report 12     # 12-hour report
!health        # Check for warnings
!help          # Show available commands
```

---

## Phase 1 Features ✅

- ✅ Bot connects to Discord
- ✅ Loads config from .env and config.yaml
- ✅ Connects to existing database
- ✅ `!stats` command - text summary with 1h averages
- ✅ `!report` command - placeholder for charts (Phase 2)
- ✅ `!miner` command - placeholder for detailed stats (Phase 2)
- ✅ `!health` command - warnings and alerts
- ✅ `!help` command - command list
- ✅ Auto-reports every hour (text-only for now)
- ✅ Per-user cooldowns to prevent spam
- ✅ Error handling and logging

---

## Troubleshooting

**"Discord bot is not enabled in config.yaml"**
- Add the `discord:` section to config.yaml (see Step 3)

**"Environment variable DISCORD_BOT_TOKEN not set"**
- Create `.env` file with your bot token (see Step 2)
- Make sure it's in the project root directory

**"Database not found"**
- Make sure `run_logger.py` is running first
- Check that `data/metrics.db` exists

**Bot doesn't respond to commands**
- Make sure you invited the bot with MESSAGE CONTENT intent enabled
- Check bot has "Send Messages" permission in #swarm channel
- Verify command prefix is `!` (not `/`)

**"Auto-report channel not found"**
- Double-check your channel ID in config.yaml
- Make sure the bot has access to #swarm channel

---

## Next: Phase 2

Once !status is working, we'll add:
- Chart generation with matplotlib
- Swarm hashrate graph (12h, with 1h/24h MAs)
- Per-miner hashrate + temperature graphs
- Attach charts to !report command
- Auto-reports will include charts

Ready? Let's test Phase 1 first!
