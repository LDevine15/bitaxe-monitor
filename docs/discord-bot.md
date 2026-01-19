# Discord Bot Integration Plan

## Overview

Add Discord bot functionality to report Bitaxe mining metrics with rich visualizations including:
- Configuration summary in embed title/description
- Swarm-wide aggregate hashrate graphs (24h)
- Per-miner hashrate graphs with dual-axis temperature overlay (24h)
- Statistical summaries and variance analysis
- On-demand reporting via Discord commands

---

## Architecture

```
┌─────────────────┐
│  Discord Bot    │ ←─── Commands from Discord users
│  (discord.py)   │
└────────┬────────┘
         │
         ├─────→ Chart Generator (matplotlib)
         │        ├─── Swarm hashrate graphs
         │        ├─── Per-miner hashrate + temp
         │        └─── Generate PNG images
         │
         ├─────→ Database (SQLite)
         │        └─── Query metrics, configs
         │
         └─────→ Analyzer (existing)
                  └─── Statistical analysis
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **discord_bot.py** | Bot entry point, command handlers, Discord API |
| **chart_generator.py** | Matplotlib charts, image generation |
| **embed_builder.py** | Discord embed formatting, data presentation |
| **bot_config.py** | Bot settings, Discord token, channel IDs |

---

## File Structure

```
bitaxe-monitor/
├── discord_bot.py              # Main bot entry point (NEW)
├── requirements-discord.txt     # Discord-specific deps (NEW)
│
├── src/
│   ├── discord/                # Discord bot module (NEW)
│   │   ├── __init__.py
│   │   ├── bot.py             # Bot class & command handlers
│   │   ├── chart_generator.py # Matplotlib chart generation
│   │   ├── embed_builder.py   # Discord embed creation
│   │   └── config.py          # Bot configuration
│   │
│   ├── api_client.py          # (existing)
│   ├── database.py            # (existing)
│   ├── models.py              # (existing)
│   ├── logger.py              # (existing)
│   └── analyzer.py            # (existing)
│
├── config.yaml                # Add discord section (MODIFIED)
└── data/
    └── charts/                # Generated chart cache (NEW)
```

---

## Dependencies

### New Requirements (requirements-discord.txt)

```txt
# Discord Bot
discord.py>=2.3.0           # Discord API wrapper
py-cord>=2.5.0              # Alternative: Pycord (if preferred)

# Image Generation & Charts
matplotlib>=3.7             # (already in requirements.txt)
Pillow>=10.0                # Image manipulation
seaborn>=0.12               # Enhanced matplotlib styling

# Utilities
python-dateutil>=2.8        # Date parsing
pytz>=2023.3                # Timezone handling
```

### Installation

```bash
pip install -r requirements-discord.txt
```

---

## Configuration

### config.yaml additions

```yaml
# Existing config sections...
devices:
  - name: "bitaxe-1"
    ip: "192.168.1.149"
    enabled: true
  # ...

logging:
  poll_interval: 10
  database_path: "./data/metrics.db"

# NEW: Discord bot configuration
discord:
  enabled: true
  token: "${DISCORD_BOT_TOKEN}"        # From environment variable
  command_prefix: "!"

  # Channel IDs (optional - if specified, only these channels can use bot)
  allowed_channels:
    - 1234567890123456789              # Replace with your channel ID

  # Auto-reporting (optional)
  # NOTE: Auto-report interval is SEPARATE from poll_interval
  # poll_interval (10s) = how often to collect data
  # auto_report schedule = how often to post to Discord
  auto_report:
    enabled: false
    channel_id: 1234567890123456789

    # Recommended intervals:
    #   "0 * * * *"    = Every 1 hour (RECOMMENDED - 24 reports/day)
    #   "0 */6 * * *"  = Every 6 hours (4 reports/day)
    #   "0 */12 * * *" = Every 12 hours (2 reports/day)
    #   "0 0 * * *"    = Daily at midnight (1 report/day)
    schedule: "0 * * * *"              # Cron format: every 1 hour

    # Include charts in auto-report?
    include_charts: true

    # Lookback period for auto-reports (hours)
    default_hours: 24

  # Chart settings
  charts:
    dpi: 150                           # Image quality (72-300)
    style: "dark_background"           # matplotlib style
    figsize: [12, 6]                   # Figure dimensions (width, height)
    cache_ttl: 300                     # Cache charts for 5 minutes
