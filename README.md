# Bitaxe Multi-Miner Performance Logger

A Python-based monitoring and analysis tool for Bitaxe ASIC Bitcoin miners. Automatically collects performance metrics (hashrate, efficiency, temperature, voltage) and segments data by clock configurations to identify optimal operating parameters.

## Features

- **Multi-device monitoring**: Poll multiple Bitaxe miners simultaneously
- **Automatic config detection**: Segments data by frequency/voltage settings
- **Time-series storage**: SQLite database with efficient indexing
- **Efficiency calculations**: J/TH and GH/W metrics computed in real-time
- **Session management**: Track structured testing sessions with notes
- **Analysis tools**: Compare configurations, identify optimal settings
- **Safety monitoring**: Temperature warnings and alerts

## Quick Start

### 1. Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/bitaxe-monitor.git
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

### 3. Start Logging

```bash
python run_logger.py
```

The logger will:
- Poll all enabled devices every 30 seconds
- Automatically detect current clock configurations
- Store metrics in SQLite database
- Display real-time status in console
- Alert on temperature warnings

### 4. Analyze Data

```bash
# View configuration performance summary
python analyze.py compare-configs --device bitaxe-1

# Find optimal configuration for efficiency
python analyze.py optimize --metric efficiency

# Export data to CSV
python analyze.py export --format csv --output results.csv
```

## Project Structure

```
bitaxe-monitor/
├── README.md                   # This file
├── LICENSE                     # MIT License
├── plan.md                     # Detailed design document
├── requirements.txt            # Python dependencies
├── config.yaml.example         # Example configuration
├── config.yaml                 # Device configuration (gitignored)
│
├── run_logger.py               # Main entry point
├── analyze.py                  # Analysis CLI
├── dashboard.py                # Real-time dashboard
│
├── src/                        # Source code
│   ├── api_client.py          # Bitaxe REST API client
│   ├── database.py            # SQLite operations
│   ├── models.py              # Data models
│   ├── logger.py              # Main logging daemon
│   └── analyzer.py            # Analysis tools
│
├── cli/                        # CLI commands
│
├── tests/                      # Unit tests
│
├── data/                       # Data directory (gitignored)
│   ├── metrics.db             # SQLite database
│   ├── logs/                  # Application logs
│   └── exports/               # Exported data
│
└── docs/                       # Documentation
```

## Usage Examples

### Passive Monitoring

Just run the logger and change settings via the Bitaxe web UI whenever you want. Data is automatically segmented by configuration.

```bash
python run_logger.py
# Leave running 24/7
# Change clock settings via web UI as desired
# Analyze results later
```

### Active Testing Sessions

For structured experiments with explicit session tracking:

```bash
# Start test session
python run_logger.py session start \
  --device bitaxe-1 \
  --freq 600 --voltage 1200 \
  --notes "Overnight test, ambient 22°C"

# (Wait 8 hours)

# End session
python run_logger.py session end --device bitaxe-1

# Start next test
python run_logger.py session start \
  --device bitaxe-1 \
  --freq 625 --voltage 1250 \
  --notes "Morning test, ambient 18°C"
```

### Configuration Testing Workflow

```bash
# 1. Baseline (2 hours each)
# Set 550MHz @ 1150mV via web UI, let logger run

# 2. Medium overclock
# Set 575MHz @ 1200mV via web UI

# 3. High overclock
# Set 600MHz @ 1250mV via web UI

# 4. Analyze results
python analyze.py compare-configs --device bitaxe-1

# 5. Generate report
python dashboard.py
```

## Key Metrics

- **Hashrate**: Mining performance in GH/s (gigahash per second)
- **J/TH**: Energy efficiency in joules per terahash (lower is better)
- **GH/W**: Hash efficiency in gigahash per watt (higher is better)
- **Temperature**: ASIC and voltage regulator temps in °C
- **Power**: Total power consumption in watts

## Safety Notes

- Monitor temperatures continuously
- Keep ASIC temp below 65°C for longevity
- Recommended voltage range: 1150-1250mV
- Recommended frequency range: 550-600MHz
- Use adequate cooling and ventilation

## Development Status

**Current Phase**: Phase 1 - Basic Data Logger (MVP)

Planned features:
- [ ] Basic logging daemon
- [ ] SQLite storage
- [ ] Config auto-detection
- [ ] Session management
- [ ] Analysis tools
- [ ] Terminal dashboard
- [ ] Visualization/plotting
- [ ] Web dashboard

See [plan.md](plan.md) for complete roadmap.

## References

- [ESP-Miner Firmware](https://github.com/bitaxeorg/ESP-Miner)
- [Bitaxe Hardware](https://github.com/skot/bitaxe)
- [Bitaxe API Documentation](https://osmu.wiki/bitaxe/api/)

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please read the plan.md for architecture details before submitting PRs.
