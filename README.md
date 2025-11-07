# Bitaxe Multi-Miner Performance Logger

A Python-based monitoring and analysis tool for Bitaxe ASIC Bitcoin miners. Automatically collects performance metrics (hashrate, efficiency, temperature, voltage) and segments data by clock configurations to identify optimal operating parameters.

## Features

### Core Monitoring
- **Multi-device monitoring**: Poll multiple Bitaxe miners simultaneously
- **Automatic config detection**: Segments data by frequency/voltage settings
- **Time-series storage**: SQLite database with efficient indexing
- **Efficiency calculations**: J/TH and GH/W metrics computed in real-time
- **Analysis tools**: Compare configurations, identify optimal settings
- **Safety monitoring**: Temperature warnings and alerts

### Terminal Dashboard
- **Real-time dashboard**: Live terminal UI with Rich formatting
- **Variance analysis**: Multi-timeframe hashrate stability metrics
- **Uptime tracking**: Automatic restart detection with total uptime
- **Performance trends**: Sparkline graphs and moving averages
- **Lite mode**: Compact view for monitoring 4+ miners

### Discord Bot (New!)
- **Auto-reporting**: Hourly status updates to Discord channel
- **Smart averaging**: 1h averages for reliable hashrate/efficiency stats
- **Chart generation**: Swarm and per-miner performance graphs
- **Interactive commands**: On-demand stats, reports, and health checks
- **Moving averages**: 1h and 24h MA overlays on 12h graphs

## Quick Start

### 1. Setup

```bash
# Clone the repository
git clone https://github.com/ldevine15/bitaxe-monitor.git
cd bitaxe-monitor

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Create `config.yaml` with your Bitaxe device IPs:

```yaml
devices:
  - name: "bitaxe-1"
    ip: "192.168.1.100"
    enabled: true
  - name: "bitaxe-2"
    ip: "192.168.1.101"
    enabled: true

logging:
  poll_interval: 30
  database_path: "./data/metrics.db"
  log_level: "INFO"

safety:
  max_temp_warning: 65
  max_temp_shutdown: 70
```

### 3. Start Monitoring

```bash
# Start data collection (required)
python run_logger.py

# Terminal dashboard
python dashboard.py         # Full dashboard fits 1-4 easily 
python dashboard.py --lite  # Compact view for 4+ miners

# Discord bot
pip install -r requirements-discord.txt
python discord_bot.py       # See Discord setup below
```

The logger will:
- Poll all enabled devices every 30 seconds (or whatever is configured for `poll_interval`)
- Automatically detect current clock configurations
- Store metrics *per clock configuration* in SQLite database
- Display real-time status in console
- Alert on temperature warnings

### 4. Analyze Data

```bash
# View configuration performance summary
python stats.py compare bitaxe-1

# View summary statistics
python stats.py summary bitaxe-1

# Export data to CSV
python stats.py export bitaxe-1 results.csv
```

## Project Structure

```
bitaxe-monitor/
├── README.md                   # This file
├── LICENSE                     # MIT License
├── requirements.txt            # Core dependencies
├── requirements-discord.txt    # Discord bot dependencies
├── config.yaml.example         # Example configuration
├── config-discord-example.yaml # Discord bot config example
│
├── run_logger.py               # Data collection daemon
├── dashboard.py                # Real-time terminal dashboard
├── discord_bot.py              # Discord bot entry point
├── stats.py                    # Statistics & analysis CLI
│
├── src/                        # Source code
│   ├── api_client.py          # Bitaxe REST API client
│   ├── database.py            # SQLite operations
│   ├── models.py              # Data models
│   ├── logger.py              # Main logging daemon
│   ├── analyzer.py            # Analysis tools
│   └── discord/               # Discord bot module
│       ├── bot.py             # Bot commands & logic
│       ├── config.py          # Discord configuration
│       ├── chart_generator.py # Graph generation (Phase 2)
│       └── embed_builder.py   # Discord embeds (Phase 2)
│
├── data/                       # Data directory (gitignored)
│   ├── metrics.db             # SQLite database
│   ├── charts/                # Generated chart images
│   └── *.log                  # Application logs
│
└── docs/                       # Documentation
    ├── discord-bot.md         # Discord bot implementation plan
    ├── discord-setup.md       # Discord bot setup guide
    └── GET-CHANNEL-ID.md      # Quick Discord channel ID guide
```

## Discord Bot Setup

### Quick Start

1. **Create Discord bot** at https://discord.com/developers/applications
2. **Enable intents**: MESSAGE CONTENT intent (required)
3. **Get bot token** and **channel ID** (see `docs/discord-setup.md`)
4. **Create `.env` file**:
   ```bash
   echo "DISCORD_BOT_TOKEN=your_token_here" > .env
   ```
5. **Update `config.yaml`** with Discord section (see `config-discord-example.yaml`)
6. **Install dependencies**:
   ```bash
   pip install -r requirements-discord.txt
   ```
7. **Start the bot**:
   ```bash
   python discord_bot.py
   ```

### Discord Commands

```
!stats         # Quick stats with 1h averages
!report        # Full report with charts (Phase 2)
!miner <name>  # Individual miner details
!health        # Check for warnings
!help          # Command list
```

**Auto-reports**: Posts to your Discord channel every hour with swarm stats and per-miner performance.

See full setup guide: `docs/discord-setup.md`

---

## Usage Examples

### Configuration Testing Workflow

```bash
# 1. Start the logger
python run_logger.py

# 2. Test each configuration (2+ hours each)
# - Set 550MHz @ 1150mV via Bitaxe web UI, let it run
# - Set 575MHz @ 1200mV via web UI, let it run
# - Set 600MHz @ 1250mV via web UI, let it run

# 3. Analyze results
python stats.py compare bitaxe-1
```

## Key Metrics

- **Hashrate**: Mining performance in GH/s (gigahash per second)
- **J/TH**: Energy efficiency in joules per terahash (lower is better)
- **GH/W**: Hash efficiency in gigahash per watt (higher is better)
- **Temperature**: ASIC and voltage regulator temps in °C
- **Power**: Total power consumption in watts

## Security & Privacy

### Running Locally
- Everything runs on your local network
- No cloud services or external APIs (except Discord bot if enabled)
- Database is local SQLite file
- Only you can access your data
---

## Safety Notes

- All overclocking is done at your own risk
## References

- [ESP-Miner Firmware](https://github.com/bitaxeorg/ESP-Miner)
- [Bitaxe Hardware](https://github.com/skot/bitaxe)
- [Bitaxe API Documentation](https://osmu.wiki/bitaxe/api/)

## License

MIT License - See LICENSE file for details