```

### Environment Variables

```bash
# .env file
DISCORD_BOT_TOKEN=your_bot_token_here
```

---

## Features & Commands

### 1. `!status` - Instant Snapshot (Phase 1 ✅)

**Description**: Show instant/current values (noisy but real-time)

**Output**: ANSI colored compact format
```ansi
⛏️  Bitaxe Swarm (snapshot)
1.85 Th/s | 4/4 | 26.9 J/TH | 49.5W

bitaxe-1 525 MHz 0.46 TH/s 26.2 J/TH 58°/64° 8d
bitaxe-2 525 MHz 0.46 TH/s 27.1 J/TH 59°/66° 9d
bitaxe-3 525 MHz 0.46 TH/s 26.8 J/TH 57°/63° 2d
bitaxe-4 525 MHz 0.46 TH/s 26.5 J/TH 58°/65° 2d
```

**Features**:
- Current/instant values (±30% variance)
- ANSI colors (cyan=values, green/yellow/red=temps)
- TH/s units with 2 decimal places
- Super compact (one line per miner)
- 10s cooldown per user

---

### 2. `!stats` - Reliable Averages (Phase 1 ✅)

**Description**: Show 1h averaged stats (reliable, used for auto-reports)

**Output**: ANSI colored compact format
```ansi
⛏️  Bitaxe Swarm (1h avg)
1.84 Th/s | 4/4 | 26.9 J/TH | 49.5W

bitaxe-1 525 MHz 0.46 TH/s 26.2 J/TH 58°/64° 8d
bitaxe-2 525 MHz 0.46 TH/s 27.1 J/TH 59°/66° 9d
bitaxe-3 525 MHz 0.46 TH/s 26.8 J/TH 57°/63° 2d
bitaxe-4 525 MHz 0.46 TH/s 26.5 J/TH 58°/65° 2d
```

**Features**:
- 1h averaged hashrate & efficiency (±6% confidence)
- Current temps & power (snapshot OK for these)
- ANSI colors matching terminal dashboard
- TH/s units with 2 decimal places
- 10s cooldown per user
- **Used for hourly auto-reports**

---

---

### 3. `!report [hours]` - Comprehensive Report with Charts (Phase 2 ⏳)

**Description**: Generate detailed performance report with visualizations

**On-Demand Usage**: Members can invoke this command anytime, bypassing auto-report schedule

**Arguments**:
- `hours` (optional): Lookback period in hours (default: 24, max: 168 for 7 days)

**Cooldown**: 60 seconds per user (prevents spam, doesn't affect auto-reports)

**Output**: Discord embed with:

#### Embed Structure

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ⛏️ Bitaxe Mining Report (24 hours)      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

📋 Configuration
  4x Bitaxe @ 525MHz / 1200mV
  Pool: public-pool.io:21496
  Poll Interval: 10s

📊 Swarm Performance
  Current: 1.85 TH/s
  1h Average: 1.84 TH/s (±3.1% variance)
  24h Average: 1.84 TH/s (±4.2% variance)
  Efficiency: 26.9 J/TH (24h avg)
  Power: 49.5W total
  Uptime: 100% (no restarts detected)

🏆 Best Performance
  Peak Hashrate: 1891.2 GH/s @ 2025-11-07 03:45
  Best Efficiency: 26.1 J/TH @ 2025-11-07 12:30
  Coolest Temp: 54.3°C @ 2025-11-07 06:15

⚠️ Alerts (Last 24h)
  None - All systems nominal ✅

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[Attached: swarm_hashrate_24h.png]
[Attached: miner_details_24h.png]
```

#### Chart 1: Swarm Aggregate Hashrate (12h with Moving Averages)

![Swarm Hashrate Mockup](mockup-swarm-chart)
```
┌─────────────────────────────────────────────┐
│  Swarm Total Hashrate (12h)                 │
│                                             │
│  2000 GH/s ┤           ╭───╮                │
│  1900      ┤      ╭───╮│   │╭───╮           │
│  1800      ┤  ╭───╯   ╰╯   ╰╯   ╰───        │
│  1700      ┤──╯                             │
│            └┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┤
│             0  2  4  6  8  10 12 hours ago │
│                                             │
│  ━━━ Raw hashrate (5-min buckets)           │
│  ━━━ 1h moving average (smoothed)           │
│  ━━━ 24h moving average (trend line)        │
│                                             │
│  Current: 1847.3 GH/s | 1h Avg: 1842.7 | 24h Avg: 1838.5 │
│  Variance (12h): ±4.2% (Excellent)          │
└─────────────────────────────────────────────┘
```

