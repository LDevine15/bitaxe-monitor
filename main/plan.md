# Bitaxe Multi-Miner Performance Logger & Optimizer

## Executive Summary

This document outlines the design and implementation plan for a custom logging and analysis tool for Bitaxe ASIC Bitcoin miners. The tool will collect performance metrics (TH/s, J/TH, temperature, voltage, etc.) from multiple Bitaxe devices, segment data by clock settings, and provide analytics to determine optimal operating parameters.

**Key Objectives:**
- Monitor 2+ Bitaxe miners simultaneously via REST API
- Log performance metrics with clock setting correlation
- Calculate efficiency metrics (J/TH, GH/W)
- Identify optimal frequency/voltage combinations
- Provide historical analysis and visualization
- Support A/B testing of different configurations

---

## Research Findings

### 1. Bitaxe Hardware Overview

**Components:**
- ESP32-S3-WROOM-1 microcontroller with WiFi
- BM1366 ASIC chip (rated 0.021J/GH efficiency)
- TI TPS40305 buck regulator + Maxim DS4432U+ current DAC
- TI INA260 power meter
- Microchip EMC2101 fan controller
- 0.91" SSD1306 OLED display

**Power Requirements:**
- 5V DC input, ~15W typical consumption
- Recommended: 25W (5V, 5A) PSU minimum

### 2. ESP-Miner Firmware API

