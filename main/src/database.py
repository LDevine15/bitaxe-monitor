"""SQLite database operations for performance metrics storage."""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from .models import PerformanceMetric, ClockConfig

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for Bitaxe performance metrics."""

    def __init__(self, db_path: str):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path

        # Create parent directory if it doesn't exist
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()
        logger.info(f"Database initialized at {db_path}")

    def init_schema(self):
        """Initialize database schema with tables and indexes."""
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

        # Clock configurations table
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

        # Test sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS test_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                config_id INTEGER NOT NULL,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (device_id) REFERENCES devices(id),
                FOREIGN KEY (config_id) REFERENCES clock_configs(id)
            )
        """)

        # Create indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_device_timestamp
            ON performance_metrics(device_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config
            ON performance_metrics(config_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON performance_metrics(timestamp)
        """)

        self.conn.commit()
        logger.debug("Database schema initialized")

    def register_device(self, device_id: str, ip_address: str, hostname: str = None, model: str = None):
        """Register or update a device.

        Args:
            device_id: Unique device identifier
            ip_address: IP address of device
            hostname: Device hostname (optional)
            model: Device model (optional)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (id, ip_address, hostname, model)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ip_address = excluded.ip_address,
                hostname = excluded.hostname,
                model = excluded.model
        """, (device_id, ip_address, hostname, model))
        self.conn.commit()
        logger.debug(f"Registered device: {device_id} ({ip_address})")

    def get_or_create_config(self, frequency: int, core_voltage: int) -> int:
        """Get or create clock configuration, return ID.

        Args:
            frequency: Frequency in MHz
            core_voltage: Core voltage in mV

        Returns:
            Clock configuration ID
        """
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
        config_id = cursor.lastrowid
        logger.debug(f"Created new config: {frequency}MHz@{core_voltage}mV (ID: {config_id})")
        return config_id

    def get_config(self, config_id: int) -> Optional[ClockConfig]:
        """Get clock configuration by ID.

        Args:
            config_id: Configuration ID

        Returns:
            ClockConfig object or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, frequency, core_voltage FROM clock_configs WHERE id = ?",
            (config_id,)
        )
        row = cursor.fetchone()

        if row:
            return ClockConfig(
                id=row[0],
                frequency=row[1],
                core_voltage=row[2]
            )
        return None

    def insert_metric(self, metric: PerformanceMetric):
        """Insert performance metric record.

        Args:
            metric: PerformanceMetric object to store
        """
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

    def get_latest_metric(self, device_id: str) -> Optional[dict]:
        """Get latest performance metric for a device.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with metric data or None if no data
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                pm.*,
                cc.frequency,
                cc.core_voltage
            FROM performance_metrics pm
            JOIN clock_configs cc ON pm.config_id = cc.id
            WHERE pm.device_id = ?
            ORDER BY pm.timestamp DESC
            LIMIT 1
        """, (device_id,))

        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

    def get_metric_count(self, device_id: str = None) -> int:
        """Get total number of metrics stored.

        Args:
            device_id: Optional device filter

        Returns:
            Count of metrics
        """
        cursor = self.conn.cursor()
        if device_id:
            cursor.execute(
                "SELECT COUNT(*) FROM performance_metrics WHERE device_id = ?",
                (device_id,)
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM performance_metrics")

        return cursor.fetchone()[0]

    def get_devices(self) -> List[dict]:
        """Get all registered devices.

        Returns:
            List of device dictionaries
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM devices ORDER BY added_at")
        return [dict(row) for row in cursor.fetchall()]

    def get_configs_summary(self, device_id: str) -> List[dict]:
        """Get performance summary grouped by configuration.

        Args:
            device_id: Device identifier

        Returns:
            List of configuration summaries with aggregate metrics
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT
                cc.id as config_id,
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
        """, (device_id,))

        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