**Technical Details**:
- **Raw data**: 5-minute buckets (144 data points over 12h)
- **1h MA**: Rolling average over last 12 samples (smooths short-term noise)
- **24h MA**: Rolling average over entire dataset (shows long-term trend)
- Three overlaid lines: cyan (raw), yellow (1h MA), red (24h MA)

#### Chart 2: Per-Miner Hashrate + Temperature (12h)

![Per-Miner Chart Mockup](mockup-miner-chart)
```
┌─────────────────────────────────────────────┐
│  Individual Miner Performance (12h)         │
│                                             │
│  600 GH/s ┤   Hashrate (lines)        70°C │
│  500      ┤ ━━ bitaxe-1 (blue)        60   │
│  400      ┤ ━━ bitaxe-2 (green)       50   │
│  300      ┤ ━━ bitaxe-3 (orange)      40   │
│  200      ┤ ━━ bitaxe-4 (red)         30   │
│           └┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┤
│            0  2  4  6  8  10 12 hours ago  │
│                                             │
│  Temperature (shaded areas in background)   │
│  ░░░ ASIC temps for each miner             │
│                                             │
│  Per-Miner Stats (12h):                     │
│  bitaxe-1: Now: 462.1 | 1h: 461.8 | 24h: 460.5 GH/s │
│  bitaxe-2: Now: 461.8 | 1h: 462.3 | 24h: 461.1 GH/s │
│  [... more miners ...]                      │
└─────────────────────────────────────────────┘
```

**Technical Details**:
- **X-axis**: 12 hours lookback (720 minutes)
- **Y-axis Left**: Hashrate per miner (GH/s)
- **Y-axis Right**: Temperature per miner (°C)
- **Data points**: 5-minute buckets (144 points)
- Each miner shows current, 1h avg, and 24h avg in stats

---

---

### 4. `!miner <name>` - Individual Miner Deep Dive (Phase 2 ⏳)

**Description**: Detailed stats and chart for a single miner

**Arguments**:
- `name` (required): Miner name (e.g., "bitaxe-1")

**Output**: Focused embed with:
- Configuration details
- Current metrics
- 12h hashrate + temp chart
- Variance analysis
- Share statistics
- Recent best difficulty

---

### 5. `!health` - System Health Check (Phase 1 ✅)

**Description**: Monitor for warnings and anomalies

**Output**: Text report with color-coded warnings
- Temperature warnings (yellow ≥60°C, red ≥65°C ASIC)
- Temperature warnings (yellow ≥70°C, red ≥80°C VRM)
- Voltage issues (yellow <4.9V, red <4.8V)
- Hashrate drops (<400 GH/s)
- No data available for any miners

---

### 6. `!help` - Command List (Phase 1 ✅)

**Description**: Show all available commands

**Output**: List of commands with examples and usage

---

## Implementation Phases

### Phase 1: Core Bot Infrastructure ✅ COMPLETE

**Goal**: Get basic bot working with ANSI colored compact stats

**Completed**:
- ✅ Set up discord.py bot scaffolding
- ✅ Implement `!status` command (instant snapshot)
- ✅ Implement `!stats` command (1h averages)
- ✅ Implement `!health` command (warnings check)
- ✅ Implement `!help` command (command list)
- ✅ Connect to existing database.py
- ✅ Add Discord config to config.yaml
- ✅ Environment variable loading (.env support)
- ✅ ANSI color codes matching terminal dashboard
- ✅ Compact format (one line per miner)
- ✅ TH/s units with 2 decimal places
- ✅ 1h averaged calculations for reliability
- ✅ Auto-reporting every hour (uses `!stats` format)
- ✅ Per-user cooldowns (anti-spam)
- ✅ Smart temperature color-coding
- ✅ Error handling and logging

**Deliverable**: Bot responds with beautiful colored compact stats in Discord

---

### Phase 2: Chart Generation (Week 2)

**Goal**: Generate PNG charts from database metrics

- [ ] Create `chart_generator.py` module
- [ ] Implement swarm hashrate chart (24h line graph)
- [ ] Implement per-miner hashrate chart (multi-line)
- [ ] Add temperature overlay (dual y-axis)
- [ ] Style charts for Discord dark mode
- [ ] Implement chart caching (5-minute TTL)

**Deliverable**: Charts generated locally, viewable as files

---

### Phase 3: Rich Embeds (Week 3)

**Goal**: Beautiful Discord embeds with attached charts