The Bitaxe runs ESP-Miner firmware which provides a comprehensive REST API accessible via HTTP on port 80 (http://bitaxe or http://<IP>).

#### Primary API Endpoints

**GET `/api/system/info`** - Real-time system information (66 fields)

Key metrics returned:
```json
{
  // Performance Metrics
  "hashRate": 550.0,              // Current GH/s
  "expectedHashrate": 600.0,      // Target GH/s
  "power": 15.2,                  // Watts
  "voltage": 5.1,                 // Input voltage (V)
  "current": 2.98,                // Amps

  // ASIC Configuration
  "frequency": 575,               // MHz
  "coreVoltage": 1200,           // mV
  "coreVoltageActual": 1198,     // mV (actual reading)
  "overclockEnabled": 1,

  // Thermal Monitoring
  "temp": 52.5,                   // ASIC temp (°C)
  "temp2": 51.8,                  // Secondary temp sensor
  "vrTemp": 48.3,                 // Voltage regulator temp

  // Mining Statistics
  "sharesAccepted": 1234,
  "sharesRejected": 5,
  "bestDiff": 1234567.8,
  "bestSessionDiff": 987654.3,

  // Pool Configuration
  "stratumURL": "stratum+tcp://pool.example.com",
  "stratumPort": 3333,
  "stratumUser": "bc1q...",
  "poolDifficulty": 1024.0,

  // System Information
  "uptimeSeconds": 86400,
  "version": "v2.1.0",
  "hostname": "bitaxe",
  "ssid": "YourWiFi",
  "ipv4": "192.168.1.100",
  "wifiRSSI": -45,

  // Fan Control
  "fanspeed": 75,                 // % duty cycle
  "fanrpm": 4500,
  "autofanspeed": 1,

  // Memory Stats
  "freeHeap": 45000,
  "freeHeapInternal": 12000,
  "freeHeapSpiram": 33000
}
```

**GET `/api/system/statistics`** - Historical time-series data

Parameters:
- `columns` (optional): Comma-separated list of metrics to retrieve
  - Available columns: hashrate, asicTemp, vrTemp, asicVoltage, voltage, power, current, fanSpeed, fanRpm, wifiRssi, freeHeap

Response structure:
```json
{
  "currentTimestamp": 1699123456,
  "labels": ["hashrate", "asicTemp", "power"],
  "statistics": [
    [550.2, 52.1, 15.3],  // Data point 1
    [548.9, 52.3, 15.2],  // Data point 2
    [551.1, 52.0, 15.4]   // Data point 3
  ]
}
```

**PATCH `/api/system`** - Modify device settings

Can update configuration in real-time:
```json
{
  "frequency": 575,
  "coreVoltage": 1200,
  "fanspeed": 80,
  "autofanspeed": 0
}
```

**POST `/api/system/restart`** - Restart device (required after some config changes)

### 3. Analysis of Existing Tools

**[bitaxe-temp-monitor](https://github.com/Hurllz/bitaxe-temp-monitor)**
- Continuous polling of `/api/system/info`
- Monitors: temperature, hashrate, voltage
- Auto-tuning: Adjusts frequency/voltage based on thermal targets
- Supports both GUI and headless modes

**[Bitaxe-Hashrate-Benchmark](https://github.com/WhiteyCookie/Bitaxe-Hashrate-Benchmark)**
- Systematic testing of voltage/frequency combinations
- Tests: voltages [1150, 1200, 1250 mV] × frequencies [550, 575, 600 MHz]
- Collects: avg hashrate, temp, power, efficiency (J/TH)
- 120-second stabilization period after config changes
- Saves results as JSON sorted by performance
- Includes safety limits and cooldown periods

**Key Learnings:**
1. Need 2-3 minute stabilization period after changing settings
2. Temperature must be monitored to prevent thermal throttling
3. J/TH efficiency = power(W) / (hashrate(GH/s) / 1000)
4. JSON storage format works well for benchmark results
5. Retry logic needed for API calls (network instability)

---

## System Architecture

### Design Principles

1. **Multi-device support**: Poll multiple miners concurrently
2. **Clock setting correlation**: Tag all data with current freq/voltage config
3. **Time-series storage**: Maintain historical data with timestamps
4. **Flexible analysis**: Support ad-hoc queries and aggregations
5. **Separation of concerns**: Decouple collection, storage, and analysis
6. **Safety first**: Monitor temps, respect limits, graceful degradation

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Bitaxe Logger System                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Data Collection Layer (Async Polling)          │ │
│  │  - HTTP Client Pool                                     │ │
│  │  - Multi-device concurrent polling                      │ │
│  │  - Error handling & retry logic                         │ │
│  │  - Configurable poll intervals                          │ │
│  └────────────────┬───────────────────────────────────────┘ │
│                   │                                           │
│                   ▼                                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Storage Layer (Time-Series Database)            │ │
│  │  - SQLite with timestamp indexing                       │ │
│  │  - Clock setting tags (freq, voltage)                   │ │
│  │  - Per-device tables                                    │ │
│  │  - Automatic data rotation/archival                     │ │
│  └────────────────┬───────────────────────────────────────┘ │
│                   │                                           │
│                   ▼                                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Analysis Layer (Metrics & Aggregation)         │ │
│  │  - Efficiency calculations (J/TH, GH/W)                 │ │
│  │  - Statistical analysis per config                      │ │
│  │  - Config comparison & ranking                          │ │
│  │  - Anomaly detection                                    │ │
│  └────────────────┬───────────────────────────────────────┘ │
│                   │                                           │
│                   ▼                                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │    Visualization Layer (Reports & Dashboards)          │ │
│  │  - CSV/JSON export                                      │ │
│  │  - Terminal UI (optional)                               │ │
│  │  - Web dashboard (future)                               │ │
│  │  - Matplotlib/Plotly graphs                             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘

   Bitaxe 1          Bitaxe 2
  (192.168.1.100)  (192.168.1.101)
       ▲                ▲
       │                │
       └────────┬───────┘
                │
         HTTP API Polling
```

### Data Model

#### Device Configuration Table
```sql
CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    ip_address TEXT NOT NULL,
    hostname TEXT,
    model TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Clock Configuration Table
```sql
CREATE TABLE clock_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frequency INTEGER NOT NULL,         -- MHz
    core_voltage INTEGER NOT NULL,      -- mV
    UNIQUE(frequency, core_voltage)
);
```

#### Performance Metrics Table
```sql
CREATE TABLE performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    config_id INTEGER NOT NULL,

    -- Performance
    hashrate REAL,                      -- GH/s
    power REAL,                         -- W
    voltage REAL,                       -- V
    current REAL,                       -- A

    -- Thermal
    asic_temp REAL,                     -- °C
    vreg_temp REAL,                     -- °C
    fan_speed INTEGER,                  -- %
    fan_rpm INTEGER,

    -- Mining Stats
    shares_accepted INTEGER,
    shares_rejected INTEGER,
    best_diff REAL,
    uptime INTEGER,                     -- seconds

    -- Calculated Metrics
    efficiency_jth REAL,                -- J/TH (calculated)
    efficiency_ghw REAL,                -- GH/W (calculated)

    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (config_id) REFERENCES clock_configs(id)
);

CREATE INDEX idx_device_timestamp ON performance_metrics(device_id, timestamp);
CREATE INDEX idx_config ON performance_metrics(config_id);
CREATE INDEX idx_timestamp ON performance_metrics(timestamp);
```

#### Session Metadata Table
```sql
CREATE TABLE test_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    config_id INTEGER NOT NULL,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (config_id) REFERENCES clock_configs(id)
);
```

---

## Implementation Plan

### Phase 1: Basic Data Logger (MVP)

**Goal:** Collect and store real-time metrics from multiple Bitaxe miners

**Components:**
1. Configuration management (YAML/JSON for device IPs)
2. HTTP client with connection pooling
3. SQLite database setup
4. Async polling loop (configurable interval, default 30s)
5. Error handling and logging

**Files to create:**
```
bitaxe-monitor/
├── config.yaml                 # Device configuration
├── logger.py                   # Main logging daemon
├── api_client.py              # Bitaxe REST API wrapper
├── database.py                # SQLite database operations
├── models.py                  # Data models/schemas
└── requirements.txt           # Dependencies
```

**Key Features:**
- Poll `/api/system/info` every 30 seconds (configurable)
- Auto-detect current clock configuration
- Calculate efficiency metrics on-the-fly
- Graceful handling of offline devices
- Console logging with device status

**Sample config.yaml:**
```yaml
devices:
  - name: "bitaxe-1"
    ip: "192.168.1.100"
    enabled: true
  - name: "bitaxe-2"
    ip: "192.168.1.101"
    enabled: true

logging:
  poll_interval: 30              # seconds
  database_path: "./data/metrics.db"
  log_level: "INFO"

safety:
  max_temp_warning: 65           # °C
  max_temp_shutdown: 70          # °C
```

### Phase 2: Clock Setting Segmentation

**Goal:** Track and segment data by different frequency/voltage configurations

**Features:**
1. Detect config changes automatically
2. Create new test sessions when config changes
3. Mark configuration boundaries in database
4. Add manual session management CLI

**New Components:**
- Session manager
- Config change detector
- Manual testing mode

**CLI Commands:**
```bash
# Start a new test session
python logger.py session start --device bitaxe-1 --freq 575 --voltage 1200 --notes "Testing efficiency"

# End current session
python logger.py session end --device bitaxe-1

# List active sessions
python logger.py session list
```

### Phase 3: Analysis & Optimization Tools

**Goal:** Analyze collected data to find optimal settings

**Components:**

**3.1 Config Analyzer (`analyzer.py`)**
```python
# Generate performance report per config
python analyzer.py compare-configs --device bitaxe-1

# Find optimal config for efficiency
python analyzer.py optimize --metric efficiency --device bitaxe-1

# Compare two configs
python analyzer.py compare --config1 "575MHz@1200mV" --config2 "600MHz@1250mV"
```

**3.2 Statistical Analysis**
- Mean/median/stddev for hashrate, temp, power per config
- Identify stable operating ranges
- Detect thermal throttling events
- Calculate cost/benefit of overclocking

**3.3 Export Tools**
```python
# Export to CSV for external analysis
python analyzer.py export --format csv --output results.csv

# Export specific session
python analyzer.py export --session-id 42 --format json
```

### Phase 4: Visualization & Reporting

**Goal:** Create visual representations of performance data

**Tools:**

**4.1 Terminal Dashboard (`dashboard.py`)**
Real-time TUI using Rich or Textual:
```
┌─ Bitaxe Monitor ───────────────────── 2025-10-23 14:30:00 ─┐
│                                                              │
│ Device: bitaxe-1 (192.168.1.100)        Config: 575@1200    │
│ ├─ Hashrate:     550.2 GH/s    ████████████████░░ 92%      │
│ ├─ Temperature:   52.3°C       ████████░░░░░░░░░░ 40%      │
│ ├─ Power:         15.2W        ████████████░░░░░░ 60%      │
│ └─ Efficiency:    27.6 J/TH    ████████████████░░ Excellent│
│                                                              │
│ Device: bitaxe-2 (192.168.1.101)        Config: 600@1250    │
│ ├─ Hashrate:     585.8 GH/s    ████████████████▓▓ 98%      │
│ ├─ Temperature:   58.1°C       ███████████░░░░░░░ 55%      │
│ ├─ Power:         17.8W        █████████████████░ 71%      │
│ └─ Efficiency:    30.4 J/TH    █████████████░░░░░ Good     │
│                                                              │
│ [Q]uit  [R]efresh  [E]xport  [S]essions                    │
└──────────────────────────────────────────────────────────────┘
```

**4.2 Static Reports (`reporter.py`)**
Generate markdown/HTML reports:
```bash
python reporter.py generate --device bitaxe-1 --days 7
```

Output:
```markdown
# Bitaxe Performance Report: bitaxe-1
Period: 2025-10-16 to 2025-10-23

## Configuration Performance Summary

| Config       | Avg Hashrate | Avg Temp | Avg Power | Efficiency | Runtime |
|--------------|--------------|----------|-----------|------------|---------|
| 550MHz@1150mV| 505.2 GH/s   | 48.3°C   | 13.2W     | 26.1 J/TH  | 24h     |
| 575MHz@1200mV| 550.8 GH/s   | 52.1°C   | 15.1W     | 27.4 J/TH  | 48h     |
| 600MHz@1250mV| 585.3 GH/s   | 57.8°C   | 17.6W     | 30.1 J/TH  | 12h     |

## Recommendations
- **Optimal efficiency**: 550MHz@1150mV (26.1 J/TH)
- **Optimal hashrate**: 600MHz@1250mV (585.3 GH/s)
- **Best balance**: 575MHz@1200mV (sweet spot)
```

**4.3 Graphical Plots (`plotter.py`)**
Using matplotlib/plotly:
```bash
# Time series plot for a session
python plotter.py timeseries --session-id 42

# Compare multiple configs
python plotter.py compare --configs "550@1150,575@1200,600@1250"

# Efficiency scatter plot
python plotter.py scatter --x power --y hashrate --color-by config
```

Example plots:
- Hashrate vs. time (colored by config)
- Temperature vs. power consumption
- Efficiency comparison bar chart
- Pareto frontier (hashrate vs. efficiency)

---

## Technical Specifications

### Technology Stack

**Core:**
- Python 3.11+
- asyncio for concurrent polling
- aiohttp for HTTP client
- SQLite3 for storage

**Dependencies:**
```
aiohttp>=3.9.0          # Async HTTP client
pyyaml>=6.0             # Config parsing
python-dotenv>=1.0      # Environment variables
pandas>=2.0             # Data analysis
numpy>=1.24             # Numerical operations
matplotlib>=3.7         # Plotting
plotly>=5.17            # Interactive plots
rich>=13.0              # Terminal UI
click>=8.1              # CLI framework
pydantic>=2.0           # Data validation
```

**Optional:**
```
textual>=0.40           # Advanced TUI framework
flask>=3.0              # Web dashboard (future)
prometheus_client>=0.18 # Metrics export (future)
```

### Performance Considerations

**Polling Strategy:**
- Default 30-second interval balances data granularity vs. API load
- Exponential backoff for failed requests (1s, 2s, 4s, 8s, max 60s)
- Concurrent polling using asyncio.gather() for multiple devices
- Connection pooling to reduce overhead

**Database Optimization:**
- Indexes on timestamp, device_id, config_id for fast queries
- Batch inserts (buffer 10 samples before commit)
- Periodic vacuuming to reclaim space
- Optional data archival (compress/delete data older than N days)

**Resource Usage:**
- Expected: <50MB RAM for 2 devices with 7 days of data
- Database growth: ~1KB per sample × 2 devices × 2880 samples/day = ~5.5MB/day
- CPU: Minimal (async I/O bound)

### Safety Features

1. **Thermal Protection:**
   - Warning at 65°C (configurable)
   - Emergency shutdown trigger at 70°C (sends restart command to reduce freq)
   - Alerts logged to console and database

2. **API Error Handling:**
   - Retry with exponential backoff
   - Mark device as offline after 5 consecutive failures
   - Auto-reconnect on recovery

3. **Data Validation:**
   - Pydantic models validate API responses
   - Reject outlier values (e.g., hashrate >1000 GH/s, temp >100°C)
   - Log validation errors for debugging

### Configuration Testing Workflow

Recommended approach for finding optimal settings:

```bash
# 1. Start with conservative baseline
python logger.py session start --device bitaxe-1 --freq 550 --voltage 1150 --notes "Baseline"
# Run for 2 hours to gather stable data

# 2. Increase frequency in steps
python logger.py session start --device bitaxe-1 --freq 575 --voltage 1200
# Run for 2 hours

python logger.py session start --device bitaxe-1 --freq 600 --voltage 1250
# Run for 2 hours

# 3. Test voltage variations at optimal frequency
python logger.py session start --device bitaxe-1 --freq 575 --voltage 1150
python logger.py session start --device bitaxe-1 --freq 575 --voltage 1200
python logger.py session start --device bitaxe-1 --freq 575 --voltage 1250

# 4. Analyze results
python analyzer.py optimize --metric efficiency
python analyzer.py compare-configs

# 5. Generate report
python reporter.py generate --days 1 --output optimal-config-report.md
```

---

## Project File Structure

```
bitaxe-monitor/
├── README.md                      # Project documentation
├── requirements.txt               # Python dependencies
├── config.yaml                    # Device and logging configuration
├── .env                           # Environment variables (optional)
│
├── data/                          # Data directory
│   ├── metrics.db                 # SQLite database
│   ├── logs/                      # Application logs
│   └── exports/                   # Exported CSV/JSON files
│
├── src/                           # Source code
│   ├── __init__.py
│   ├── api_client.py             # Bitaxe API wrapper
│   ├── database.py               # Database operations
│   ├── models.py                 # Pydantic data models
│   ├── logger.py                 # Main logging daemon
│   ├── session.py                # Session management
│   ├── analyzer.py               # Data analysis tools
│   ├── plotter.py                # Visualization
│   ├── reporter.py               # Report generation
│   └── utils.py                  # Helper functions
│
├── cli/                           # CLI entry points
│   ├── __init__.py
│   ├── logger_cli.py             # Logger commands
│   ├── session_cli.py            # Session commands
│   ├── analyze_cli.py            # Analysis commands
│   └── dashboard_cli.py          # Dashboard commands
│
├── tests/                         # Unit tests
│   ├── test_api_client.py
│   ├── test_database.py
│   ├── test_analyzer.py
│   └── fixtures/                 # Test data
│
└── docs/                          # Additional documentation
    ├── API.md                    # Bitaxe API reference
    ├── SCHEMA.md                 # Database schema details
    └── EXAMPLES.md               # Usage examples
```

---

## Example Code Snippets

### 1. API Client (api_client.py)

```python
import aiohttp
from typing import Dict, Optional
from models import SystemInfo

class BitaxeClient:
    """Async HTTP client for Bitaxe API"""

    def __init__(self, ip_address: str, timeout: int = 10):
        self.base_url = f"http://{ip_address}"
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_system_info(self) -> SystemInfo:
        """Fetch current system information"""
        async with self.session.get(f"{self.base_url}/api/system/info") as response:
            response.raise_for_status()
            data = await response.json()
            return SystemInfo(**data)

    async def get_statistics(self, columns: list[str]) -> Dict:
        """Fetch historical statistics"""
        params = {"columns": ",".join(columns)}
        async with self.session.get(
            f"{self.base_url}/api/system/statistics",
            params=params
        ) as response:
            response.raise_for_status()
            return await response.json()

    async def update_config(self, frequency: int, core_voltage: int) -> None:
        """Update device frequency and voltage"""
        payload = {
            "frequency": frequency,
            "coreVoltage": core_voltage
        }
        async with self.session.patch(
            f"{self.base_url}/api/system",
            json=payload
        ) as response:
            response.raise_for_status()

    async def restart(self) -> None:
        """Restart the device"""
        async with self.session.post(f"{self.base_url}/api/system/restart") as response:
            response.raise_for_status()
```

### 2. Data Models (models.py)

```python
from pydantic import BaseModel, Field, computed_field
from datetime import datetime
from typing import Optional

class SystemInfo(BaseModel):
    """System information from /api/system/info"""

    # Performance
    hashRate: float = Field(alias="hashRate")
    power: float
    voltage: float
    current: float

    # Configuration
    frequency: int
    coreVoltage: int = Field(alias="coreVoltage")
    coreVoltageActual: Optional[int] = Field(None, alias="coreVoltageActual")

    # Thermal
    temp: float
    temp2: Optional[float] = None
    vrTemp: float = Field(alias="vrTemp")
    fanspeed: int
    fanrpm: int

    # Mining stats
    sharesAccepted: int = Field(alias="sharesAccepted")
    sharesRejected: int = Field(alias="sharesRejected")
    uptimeSeconds: int = Field(alias="uptimeSeconds")

    # Device info
    hostname: str
    ASICModel: str = Field(alias="ASICModel")

    @computed_field
    @property
    def efficiency_jth(self) -> float:
        """Calculate J/TH efficiency"""
        if self.hashRate == 0:
            return 0.0
        return (self.power / (self.hashRate / 1000.0))

    @computed_field
    @property
    def efficiency_ghw(self) -> float:
        """Calculate GH/W efficiency"""
        if self.power == 0:
            return 0.0
        return self.hashRate / self.power

    class Config:
        populate_by_name = True


class PerformanceMetric(BaseModel):
    """Database model for performance metrics"""

    device_id: str
    timestamp: datetime
    config_id: int

    hashrate: float
    power: float
    voltage: float
    current: float

    asic_temp: float
    vreg_temp: float
    fan_speed: int
    fan_rpm: int

    shares_accepted: int
    shares_rejected: int
    uptime: int

    efficiency_jth: float
    efficiency_ghw: float
```

### 3. Main Logger Loop (logger.py)

```python
import asyncio
import logging
from datetime import datetime
from typing import List
from api_client import BitaxeClient
from database import Database
from models import SystemInfo, PerformanceMetric

logger = logging.getLogger(__name__)

class BitaxeLogger:
    """Main logger daemon for Bitaxe devices"""

    def __init__(self, config: dict, db: Database):
        self.config = config
        self.db = db
        self.devices = config["devices"]
        self.poll_interval = config["logging"]["poll_interval"]
        self.running = False

    async def poll_device(self, device: dict) -> Optional[SystemInfo]:
        """Poll a single device"""
        try:
            async with BitaxeClient(device["ip"]) as client:
                return await client.get_system_info()
        except Exception as e:
            logger.error(f"Failed to poll {device['name']}: {e}")
            return None

    async def poll_all_devices(self) -> List[tuple[str, SystemInfo]]:
        """Poll all devices concurrently"""
        tasks = []
        for device in self.devices:
            if device.get("enabled", True):
                task = self.poll_device(device)
                tasks.append((device["name"], task))

        results = []
        for device_name, task in tasks:
            info = await task
            if info:
                results.append((device_name, info))

        return results

    def store_metrics(self, device_id: str, info: SystemInfo):
        """Store metrics in database"""
        # Get or create clock config
        config_id = self.db.get_or_create_config(
            frequency=info.frequency,
            core_voltage=info.coreVoltage
        )

        # Create metric record
        metric = PerformanceMetric(
            device_id=device_id,
            timestamp=datetime.now(),
            config_id=config_id,
            hashrate=info.hashRate,
            power=info.power,
            voltage=info.voltage,
            current=info.current,
            asic_temp=info.temp,
            vreg_temp=info.vrTemp,
            fan_speed=info.fanspeed,
            fan_rpm=info.fanrpm,
            shares_accepted=info.sharesAccepted,
            shares_rejected=info.sharesRejected,
            uptime=info.uptimeSeconds,
            efficiency_jth=info.efficiency_jth,
            efficiency_ghw=info.efficiency_ghw
        )

        self.db.insert_metric(metric)

        # Check safety thresholds
        max_temp = self.config["safety"]["max_temp_warning"]
        if info.temp > max_temp:
            logger.warning(
                f"{device_id}: Temperature {info.temp}°C exceeds threshold {max_temp}°C"
            )

    async def run(self):
        """Main logging loop"""
        self.running = True
        logger.info("Starting Bitaxe logger...")

        while self.running:
            try:
                # Poll all devices
                results = await self.poll_all_devices()

                # Store results
                for device_id, info in results:
                    self.store_metrics(device_id, info)
                    logger.info(
                        f"{device_id}: {info.hashRate:.1f} GH/s, "
                        f"{info.temp:.1f}°C, {info.power:.1f}W, "
                        f"{info.efficiency_jth:.1f} J/TH"
                    )

                # Wait for next poll
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)  # Back off on error

    def stop(self):
        """Stop the logger"""
        self.running = False
        logger.info("Stopping logger...")
```

### 4. Database Operations (database.py)

```python
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
from models import PerformanceMetric
import pandas as pd

class Database:
    """SQLite database manager"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.init_schema()

    def init_schema(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()

        # Devices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                ip_address TEXT NOT NULL,
                hostname TEXT,
                model TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Clock configs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clock_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                frequency INTEGER NOT NULL,
                core_voltage INTEGER NOT NULL,
                UNIQUE(frequency, core_voltage)
            )
        """)

        # Performance metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config_id INTEGER NOT NULL,

                hashrate REAL,
                power REAL,
                voltage REAL,
                current REAL,

                asic_temp REAL,
                vreg_temp REAL,
                fan_speed INTEGER,
                fan_rpm INTEGER,

                shares_accepted INTEGER,
                shares_rejected INTEGER,
                uptime INTEGER,

                efficiency_jth REAL,
                efficiency_ghw REAL,

                FOREIGN KEY (device_id) REFERENCES devices(id),
                FOREIGN KEY (config_id) REFERENCES clock_configs(id)
            )
        """)

        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_device_timestamp
            ON performance_metrics(device_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config
            ON performance_metrics(config_id)
        """)

        self.conn.commit()

    def get_or_create_config(self, frequency: int, core_voltage: int) -> int:
        """Get or create clock configuration, return ID"""
        cursor = self.conn.cursor()

        # Try to find existing
        cursor.execute(
            "SELECT id FROM clock_configs WHERE frequency = ? AND core_voltage = ?",
            (frequency, core_voltage)
        )
        row = cursor.fetchone()

        if row:
            return row[0]

        # Create new
        cursor.execute(
            "INSERT INTO clock_configs (frequency, core_voltage) VALUES (?, ?)",
            (frequency, core_voltage)
        )
        self.conn.commit()
        return cursor.lastrowid

    def insert_metric(self, metric: PerformanceMetric):
        """Insert performance metric"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO performance_metrics (
                device_id, timestamp, config_id,
                hashrate, power, voltage, current,
                asic_temp, vreg_temp, fan_speed, fan_rpm,
                shares_accepted, shares_rejected, uptime,
                efficiency_jth, efficiency_ghw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metric.device_id, metric.timestamp, metric.config_id,
            metric.hashrate, metric.power, metric.voltage, metric.current,
            metric.asic_temp, metric.vreg_temp, metric.fan_speed, metric.fan_rpm,
            metric.shares_accepted, metric.shares_rejected, metric.uptime,
            metric.efficiency_jth, metric.efficiency_ghw
        ))
        self.conn.commit()

    def get_metrics_by_config(
        self,
        device_id: str,
        config_id: int,
        hours: int = 24
    ) -> pd.DataFrame:
        """Get metrics for a specific configuration"""
        since = datetime.now() - timedelta(hours=hours)

        query = """
            SELECT
                timestamp, hashrate, power, asic_temp, vreg_temp,
                efficiency_jth, efficiency_ghw
            FROM performance_metrics
            WHERE device_id = ?
              AND config_id = ?
              AND timestamp > ?
            ORDER BY timestamp
        """

        return pd.read_sql_query(
            query,
            self.conn,
            params=(device_id, config_id, since)
        )

    def get_config_summary(self, device_id: str) -> pd.DataFrame:
        """Get aggregate stats per configuration"""
        query = """
            SELECT
                cc.frequency,
                cc.core_voltage,
                COUNT(*) as sample_count,
                AVG(pm.hashrate) as avg_hashrate,
                AVG(pm.power) as avg_power,
                AVG(pm.asic_temp) as avg_temp,
                AVG(pm.efficiency_jth) as avg_efficiency_jth,
                MIN(pm.timestamp) as first_seen,
                MAX(pm.timestamp) as last_seen
            FROM performance_metrics pm
            JOIN clock_configs cc ON pm.config_id = cc.id
            WHERE pm.device_id = ?
            GROUP BY cc.id
            ORDER BY avg_efficiency_jth ASC
        """

        return pd.read_sql_query(query, self.conn, params=(device_id,))
```

---

## Next Steps

### Immediate Actions (Week 1)

1. **Set up development environment**
   ```bash
   mkdir -p code/bitaxe-monitor
   cd code/bitaxe-monitor
   python3 -m venv venv
   source venv/bin/activate
   pip install aiohttp pyyaml pydantic pandas
   ```

2. **Create basic config.yaml** with your Bitaxe IP addresses

3. **Implement Phase 1 components**:
   - `api_client.py` - Test connectivity to both miners
   - `database.py` - Set up SQLite schema
   - `logger.py` - Basic polling loop
   - Run for 24 hours to collect baseline data

4. **Validate data collection**:
   - Check database for expected sample count
   - Verify efficiency calculations
   - Ensure no polling errors

### Short-term Goals (Week 2-3)

5. **Implement session management** (Phase 2)
   - Add session tracking
   - Create CLI for starting/stopping sessions
   - Test with different clock settings

6. **Build analyzer** (Phase 3)
   - Config comparison queries
   - Statistical analysis
   - Export functionality

7. **Generate first optimization report**
   - Test 3-4 different configurations per device
   - Run each for 2-4 hours
   - Identify optimal settings

### Long-term Enhancements

8. **Visualization** (Phase 4)
   - Terminal dashboard
   - Static plots
   - HTML reports

9. **Advanced Features**:
   - Auto-tuning algorithm
   - Anomaly detection
   - Web dashboard
   - Prometheus metrics export
   - Email/Slack alerts

10. **Documentation**:
    - User guide
    - API reference
    - Optimization cookbook

---

## References

- [ESP-Miner GitHub](https://github.com/bitaxeorg/ESP-Miner)
- [Bitaxe Hardware](https://github.com/skot/bitaxe)
- [Bitaxe API Wiki](https://osmu.wiki/bitaxe/api/)
- [bitaxe-temp-monitor](https://github.com/Hurllz/bitaxe-temp-monitor)
- [Bitaxe-Hashrate-Benchmark](https://github.com/WhiteyCookie/Bitaxe-Hashrate-Benchmark)

---

## Appendix A: Sample API Responses

### /api/system/info (Abbreviated)
```json
{
  "hashRate": 550.2,
  "power": 15.3,
  "voltage": 5.08,
  "current": 3.01,
  "frequency": 575,
  "coreVoltage": 1200,
  "coreVoltageActual": 1198,
  "temp": 52.5,
  "vrTemp": 48.2,
  "fanspeed": 75,
  "fanrpm": 4500,
  "sharesAccepted": 1234,
  "sharesRejected": 5,
  "hostname": "bitaxe",
  "ASICModel": "BM1366"
}
```

### /api/system/statistics
```json
{
  "currentTimestamp": 1699123456,
  "labels": ["hashrate", "asicTemp", "power"],
  "statistics": [
    [550.2, 52.1, 15.3],
    [548.9, 52.3, 15.2],
    [551.1, 52.0, 15.4]
  ]
}
```

---

## Appendix B: Efficiency Calculations

**J/TH (Joules per Terahash)** - Lower is better
```
J/TH = Power(W) / (Hashrate(GH/s) / 1000)
     = Power(W) / Hashrate(TH/s)

Example: 15.3W / (550.2 GH/s / 1000) = 27.8 J/TH
```

**GH/W (Gigahash per Watt)** - Higher is better
```
GH/W = Hashrate(GH/s) / Power(W)

Example: 550.2 GH/s / 15.3W = 35.9 GH/W
```

**BM1366 Rated Efficiency:** 0.021 J/GH = 21 J/TH (theoretical)

In practice, with power supply losses and ESP32 overhead, expect:
- Conservative (550MHz@1150mV): ~26-28 J/TH
- Balanced (575MHz@1200mV): ~28-30 J/TH
- Overclocked (600MHz@1250mV): ~30-33 J/TH

---

## Appendix C: Safety Limits

**Temperature Limits:**
- BM1366 max junction temp: 125°C
- Recommended continuous: <65°C
- Warning threshold: 65°C
- Throttle/shutdown: 70°C

**Voltage Limits:**
- BM1366 core voltage range: 0.9V - 1.4V (900-1400mV)
- Conservative range: 1150-1250mV
- Overclocking range: 1250-1350mV (use caution)
- Absolute max: 1400mV (not recommended)

**Frequency Limits:**
- Stock frequency: 490-525 MHz
- Safe overclocking: 550-600 MHz
- Aggressive OC: 600-650 MHz (monitor temps closely)
- Absolute max: ~700 MHz (unstable, may damage ASIC)

**Power Consumption:**
- Typical: 13-18W @ 5V input
- Max recommended: 20W continuous
- PSU requirement: 25W (5V @ 5A) minimum
