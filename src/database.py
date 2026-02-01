"""SQLite database operations for performance metrics storage."""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
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

        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrent access across multiple processes
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=60000")  # 60s timeout for multi-process access
        self.conn.execute("PRAGMA synchronous=NORMAL")  # Faster than FULL, safe with WAL
        self.conn.execute("PRAGMA cache_size=-64000")   # 64MB cache (default is 2MB)

        self.init_schema()
        logger.info(f"Database initialized at {db_path}")

    def migrate_schema(self):
        """Apply schema migrations for existing databases."""
        cursor = self.conn.cursor()

        # Check if best_diff column exists
        cursor.execute("PRAGMA table_info(performance_metrics)")
        columns = [row[1] for row in cursor.fetchall()]

        # Add difficulty columns if they don't exist
        if 'best_diff' not in columns:
            logger.info("Migrating database: Adding difficulty tracking column...")
            cursor.execute("ALTER TABLE performance_metrics ADD COLUMN best_diff REAL")
            self.conn.commit()
            logger.info("Database migration completed successfully")

        # Check if pool columns exist in devices table
        cursor.execute("PRAGMA table_info(devices)")
        device_columns = [row[1] for row in cursor.fetchall()]

        # Add pool columns if they don't exist
        if 'stratum_url' not in device_columns:
            logger.info("Migrating database: Adding pool tracking columns to devices...")
            cursor.execute("ALTER TABLE devices ADD COLUMN stratum_url TEXT")
            cursor.execute("ALTER TABLE devices ADD COLUMN stratum_port INTEGER")
            cursor.execute("ALTER TABLE devices ADD COLUMN stratum_user TEXT")
            self.conn.commit()
            logger.info("Pool tracking migration completed successfully")

        # Check if stratum_diff and rejection_reasons columns exist
        cursor.execute("PRAGMA table_info(performance_metrics)")
        metrics_columns = [row[1] for row in cursor.fetchall()]

        if 'stratum_diff' not in metrics_columns:
            logger.info("Migrating database: Adding mining statistics columns...")
            cursor.execute("ALTER TABLE performance_metrics ADD COLUMN stratum_diff REAL")
            cursor.execute("ALTER TABLE performance_metrics ADD COLUMN rejection_reasons TEXT")
            self.conn.commit()
            logger.info("Mining statistics migration completed successfully")

        # Check if core_voltage_actual column exists
        cursor.execute("PRAGMA table_info(performance_metrics)")
        metrics_columns = [row[1] for row in cursor.fetchall()]

        if 'core_voltage_actual' not in metrics_columns:
            logger.info("Migrating database: Adding actual core voltage tracking...")
            cursor.execute("ALTER TABLE performance_metrics ADD COLUMN core_voltage_actual INTEGER")
            self.conn.commit()
            logger.info("Core voltage actual migration completed successfully")

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
                core_voltage_actual INTEGER,

                asic_temp REAL,
                vreg_temp REAL,
                fan_speed INTEGER,
                fan_rpm INTEGER,

                shares_accepted INTEGER,
                shares_rejected INTEGER,
                uptime INTEGER,

                efficiency_jth REAL,
                efficiency_ghw REAL,

                best_diff REAL,
                stratum_diff REAL,
                rejection_reasons TEXT,

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

        # Run migrations for existing databases
        self.migrate_schema()

    def register_device(self, device_id: str, ip_address: str, hostname: Optional[str] = None,
                       model: Optional[str] = None, stratum_url: Optional[str] = None,
                       stratum_port: Optional[int] = None, stratum_user: Optional[str] = None):
        """Register or update a device.

        Args:
            device_id: Unique device identifier
            ip_address: IP address of device
            hostname: Device hostname (optional)
            model: Device model (optional)
            stratum_url: Mining pool URL (optional)
            stratum_port: Mining pool port (optional)
            stratum_user: Mining pool username (optional)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (id, ip_address, hostname, model, stratum_url, stratum_port, stratum_user)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ip_address = excluded.ip_address,
                hostname = excluded.hostname,
                model = excluded.model,
                stratum_url = excluded.stratum_url,
                stratum_port = excluded.stratum_port,
                stratum_user = excluded.stratum_user
        """, (device_id, ip_address, hostname, model, stratum_url, stratum_port, stratum_user))
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
        if config_id is None:
            raise RuntimeError("Failed to create clock configuration: lastrowid is None")
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
                hashrate, power, voltage, current, core_voltage_actual,
                asic_temp, vreg_temp, fan_speed, fan_rpm,
                shares_accepted, shares_rejected, uptime,
                efficiency_jth, efficiency_ghw,
                best_diff, stratum_diff, rejection_reasons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metric.device_id, metric.timestamp, metric.config_id,
            metric.hashrate, metric.power, metric.voltage, metric.current, metric.core_voltage_actual,
            metric.asic_temp, metric.vreg_temp, metric.fan_speed, metric.fan_rpm,
            metric.shares_accepted, metric.shares_rejected, metric.uptime,
            metric.efficiency_jth, metric.efficiency_ghw,
            metric.best_diff, metric.stratum_diff, metric.rejection_reasons_json
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

    def get_metric_count(self, device_id: str | None = None) -> int:
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

    def get_bucketed_hashrate_trend(self, device_id: str, minutes: int, buckets: int) -> List[float]:
        """Get bucketed hashrate trend for a device.

        Args:
            device_id: Device identifier
            minutes: Lookback period in minutes
            buckets: Number of time buckets to divide data into

        Returns:
            List of average hashrate values per bucket
        """
        cursor = self.conn.cursor()

        # Get the most recent timestamp for this device to use as reference
        # This handles cases where data collection may be delayed
        cursor.execute(
            "SELECT MAX(timestamp) FROM performance_metrics WHERE device_id = ?",
            (device_id,)
        )
        max_row = cursor.fetchone()
        
        if max_row and max_row[0]:
            now = datetime.fromisoformat(max_row[0])
        else:
            now = datetime.now()
        
        cutoff = now - timedelta(minutes=minutes)

        # Get bucket averages
        cursor.execute("""
            WITH bucket_data AS (
                SELECT
                    CAST((julianday(?) - julianday(timestamp)) * 24 * 60 / ? AS INTEGER) as bucket,
                    hashrate
                FROM performance_metrics
                WHERE device_id = ?
                  AND timestamp >= ?
                  AND hashrate IS NOT NULL
            )
            SELECT
                bucket,
                AVG(hashrate) as avg_hashrate
            FROM bucket_data
            WHERE bucket >= 0 AND bucket < ?
            GROUP BY bucket
            ORDER BY bucket DESC
        """, (now, minutes / buckets, device_id, cutoff, buckets))

        # Create full bucket list (fill missing buckets with None)
        results = {row[0]: row[1] for row in cursor.fetchall()}
        return [results.get(i) for i in range(buckets - 1, -1, -1)]

    def get_bucketed_temp_trend(self, device_id: str, minutes: int, buckets: int) -> List[Optional[float]]:
        """Get bucketed temperature trend for a device.

        Args:
            device_id: Device identifier
            minutes: Lookback period in minutes
            buckets: Number of time buckets to divide data into

        Returns:
            List of average ASIC temperature values per bucket
        """
        cursor = self.conn.cursor()

        # Get the most recent timestamp for this device to use as reference
        # This handles cases where data collection may be delayed
        cursor.execute(
            "SELECT MAX(timestamp) FROM performance_metrics WHERE device_id = ?",
            (device_id,)
        )
        max_row = cursor.fetchone()
        
        if max_row and max_row[0]:
            now = datetime.fromisoformat(max_row[0])
        else:
            now = datetime.now()
        
        cutoff = now - timedelta(minutes=minutes)

        # Get bucket averages (filter out sensor errors < 0)
        cursor.execute("""
            WITH bucket_data AS (
                SELECT
                    CAST((julianday(?) - julianday(timestamp)) * 24 * 60 / ? AS INTEGER) as bucket,
                    asic_temp
                FROM performance_metrics
                WHERE device_id = ?
                  AND timestamp >= ?
                  AND asic_temp IS NOT NULL
                  AND asic_temp > 0
            )
            SELECT
                bucket,
                AVG(asic_temp) as avg_temp
            FROM bucket_data
            WHERE bucket >= 0 AND bucket < ?
            GROUP BY bucket
            ORDER BY bucket DESC
        """, (now, minutes / buckets, device_id, cutoff, buckets))

        # Create full bucket list (fill missing buckets with None)
        results = {row[0]: row[1] for row in cursor.fetchall()}
        return [results.get(i) for i in range(buckets - 1, -1, -1)]

    def get_all_device_ids(self) -> List[str]:
        """Get list of all device IDs.

        Returns:
            List of device identifier strings
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM devices ORDER BY added_at")
        return [row[0] for row in cursor.fetchall()]

    def get_config_changes(self, device_ids: List[str], minutes: int) -> List[dict]:
        """Get timestamps when config changed for any device in the swarm.

        Args:
            device_ids: List of device IDs to check
            minutes: Lookback period in minutes

        Returns:
            List of dicts with 'timestamp', 'device_id', 'frequency', 'core_voltage'
        """
        cursor = self.conn.cursor()
        
        # Get the most recent timestamp to use as reference
        # This handles cases where data collection may be delayed
        cursor.execute("SELECT MAX(timestamp) FROM performance_metrics")
        max_row = cursor.fetchone()
        
        if max_row and max_row[0]:
            reference_time = datetime.fromisoformat(max_row[0])
        else:
            reference_time = datetime.now()
        
        lookback = reference_time - timedelta(minutes=minutes)

        # For each device, find where config_id changes
        config_changes = []

        for device_id in device_ids:
            cursor.execute("""
                WITH config_transitions AS (
                    SELECT
                        timestamp,
                        config_id,
                        LAG(config_id) OVER (ORDER BY timestamp) as prev_config_id
                    FROM performance_metrics
                    WHERE device_id = ?
                      AND timestamp >= ?
                    ORDER BY timestamp
                )
                SELECT
                    ct.timestamp,
                    cc.frequency,
                    cc.core_voltage
                FROM config_transitions ct
                JOIN clock_configs cc ON ct.config_id = cc.id
                WHERE ct.prev_config_id IS NOT NULL
                  AND ct.config_id != ct.prev_config_id
                ORDER BY ct.timestamp
            """, (device_id, lookback))

            for row in cursor.fetchall():
                config_changes.append({
                    'timestamp': datetime.fromisoformat(row[0]),
                    'device_id': device_id,
                    'frequency': row[1],
                    'core_voltage': row[2]
                })

        # Sort by timestamp
        config_changes.sort(key=lambda x: x['timestamp'])
        return config_changes

    def get_device_health_status(self, device_id: str, minutes_threshold: int = 10) -> dict:
        """Get health status for a device.

        Args:
            device_id: Device identifier
            minutes_threshold: Minutes since last data to consider device offline

        Returns:
            Dictionary with health status:
            {
                'is_online': bool,
                'last_seen': datetime or None,
                'reject_rate': float (0-100),
                'shares_accepted': int,
                'shares_rejected': int
            }
        """
        cursor = self.conn.cursor()

        # Get latest metric
        cursor.execute("""
            SELECT
                timestamp,
                shares_accepted,
                shares_rejected
            FROM performance_metrics
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (device_id,))

        row = cursor.fetchone()

        if not row:
            return {
                'is_online': False,
                'last_seen': None,
                'reject_rate': 0.0,
                'shares_accepted': 0,
                'shares_rejected': 0
            }

        last_seen = datetime.fromisoformat(row[0])
        shares_accepted = row[1]
        shares_rejected = row[2]

        # Check if online (has data within threshold)
        time_diff = (datetime.now() - last_seen).total_seconds() / 60
        is_online = time_diff <= minutes_threshold

        # Calculate reject rate
        total_shares = shares_accepted + shares_rejected
        reject_rate = (shares_rejected / total_shares * 100) if total_shares > 0 else 0.0

        return {
            'is_online': is_online,
            'last_seen': last_seen,
            'reject_rate': reject_rate,
            'shares_accepted': shares_accepted,
            'shares_rejected': shares_rejected
        }

    def get_all_device_health(self, device_ids: List[str], minutes_threshold: int = 10) -> Dict[str, dict]:
        """Get health status for all devices.

        Args:
            device_ids: List of device identifiers
            minutes_threshold: Minutes since last data to consider device offline

        Returns:
            Dictionary mapping device_id to health status dict
        """
        return {
            device_id: self.get_device_health_status(device_id, minutes_threshold)
            for device_id in device_ids
        }

    def close(self):
        """Close database connection with WAL checkpoint."""
        if self.conn:
            try:
                # Checkpoint WAL to main database file before closing
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                logger.warning(f"WAL checkpoint failed: {e}")
            self.conn.close()
            logger.info("Database connection closed")