- [ ] Create `embed_builder.py` module
- [ ] Implement `/report` command with embeds
- [ ] Attach generated charts to embeds
- [ ] Add color-coded status indicators
- [ ] Format tables for Discord
- [ ] Add emoji indicators for health status

**Deliverable**: `/report` command sends full embed with charts

---

### Phase 4: Additional Commands (Week 4)

**Goal**: Complete command suite

- [ ] Implement `/miner <name>` command
- [ ] Implement `/compare` command
- [ ] Implement `/health` command
- [ ] Add command cooldowns (anti-spam)
- [ ] Add permissions/role checks
- [ ] Command help system

**Deliverable**: Full command suite operational

---

### Phase 5: Auto-Reporting & Polish (Week 5)

**Goal**: Scheduled reports and production readiness

- [ ] Implement scheduled auto-reporting (cron-style)
- [ ] Add uptime tracking for bot itself
- [ ] Improve error messages
- [ ] Add logging and monitoring
- [ ] Write documentation
- [ ] Deployment guide (systemd service)

**Deliverable**: Production-ready Discord bot

---

## Technical Details

### Chart Generation Specifications

#### Swarm Hashrate Chart

**Type**: Single-line time series
**X-axis**: Time (24h lookback, 1-hour buckets)
**Y-axis**: Total hashrate (GH/s)
**Data**: Bucketed averages from `get_bucketed_hashrate_trend()`
**Styling**:
- Line: 2px solid cyan (#00FFFF)
- Fill under curve: cyan with 20% alpha
- Grid: dashed gray
- Background: dark (#1E1E1E)

**Annotations**:
- Min/Max/Avg values in legend
- Current value marker (red dot)
- Variance percentage

---

#### Per-Miner Hashrate + Temperature Chart

**Type**: Multi-line time series with dual y-axis
**X-axis**: Time (24h lookback, 1-hour buckets)
**Y-axis Left**: Hashrate (GH/s)
**Y-axis Right**: Temperature (°C)

**Data Sources**:
- Hashrate: `get_bucketed_hashrate_trend()` per device
- Temperature: Bucket averages of ASIC temp

**Styling**:
- Hashrate lines: 2px solid, unique color per miner
- Temp areas: Filled translucent (20% alpha), matching miner colors
- Grid: shared, dashed gray
- Legend: Upper right, miner names with colors

**Colors** (per miner):
```python
MINER_COLORS = [
    '#3498DB',  # Blue
    '#2ECC71',  # Green
    '#E74C3C',  # Red
    '#F39C12',  # Orange
    '#9B59B6',  # Purple
    '#1ABC9C',  # Teal
]
```

---

### Database Queries

#### Swarm Aggregate Query

```python
def get_swarm_hashrate_trend(db: Database, hours: int = 24, buckets: int = 24):
    """Get bucketed swarm-wide hashrate for all active devices."""
    devices = db.get_all_device_ids()

    # Get trends for each device
    all_trends = []
    for device_id in devices:
        trend = db.get_bucketed_hashrate_trend(device_id, hours * 60, buckets)
        all_trends.append(trend)

    # Sum across devices at each bucket
    swarm_trend = [sum(bucket) for bucket in zip(*all_trends)]
    return swarm_trend
```

#### Per-Miner with Temperature

```python
def get_miner_hashrate_temp(db: Database, device_id: str, hours: int = 24):
    """Get hashrate and temperature trends for a single miner."""
    minutes = hours * 60
    buckets = 24  # 1-hour buckets

    hashrates = db.get_bucketed_hashrate_trend(device_id, minutes, buckets)
    temps = db.get_bucketed_temp_trend(device_id, minutes, buckets)  # NEW METHOD

    return {
        'hashrate': hashrates,
        'temperature': temps,
        'timestamps': generate_bucket_timestamps(hours, buckets)
    }
```

**Note**: Need to add `get_bucketed_temp_trend()` to `database.py`

---

### Discord Embed Limits

- **Title**: 256 characters max
- **Description**: 4096 characters max
- **Fields**: 25 fields max, 1024 chars each
- **Footer**: 2048 characters max
- **Total embed**: 6000 characters max
- **Attachments**: 10 MB max per file

---

## Example Usage

### User Workflow

```
User: !status
Bot: [Quick text status of all miners]

User: !report
Bot: [Sends embed with 2 chart images attached]

User: !miner bitaxe-1
Bot: [Detailed embed for bitaxe-1 with individual chart]

User: !health
Bot: ✅ All systems nominal
     - No temperature warnings
     - No restarts in last 24h
     - All reject rates < 1%
```

---

## Rate Limiting & Performance

### Discord Rate Limits

**Hard Limits**:
- 5 messages per 5 seconds per channel
- 50 global API requests per second per bot
- File uploads count as full messages

**Consequences**:
- Exceeding limits = HTTP 429 error
- Temporary ban (1-60 minutes depending on severity)
- Permanent ban for repeated violations

### Auto-Report Interval Guidelines

| Interval | Posts/Day | Status | Use Case |
|----------|-----------|--------|----------|
| 10s (poll) | 8,640 | ❌ **NEVER** | Data collection only |
| 1 minute | 1,440 | ❌ **NO** | Rate limit violation |
| 15 minutes | 96 | ❌ **NO** | Channel spam |
| 30 minutes | 48 | ⚠️ Risky | Very active monitoring |
| 1 hour | 24 | ✅ OK | Active monitoring |
| 6 hours | 4 | ✅ **Recommended** | Best balance |
| 12 hours | 2 | ✅ Good | Conservative |
| Daily | 1 | ✅ Good | Summary reports |

**Important**: Your 10-second `poll_interval` is for **data collection** (logger → database). Discord auto-reports should be **1-6 hours minimum**.

### Command Cooldowns

Implement per-user cooldowns to prevent spam:
```python
@commands.cooldown(1, 60, commands.BucketType.user)  # 1 use per 60 seconds per user
async def report(ctx, hours: int = 24):
    # User can manually invoke /report once per minute
    # This doesn't affect scheduled auto-reports
    ...
```

**How Auto + Manual Work Together**:
- **Auto-report**: Posts every hour automatically (no cooldown, uses service account)
- **Manual `/report`**: Any user can invoke it, 60s cooldown per user
- Both use the same chart generation code
- Chart cache (5-minute TTL) prevents duplicate work if auto-report just ran

---

## Security Considerations

1. **Token Security**: Store bot token in environment variable, never commit to git
2. **Channel Restrictions**: Limit bot to specific channels via `allowed_channels`
3. **Rate Limiting**:
   - Implement command cooldowns (60s per user for `/report`)
   - Global bot cooldown (10s between any commands)
   - Auto-report: 6-hour minimum interval
4. **Permissions**: Use Discord role checks for sensitive commands
5. **Input Validation**: Sanitize all user inputs (miner names, time ranges)

---

## Deployment

### Running the Bot

```bash
# Export Discord token
export DISCORD_BOT_TOKEN="your_token_here"

# Run bot alongside logger
python run_logger.py &       # Background process
python discord_bot.py        # Foreground

# Or use systemd services (production)
sudo systemctl start bitaxe-logger
sudo systemctl start bitaxe-discord-bot
```

### Systemd Service Example

```ini
# /etc/systemd/system/bitaxe-discord-bot.service
[Unit]
Description=Bitaxe Discord Bot
After=network.target bitaxe-logger.service
Requires=bitaxe-logger.service

[Service]
Type=simple
User=bitaxe
WorkingDirectory=/opt/bitaxe-monitor
Environment="DISCORD_BOT_TOKEN=your_token"
ExecStart=/opt/bitaxe-monitor/venv/bin/python discord_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Testing Strategy

### Unit Tests

- `test_chart_generator.py`: Test chart generation without Discord
- `test_embed_builder.py`: Test embed formatting
- `test_queries.py`: Test swarm aggregation queries

### Integration Tests

- Test commands in private Discord server
- Validate chart rendering quality
- Test with varying data sizes (1-7 days)

### Performance Tests

- Chart generation time (target: < 2 seconds)
- Database query performance
- Memory usage with multiple simultaneous requests

---

## Future Enhancements

- [ ] Interactive charts with Plotly (click to zoom)
- [ ] Animated GIF showing 24h progression
- [ ] Slash commands instead of text commands
- [ ] Web dashboard embed (iframe in Discord)
- [ ] Alert subscriptions (DM on critical events)
- [ ] Multi-language support
- [ ] Custom chart timeframes via buttons

---

## References

- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [Matplotlib Discord Integration](https://github.com/matplotlib/matplotlib/discussions)
- [Discord Embed Visualizer](https://leovoel.github.io/embed-visualizer/)
- [Bitaxe API Docs](https://osmu.wiki/bitaxe/api/)

---

**Next Steps**: Review this plan, then begin Phase 1 implementation.
