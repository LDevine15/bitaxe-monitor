#!/usr/bin/env python3
"""Real-time terminal dashboard for Bitaxe miners."""

import sys
import time
import yaml
import subprocess
import platform
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.progress import BarColumn, Progress, TextColumn

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.analyzer import Analyzer
from src.remote_provider import RemoteProvider


class BitaxeDashboard:
    """Real-time terminal dashboard for Bitaxe monitoring."""

    def __init__(self, config: dict, db: Database = None, analyzer: Analyzer = None,
                 lite_mode: bool = False, remote_provider: RemoteProvider = None):
        """Initialize dashboard.

        Args:
            config: Configuration dictionary
            db: Database instance (for local mode)
            analyzer: Analyzer instance (for local mode)
            lite_mode: Use compact lite mode for 4+ miners
            remote_provider: Remote API provider (for remote mode)
        """
        self.config = config
        self.db = db
        self.analyzer = analyzer
        self.remote = remote_provider
        self.console = Console()
        self.running = False
        self.lite_mode = lite_mode

        # Determine if we're in remote mode
        self.is_remote = remote_provider is not None

        # Get enabled devices
        if self.is_remote:
            self.devices = [d for d in remote_provider.get_devices() if d.get("enabled", True)]
        else:
            self.devices = [d for d in config["devices"] if d.get("enabled", True)]

        # Ping tracking for session statistics
        self.ping_history = {}  # {device_id: [ping1, ping2, ...]}
        self.session_start = datetime.now()

        # Build device-to-group mapping for power limits
        self.device_groups = {}
        for device in self.devices:
            self.device_groups[device['name']] = device.get('group', 'default')

    def get_power_limits(self, device_id: str) -> dict:
        """Get power limits for a device based on its group.

        Args:
            device_id: Device identifier

        Returns:
            Dict with max_power, warn_power, psu_capacity
        """
        # Default limits (single-chip Bitaxe)
        defaults = {
            'max_power': 40,
            'warn_power': 35,
            'psu_capacity': 40
        }

        group_name = self.device_groups.get(device_id, 'default')
        group_config = self.config.get('device_groups', {}).get(group_name)

        if group_config:
            return {
                'max_power': group_config.get('max_power', defaults['max_power']),
                'warn_power': group_config.get('warn_power', defaults['warn_power']),
                'psu_capacity': group_config.get('psu_capacity', defaults['psu_capacity'])
            }

        return defaults

    def ping_device(self, ip_address: str) -> Optional[float]:
        """Ping a device and return latency in milliseconds.

        Args:
            ip_address: IP address to ping

        Returns:
            Ping latency in ms or None if unreachable
        """
        try:
            system = platform.system().lower()

            # Build platform-specific ping command
            if system == 'windows':
                command = ['ping', '-n', '1', '-w', '1000', ip_address]
            elif system == 'darwin':  # macOS
                command = ['ping', '-c', '1', '-W', '1000', ip_address]
            else:  # Linux
                command = ['ping', '-c', '1', '-W', '1', ip_address]

            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
                text=True
            )

            if result.returncode == 0:
                # Parse ping output for latency
                output = result.stdout
                if 'time=' in output.lower():
                    # Extract time value (works for Linux/Mac/Windows)
                    for line in output.split('\n'):
                        if 'time=' in line.lower():
                            # Find the time= part
                            time_part = line.lower().split('time=')[1]
                            # Extract just the number (handle "time=52.212 ms" or "time=52.212ms")
                            time_str = time_part.split()[0].replace('ms', '').strip()
                            return float(time_str)
            return None
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError, IndexError) as e:
            return None

    def get_uptime_average_hashrate(self, device_id: str, uptime_seconds: int) -> Optional[float]:
        """Get average hashrate during the current uptime period.

        Args:
            device_id: Device identifier
            uptime_seconds: Current uptime in seconds

        Returns:
            Average hashrate or None if no data
        """
        if self.is_remote:
            result = self.remote.get_uptime_averages(device_id, uptime_seconds)
            return result.get('avg_hashrate')

        from datetime import timedelta

        # Calculate when device was rebooted
        reboot_time = datetime.now() - timedelta(seconds=uptime_seconds)

        # Query average hashrate since reboot
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT AVG(hashrate) as avg_hashrate
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
        """, (device_id, reboot_time))

        row = cursor.fetchone()
        if row and row[0]:
            return round(row[0], 1)
        return None

    def get_uptime_average_efficiency(self, device_id: str, uptime_seconds: int) -> Optional[float]:
        """Get average efficiency during the current uptime period.

        Args:
            device_id: Device identifier
            uptime_seconds: Current uptime in seconds

        Returns:
            Average efficiency (J/TH) or None if no data
        """
        if self.is_remote:
            result = self.remote.get_uptime_averages(device_id, uptime_seconds)
            return result.get('avg_efficiency')

        from datetime import timedelta

        # Calculate when device was rebooted
        reboot_time = datetime.now() - timedelta(seconds=uptime_seconds)

        # Query average efficiency since reboot
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT AVG(efficiency_jth) as avg_efficiency
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
              AND efficiency_jth IS NOT NULL
        """, (device_id, reboot_time))

        row = cursor.fetchone()
        if row and row[0]:
            return round(row[0], 1)
        return None

    def _get_session_metric_stats(self, device_id: str, uptime_seconds: int, metric: str, precision: int = 2) -> Optional[Dict]:
        """Get statistics for a metric during the current uptime session.

        Args:
            device_id: Device identifier
            uptime_seconds: Current uptime in seconds
            metric: Metric column name (e.g., 'power', 'current')
            precision: Decimal places for rounding

        Returns:
            Dictionary with min, max, avg, samples or None if no data
        """
        if self.is_remote:
            return self.remote.get_session_stats(device_id, metric, uptime_seconds)

        from datetime import timedelta

        reboot_time = datetime.now() - timedelta(seconds=uptime_seconds)
        cursor = self.db.conn.cursor()

        cursor.execute(f"""
            SELECT
                MIN({metric}) as min_val,
                MAX({metric}) as max_val,
                AVG({metric}) as avg_val,
                COUNT(*) as sample_count
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
              AND {metric} IS NOT NULL
        """, (device_id, reboot_time))

        row = cursor.fetchone()
        if row and row[0] is not None and row[3] > 0:
            return {
                'min': round(row[0], precision),
                'max': round(row[1], precision),
                'avg': round(row[2], precision),
                'samples': row[3]
            }
        return None

    def get_session_power_stats(self, device_id: str, uptime_seconds: int) -> Optional[Dict]:
        """Get power statistics during the current uptime session."""
        return self._get_session_metric_stats(device_id, uptime_seconds, 'power', precision=2)

    def get_session_current_stats(self, device_id: str, uptime_seconds: int) -> Optional[Dict]:
        """Get current draw statistics during the current uptime session."""
        return self._get_session_metric_stats(device_id, uptime_seconds, 'current', precision=2)

    def get_hashrate_stats_timeframe(self, device_id: str, hours: float) -> Optional[Dict]:
        """Get hashrate statistics for a specific timeframe.

        Args:
            device_id: Device identifier
            hours: Lookback period in hours

        Returns:
            Dictionary with min, max, avg, variance or None if no data
        """
        from datetime import timedelta

        lookback_time = datetime.now() - timedelta(hours=hours)

        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT
                MIN(hashrate) as min_hashrate,
                MAX(hashrate) as max_hashrate,
                AVG(hashrate) as avg_hashrate,
                COUNT(*) as sample_count
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
        """, (device_id, lookback_time))

        row = cursor.fetchone()
        if row and row[0] is not None and row[3] > 0:  # Check samples exist
            min_hr = round(row[0], 1)
            max_hr = round(row[1], 1)
            avg_hr = round(row[2], 1)
            samples = row[3]

            # Calculate variance percentage
            if avg_hr > 0:
                variance_pct = ((max_hr - min_hr) / avg_hr * 100)
            else:
                variance_pct = 0

            return {
                'min': min_hr,
                'max': max_hr,
                'avg': avg_hr,
                'variance_pct': round(variance_pct, 1),
                'samples': samples
            }
        return None

    def get_bucketed_hashrate_trend(self, device_id: str, minutes: int, num_buckets: int) -> list:
        """Get bucketed average hashrate for trend visualization.

        Args:
            device_id: Device identifier
            minutes: Lookback period in minutes
            num_buckets: Number of time buckets to create

        Returns:
            List of average hashrate values per bucket (most recent last)
        """
        if self.is_remote:
            return self.remote.get_hashrate_trend(device_id, minutes, num_buckets)

        from datetime import timedelta

        lookback_time = datetime.now() - timedelta(minutes=minutes)
        bucket_size_minutes = minutes / num_buckets

        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT hashrate, timestamp
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (device_id, lookback_time))

        rows = cursor.fetchall()
        if not rows:
            return []

        # Group samples into buckets and average
        buckets = [[] for _ in range(num_buckets)]
        start_time = datetime.fromisoformat(rows[0][1])

        for hashrate, timestamp_str in rows:
            timestamp = datetime.fromisoformat(timestamp_str)
            elapsed_minutes = (timestamp - start_time).total_seconds() / 60

            # Determine which bucket this sample belongs to
            bucket_idx = int(elapsed_minutes / bucket_size_minutes)
            if bucket_idx >= num_buckets:
                bucket_idx = num_buckets - 1

            buckets[bucket_idx].append(hashrate)

        # Calculate average for each bucket (skip empty buckets)
        averages = []
        for bucket in buckets:
            if bucket:
                averages.append(sum(bucket) / len(bucket))
            elif averages:
                # If bucket is empty but we have previous data, use last value
                averages.append(averages[-1])

        return averages

    def create_hashrate_sparkline(self, hashrates: list, width: int = 40) -> str:
        """Create a sparkline graph from hashrate data.

        Args:
            hashrates: List of hashrate values
            width: Width of the sparkline in characters

        Returns:
            String with block characters representing the trend
        """
        if not hashrates or len(hashrates) < 2:
            return "[dim]No data[/dim]"

        # Sample data to fit width (take evenly spaced samples)
        if len(hashrates) > width:
            step = len(hashrates) / width
            sampled = [hashrates[int(i * step)] for i in range(width)]
        else:
            sampled = hashrates

        # Normalize to 0-8 range for block heights
        min_hr = min(sampled)
        max_hr = max(sampled)
        range_hr = max_hr - min_hr

        if range_hr == 0:
            # All values the same
            return "─" * len(sampled)

        # Block characters from lowest to highest
        blocks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']

        graph = ""
        for value in sampled:
            normalized = (value - min_hr) / range_hr
            block_idx = min(int(normalized * 8), 7)
            graph += blocks[block_idx]

        return graph

    def get_total_uptime(self, device_id: str) -> Optional[Dict[str, float]]:
        """Calculate total cumulative uptime vs current session uptime.

        Detects restarts by finding where uptime decreases significantly between consecutive polls.
        Ignores small decreases (< 5 minutes) which are likely clock adjustments, not real reboots.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with session_hours and total_hours or None if no data
        """
        if self.is_remote:
            return self.remote.get_total_uptime(device_id)

        cursor = self.db.conn.cursor()

        # Get all uptime values ordered by time
        cursor.execute("""
            SELECT uptime, timestamp
            FROM performance_metrics
            WHERE device_id = ?
            ORDER BY timestamp ASC
        """, (device_id,))

        rows = cursor.fetchall()
        if not rows:
            return None

        # Current session uptime (latest value)
        current_uptime = rows[-1][0]

        # Calculate total uptime by detecting real restarts
        # A real restart resets uptime to near-zero (< 1 hour)
        # Uptime decreases to larger values are clock adjustments from NTP/DST, not reboots
        MAX_RESTART_UPTIME = 3600  # 1 hour in seconds - real restarts reset to < this

        total_uptime = 0
        prev_uptime = 0
        session_start_idx = 0

        for i, (uptime, timestamp) in enumerate(rows):
            # Detect restart: uptime decreased AND new uptime is small (< 1 hour)
            # This filters out clock adjustments while catching real reboots
            if uptime < prev_uptime and uptime < MAX_RESTART_UPTIME:
                # Add the maximum uptime from the previous session
                session_uptimes = [rows[j][0] for j in range(session_start_idx, i)]
                if session_uptimes:
                    total_uptime += max(session_uptimes)
                session_start_idx = i

            prev_uptime = uptime

        # Add current session uptime
        total_uptime += current_uptime

        return {
            'session_hours': current_uptime / 3600,
            'total_hours': total_uptime / 3600
        }

    def get_highest_difficulty(self, device_id: str) -> Optional[Dict[str, float]]:
        """Get the highest difficulty ever achieved by this device.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with best_diff and best_session_diff or None if no data
        """
        if self.is_remote:
            return self.remote.get_highest_difficulty(device_id)

        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT
                MAX(best_diff) as max_best_diff,
                MAX(best_session_diff) as max_session_diff
            FROM performance_metrics
            WHERE device_id = ?
              AND best_diff IS NOT NULL
        """, (device_id,))

        row = cursor.fetchone()
        if row and row[0] is not None:
            return {
                'all_time': row[0],
                'session': row[1] if row[1] else row[0]
            }
        return None

    def get_multi_timeframe_variance(self, device_id: str) -> Dict[str, Optional[Dict]]:
        """Get variance percentages for multiple timeframes using bucketed averages.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary mapping timeframe labels to dictionaries containing variance, mean, median, and sample count
        """
        if self.is_remote:
            return self.remote.get_variance(device_id)

        # Use analyzer's cached method for local mode
        return self.analyzer.get_multi_timeframe_variance(device_id)

    def _get_device_ip(self, device_id: str) -> str:
        """Get device IP from config.

        Args:
            device_id: Device identifier

        Returns:
            Device IP address or "Unknown"
        """
        device_config = next((d for d in self.devices if d["name"] == device_id), None)
        return device_config["ip"] if device_config else "Unknown"

    def _track_ping_history(self, device_id: str, ping_ms: Optional[float]) -> None:
        """Track ping in history (keep last 100).

        Args:
            device_id: Device identifier
            ping_ms: Ping latency in milliseconds or None
        """
        if device_id not in self.ping_history:
            self.ping_history[device_id] = []

        if ping_ms is not None:
            self.ping_history[device_id].append(ping_ms)
            if len(self.ping_history[device_id]) > 100:
                self.ping_history[device_id].pop(0)

    def _get_ping_color(self, ping_ms: float) -> str:
        """Get color for ping latency.

        Args:
            ping_ms: Ping latency in milliseconds

        Returns:
            Color string for rich formatting
        """
        if ping_ms < 50:
            return "green"
        elif ping_ms < 100:
            return "yellow"
        return "red"

    def _get_temp_color(self, temp: float, warn_threshold: float, critical_threshold: float) -> str:
        """Get color for temperature value.

        Args:
            temp: Temperature in Celsius
            warn_threshold: Warning threshold
            critical_threshold: Critical threshold

        Returns:
            Color string for rich formatting
        """
        if temp >= critical_threshold:
            return "red"
        elif temp >= warn_threshold:
            return "yellow"
        return "white"

    def _get_voltage_color(self, voltage: float, lite_mode: bool = False) -> str:
        """Get color for voltage value.

        Args:
            voltage: Voltage in volts
            lite_mode: Use white for good voltage (lite mode)

        Returns:
            Color string for rich formatting
        """
        if voltage < 4.8:
            return "red"
        elif voltage < 4.9:
            return "yellow"
        return "white" if lite_mode else "green"

    def _calculate_median(self, values: list) -> float:
        """Calculate median of a list of numbers.

        Args:
            values: List of numeric values

        Returns:
            Median value
        """
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 0:
            return (sorted_vals[n//2 - 1] + sorted_vals[n//2]) / 2
        return sorted_vals[n//2]

    def _format_uptime(self, hours: float) -> str:
        """Format uptime hours as days/hours string.

        Args:
            hours: Uptime in hours

        Returns:
            Formatted string (e.g., "2d 5.3h" or "15.2h")
        """
        if hours >= 24:
            days = int(hours // 24)
            remaining_hours = hours % 24
            return f"{days}d {remaining_hours:.1f}h"
        return f"{hours:.1f}h"

    def _format_current_vs_avg(self, label: str, current: float, avg: float,
                                unit: str, lower_is_better: bool = False,
                                precision: int = 1) -> tuple:
        """Format current/avg display with colored diff.

        Args:
            label: Display label
            current: Current value
            avg: Average value
            unit: Unit string (e.g., 'GH/s', 'W', 'J/TH')
            lower_is_better: True if lower values are better (efficiency)
            precision: Decimal precision

        Returns:
            Tuple of (label, formatted_string)
        """
        diff = current - avg
        sign = "+" if diff >= 0 else ""

        # Determine color based on whether lower is better
        if lower_is_better:
            color = "green" if diff <= 0 else "yellow"
        else:
            color = "green" if diff >= 0 else "yellow"

        return (
            label,
            f"[cyan]{current:.{precision}f}[/cyan] / {avg:.{precision}f} {unit} "
            f"[{color}]({sign}{diff:.{precision}f})[/{color}]"
        )

    def _format_sparkline_with_range(self, label: str, hashrates: list,
                                      width: int, color: str) -> tuple:
        """Format sparkline with min-max range display.

        Args:
            label: Display label
            hashrates: List of hashrate values
            width: Sparkline width
            color: Color for sparkline

        Returns:
            Tuple of (label, formatted_string) or None if insufficient data
        """
        if len(hashrates) <= 1:
            return None

        sparkline = self.create_hashrate_sparkline(hashrates, width=width)
        min_val = min(hashrates)
        max_val = max(hashrates)
        return (
            label,
            f"[{color}]{sparkline}[/{color}] [dim]({min_val:.0f}-{max_val:.0f})[/dim]"
        )

    def _create_no_data_panel(self, device_id: str, device_ip: str,
                               message: str = "No data") -> Panel:
        """Create a panel for when no data is available.

        Args:
            device_id: Device identifier
            device_ip: Device IP address
            message: Message to display

        Returns:
            Panel with error message
        """
        return Panel(
            Text(message, style="dim"),
            title=f"[cyan]{device_id}[/cyan] [dim]({device_ip})[/dim]",
            border_style="red"
        )

    def _get_border_color_from_metrics(self, asic_temp: float, vreg_temp: float, voltage: float) -> str:
        """Get panel border color based on health metrics.

        Args:
            asic_temp: ASIC temperature in Celsius
            vreg_temp: VR temperature in Celsius
            voltage: Input voltage

        Returns:
            Border color string ('red', 'yellow', or 'green')
        """
        if asic_temp >= 70 or vreg_temp >= 80 or voltage < 4.8:
            return "red"
        elif asic_temp >= 65 or vreg_temp >= 70 or voltage < 4.9:
            return "yellow"
        return "green"

    def format_difficulty(self, difficulty: float) -> str:
        """Format difficulty value with appropriate suffix.

        Args:
            difficulty: Raw difficulty value

        Returns:
            Formatted string (e.g., "27.2 M", "1.45 G")
        """
        if difficulty >= 1_000_000_000_000:
            return f"{difficulty / 1_000_000_000_000:.2f} T"
        elif difficulty >= 1_000_000_000:
            return f"{difficulty / 1_000_000_000:.2f} G"
        elif difficulty >= 1_000_000:
            return f"{difficulty / 1_000_000:.2f} M"
        elif difficulty >= 1_000:
            return f"{difficulty / 1_000:.2f} K"
        else:
            return f"{difficulty:.0f}"

    def create_device_panel(self, device_id: str) -> Panel:
        """Create a panel showing device status.

        Args:
            device_id: Device identifier

        Returns:
            Rich Panel with device information
        """
        # Get device IP from config
        device_ip = self._get_device_ip(device_id)

        # Get device info for pool data
        if self.is_remote:
            device_info = self.remote.get_device_info(device_id)
            latest = self.remote.get_latest_metric(device_id)
        else:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
            device_info = cursor.fetchone()
            latest = self.db.get_latest_metric(device_id)

        if not latest:
            return self._create_no_data_panel(device_id, device_ip, "No data available")

        # Get uptime and calculate averages
        uptime_seconds = latest['uptime']
        avg_hashrate = self.get_uptime_average_hashrate(device_id, uptime_seconds)
        avg_efficiency = self.get_uptime_average_efficiency(device_id, uptime_seconds)

        # Get multi-timeframe variance
        variance_data = self.get_multi_timeframe_variance(device_id)

        # Get bucketed average hashrate trends
        recent_hashrates_1h = self.get_bucketed_hashrate_trend(device_id, minutes=60, num_buckets=30)   # 2-min buckets
        recent_hashrates_24h = self.get_bucketed_hashrate_trend(device_id, minutes=1440, num_buckets=24)  # 1-hour buckets

        # Create status table
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()

        # Configuration (prominent at top)
        freq = latest['frequency']
        core_v = latest['core_voltage']
        table.add_row("Config:", f"[bold cyan]{freq} MHz @ {core_v} mV[/bold cyan]")

        # Ping latency
        ping_ms = self.ping_device(device_ip)
        self._track_ping_history(device_id, ping_ms)

        if ping_ms is not None:
            # Calculate statistics
            ping_list = self.ping_history[device_id]
            avg_ping = sum(ping_list) / len(ping_list)
            min_ping = min(ping_list)
            max_ping = max(ping_list)
            median_ping = self._calculate_median(ping_list)

            # Color code based on current latency
            ping_color = self._get_ping_color(ping_ms)

            # Show current with stats
            table.add_row(
                "Ping:",
                f"[{ping_color}]{ping_ms:.1f} ms[/{ping_color}] [dim](avg: {avg_ping:.1f}, median: {median_ping:.1f})[/dim]"
            )
            table.add_row(
                "Ping Range:",
                f"[dim]{min_ping:.1f}-{max_ping:.1f} ms ({len(ping_list)} samples)[/dim]"
            )
        else:
            table.add_row("Ping:", "[red]Unreachable[/red]")

        # Pool information
        if device_info:
            # Handle both dict (remote) and Row (local) objects
            if isinstance(device_info, dict):
                device_dict = device_info
            else:
                device_dict = dict(device_info)
            stratum_url = device_dict.get('stratum_url')
            stratum_port = device_dict.get('stratum_port')

            if stratum_url and stratum_port:
                # Truncate pool URL if too long
                pool_display = stratum_url
                if len(pool_display) > 35:
                    pool_display = pool_display[:32] + "..."
                table.add_row("Pool:", f"[cyan]{pool_display}:{stratum_port}[/cyan]")

        table.add_row("", "")  # Spacer

        # Hashrate (current) and average
        hashrate = latest['hashrate']
        hashrate_color = "green" if hashrate > 500 else "yellow" if hashrate > 400 else "red"

        if avg_hashrate:
            table.add_row(
                "Hashrate:",
                f"[{hashrate_color}]{hashrate:.1f} GH/s[/{hashrate_color}] [dim](Avg: {avg_hashrate:.1f})[/dim]"
            )
        else:
            table.add_row(
                "Hashrate:",
                f"[{hashrate_color}]{hashrate:.1f} GH/s[/{hashrate_color}]"
            )

        # Hashrate trend graphs with labels
        if len(recent_hashrates_1h) > 1:
            sparkline_1h = self.create_hashrate_sparkline(recent_hashrates_1h, width=35)
            min_1h = min(recent_hashrates_1h)
            max_1h = max(recent_hashrates_1h)
            table.add_row(
                "Trend (1h):",
                f"[cyan]{sparkline_1h}[/cyan] [dim]({min_1h:.0f}-{max_1h:.0f} GH/s)[/dim]"
            )

        if len(recent_hashrates_24h) > 1:
            sparkline_24h = self.create_hashrate_sparkline(recent_hashrates_24h, width=35)
            min_24h = min(recent_hashrates_24h)
            max_24h = max(recent_hashrates_24h)
            table.add_row(
                "Trend (24h):",
                f"[blue]{sparkline_24h}[/blue] [dim]({min_24h:.0f}-{max_24h:.0f} GH/s)[/dim]"
            )

        # Efficiency
        efficiency = latest['efficiency_jth']
        eff_color = "green" if efficiency < 28 else "yellow" if efficiency < 32 else "red"
        eff_icon = "🟢" if efficiency < 28 else "🟡" if efficiency < 32 else "🔴"

        if avg_efficiency:
            table.add_row(
                "Efficiency:",
                f"{eff_icon} [{eff_color}]{efficiency:.1f} J/TH[/{eff_color}] [dim](Avg: {avg_efficiency:.1f})[/dim]"
            )
        else:
            table.add_row(
                "Efficiency:",
                f"{eff_icon} [{eff_color}]{efficiency:.1f} J/TH[/{eff_color}]"
            )

        # Uptime - show both session and total
        uptime_stats = self.get_total_uptime(device_id)
        if uptime_stats:
            session_h = uptime_stats['session_hours']
            total_h = uptime_stats['total_hours']

            session_str = self._format_uptime(session_h)
            total_str = self._format_uptime(total_h)

            # Show restart count if total > session
            if total_h > session_h * 1.1:  # 10% threshold to account for rounding
                table.add_row(
                    "Uptime:",
                    f"{session_str} [dim](session)[/dim] | {total_str} [dim](total)[/dim]"
                )
            else:
                table.add_row("Uptime:", f"{session_str}")
        else:
            uptime_hours = latest['uptime'] / 3600
            table.add_row("Uptime:", f"{uptime_hours:.1f}h")

        table.add_row("", "")  # Spacer before thermal section

        # ASIC Temperature with bar
        asic_temp = latest['asic_temp']
        temp_pct = int(asic_temp / 70 * 100)  # 70°C = 100%
        temp_color = self._get_temp_color(asic_temp, warn_threshold=65, critical_threshold=70)
        table.add_row(
            "ASIC Temp:",
            f"[{temp_color}]{asic_temp:.1f}°C[/{temp_color}] {'█' * (temp_pct // 10)}"
        )

        # VR Temperature
        vreg_temp = latest['vreg_temp']
        vr_color = self._get_temp_color(vreg_temp, warn_threshold=70, critical_threshold=80)
        table.add_row(
            "VR Temp:",
            f"[{vr_color}]{vreg_temp:.1f}°C[/{vr_color}]"
        )

        # Power with color coding (using group-specific limits)
        power = latest['power']
        power_limits = self.get_power_limits(device_id)
        max_pwr = power_limits['max_power']
        warn_pwr = power_limits['warn_power']
        psu_cap = power_limits['psu_capacity']

        power_color = "red" if power >= max_pwr else "yellow" if power >= warn_pwr else "white"
        power_pct = int(power / psu_cap * 100)
        table.add_row(
            "Power:",
            f"[{power_color}]{power:.1f}W[/{power_color}] {'█' * (power_pct // 10)} ({power_pct}% of {psu_cap}W)"
        )


        # Input Voltage
        voltage = latest['voltage']
        # Convert from millivolts to volts if needed (legacy data compatibility)
        if voltage > 100:
            voltage = voltage / 1000.0
        voltage_color = self._get_voltage_color(voltage)
        table.add_row(
            "Input V:",
            f"[{voltage_color}]{voltage:.2f}V[/{voltage_color}]"
        )

        # Fan
        fan_rpm = latest['fan_rpm']
        fan_speed = latest['fan_speed']
        table.add_row("Fan:", f"{fan_rpm} RPM ({fan_speed}%)")

        # Mining Performance Section
        table.add_row("", "")  # Spacer
        table.add_row("[bold cyan]Mining Performance[/bold cyan]", "")

        # Shares statistics
        shares_accepted = latest['shares_accepted']
        shares_rejected = latest['shares_rejected']
        total_shares = shares_accepted + shares_rejected

        if total_shares > 0:
            reject_rate = (shares_rejected / total_shares) * 100

            # Color code rejection rate
            if reject_rate < 1:
                reject_color = "green"
            elif reject_rate < 3:
                reject_color = "yellow"
            else:
                reject_color = "red"

            table.add_row(
                "Shares:",
                f"{shares_accepted:,} accepted / [{reject_color}]{shares_rejected} rejected[/{reject_color}]"
            )
            table.add_row(
                "Reject Rate:",
                f"[{reject_color}]{reject_rate:.2f}%[/{reject_color}]"
            )

            # Rejection reasons breakdown (right below reject rate)
            rejection_reasons_json = latest.get('rejection_reasons')
            if rejection_reasons_json:
                import json
                try:
                    rejection_reasons = json.loads(rejection_reasons_json)
                    if rejection_reasons and len(rejection_reasons) > 0:
                        for reason in rejection_reasons:
                            message = reason.get('message', 'Unknown')
                            count = reason.get('count', 0)
                            table.add_row(f"  {message}:", f"[yellow]{count}[/yellow]")
                except json.JSONDecodeError:
                    pass
        else:
            table.add_row("Shares:", "[dim]No shares submitted yet[/dim]")

        # Stratum difficulty
        stratum_diff = latest.get('stratum_diff')
        if stratum_diff:
            table.add_row("Pool Diff:", f"{self.format_difficulty(stratum_diff)}")

        # Best difficulty
        best_diff = latest.get('best_diff')
        if best_diff:
            table.add_row("Best Diff:", f"[bold green]{self.format_difficulty(best_diff)}[/bold green]")

        # Stability Analysis Section
        table.add_row("", "")  # Spacer
        table.add_row("[bold cyan]Hash Variance[/bold cyan]", "")

        def format_variance(variance_pct: float) -> tuple:
            """Return color and status for variance percentage (BM1370 calibrated)."""
            if variance_pct < 30:
                return "green", "Excellent"
            elif variance_pct < 50:
                return "green", "Stable"
            elif variance_pct < 70:
                return "yellow", "Acceptable"
            elif variance_pct < 90:
                return "yellow", "Variable"
            else:
                return "red", "Unstable"

        # Display variance for each timeframe
        # Define bucket sizes for clarity
        bucket_info = {
            '1h': '2-min',
            '4h': '5-min',
            '8h': '10-min',
            '24h': '1-hour',
            '3d': '2-hour'
        }

        for timeframe in ['1h', '4h', '8h', '24h', '3d']:
            data = variance_data.get(timeframe)
            if data:
                variance = data['variance']
                mean = data['mean']
                median = data['median']
                samples = data['samples']
                color, status = format_variance(variance)

                # Create visual bar (scaled 0-100% = 0-10 blocks for BM1370)
                bar_blocks = min(int(variance / 10), 10)
                bar = '█' * bar_blocks

                # Calculate mean-median difference to show skewness
                mean_median_diff = mean - median
                if abs(mean_median_diff) < 5:
                    skew_indicator = ""  # Symmetric distribution
                elif mean_median_diff > 5:
                    skew_indicator = " [dim](skewed high)[/dim]"
                else:
                    skew_indicator = " [dim](skewed low)[/dim]"

                table.add_row(
                    f"  {timeframe} [dim]({bucket_info[timeframe]})[/dim]:",
                    f"[{color}]{variance:>4.1f}% {bar:<10}[/{color}] [{color}]{status}[/{color}]{skew_indicator}"
                )
                table.add_row(
                    "",
                    f"[dim]mean: {mean:.0f} GH/s | median: {median:.0f} GH/s[/dim]"
                )
            else:
                table.add_row(f"  {timeframe}:", "[dim]No data[/dim]")

        # Check for warnings
        warnings = []
        if asic_temp >= 70:
            warnings.append("[red]🔥 OVERHEATING[/red]")
        elif asic_temp >= 65:
            warnings.append("[yellow]⚠️  Elevated Temp[/yellow]")
        if vreg_temp >= 80:
            warnings.append("[red]🔥 VR OVERHEATING[/red]")
        elif vreg_temp >= 70:
            warnings.append("[yellow]⚠️  High VR Temp[/yellow]")
        if voltage < 4.8:
            warnings.append("[red]⚠️  PSU VOLTAGE SAG[/red]")
        elif voltage < 4.9:
            warnings.append("[yellow]⚠️  Low Input Voltage[/yellow]")
        if power >= max_pwr:
            warnings.append("[red]⚠️  HIGH POWER DRAW[/red]")
        elif power >= warn_pwr:
            warnings.append("[yellow]⚠️  Approaching PSU Limit[/yellow]")

        if warnings:
            table.add_row("")
            for warning in warnings:
                table.add_row("", warning)

        # Panel border color based on health
        if warnings and any("red" in w for w in warnings):
            border_style = "red"
        elif warnings:
            border_style = "yellow"
        else:
            border_style = "green"

        # Last update time
        last_update = datetime.fromisoformat(latest['timestamp'])
        age_seconds = (datetime.now() - last_update).total_seconds()
        if age_seconds > 30:
            update_str = f"[red]Last update: {age_seconds:.0f}s ago (STALE)[/red]"
        else:
            update_str = f"[dim]Updated {age_seconds:.0f}s ago[/dim]"

        return Panel(
            table,
            title=f"[bold cyan]{device_id}[/bold cyan] [dim]({device_ip})[/dim]",
            subtitle=update_str,
            border_style=border_style
        )

    def create_device_panel_lite(self, device_id: str) -> Panel:
        """Create a compact panel for lite mode (4+ miners).

        Args:
            device_id: Device identifier

        Returns:
            Compact Rich Panel with essential device information
        """
        # Get device IP from config
        device_ip = self._get_device_ip(device_id)

        if self.is_remote:
            latest = self.remote.get_latest_metric(device_id)
        else:
            latest = self.db.get_latest_metric(device_id)

        if not latest:
            return self._create_no_data_panel(device_id, device_ip, "No data")

        # Get uptime and statistics
        uptime_seconds = latest['uptime']
        avg_hashrate = self.get_uptime_average_hashrate(device_id, uptime_seconds)
        power_stats = self.get_session_power_stats(device_id, uptime_seconds)
        current_stats = self.get_session_current_stats(device_id, uptime_seconds)

        # Get trend data
        recent_hashrates_1h = self.get_bucketed_hashrate_trend(device_id, minutes=60, num_buckets=20)
        recent_hashrates_24h = self.get_bucketed_hashrate_trend(device_id, minutes=1440, num_buckets=20)

        # Create compact table
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold", width=12)
        table.add_column()

        # Configuration
        freq = latest['frequency']
        core_v = latest['core_voltage']
        table.add_row("Config:", f"[bold cyan]{freq} MHz @ {core_v} mV[/bold cyan]")

        # Ping latency
        ping_ms = self.ping_device(device_ip)
        self._track_ping_history(device_id, ping_ms)

        if ping_ms is not None:
            # Calculate average
            ping_list = self.ping_history[device_id]
            avg_ping = sum(ping_list) / len(ping_list)

            # Color code based on average latency
            ping_color = self._get_ping_color(avg_ping)

            table.add_row("Avg Ping:", f"[{ping_color}]{avg_ping:.1f} ms[/{ping_color}]")
        else:
            table.add_row("Avg Ping:", "[red]Unreachable[/red]")

        table.add_row("", "")  # Spacer

        # Hashrate line
        hashrate = latest['hashrate']
        if avg_hashrate:
            table.add_row(*self._format_current_vs_avg("Hash/Avg:", hashrate, avg_hashrate, "GH/s"))
        else:
            table.add_row("Hash/Avg:", f"[cyan]{hashrate:.1f}[/cyan] GH/s")

        # Trend graphs
        sparkline_1h = self._format_sparkline_with_range("1h:", recent_hashrates_1h, width=30, color="cyan")
        if sparkline_1h:
            table.add_row(*sparkline_1h)

        sparkline_24h = self._format_sparkline_with_range("24h:", recent_hashrates_24h, width=30, color="blue")
        if sparkline_24h:
            table.add_row(*sparkline_24h)

        # Efficiency: current / avg
        efficiency = latest['efficiency_jth']
        if power_stats and avg_hashrate:
            # Calculate average efficiency from avg hashrate and avg power
            avg_efficiency = power_stats['avg'] / (avg_hashrate / 1000.0)
            table.add_row(*self._format_current_vs_avg("Eff/Avg:", efficiency, avg_efficiency, "J/TH", lower_is_better=True))
        else:
            table.add_row("Eff/Avg:", f"[cyan]{efficiency:.1f}[/cyan] J/TH")

        table.add_row("", "")  # Spacer

        # TEMPS/WATTS section header
        table.add_row("[bold]TEMPS/POWER:", "")

        # ASIC temp
        asic_temp = latest['asic_temp']
        temp_color = self._get_temp_color(asic_temp, warn_threshold=65, critical_threshold=70)
        table.add_row("ASIC:", f"[{temp_color}]{asic_temp:.1f}°C[/{temp_color}]")

        # VRM temp
        vreg_temp = latest['vreg_temp']
        vr_color = self._get_temp_color(vreg_temp, warn_threshold=70, critical_threshold=80)
        table.add_row("VRM:", f"[{vr_color}]{vreg_temp:.1f}°C[/{vr_color}]")

        # Voltage
        voltage = latest['voltage']
        # Convert from millivolts to volts if needed (legacy data compatibility)
        if voltage > 100:
            voltage = voltage / 1000.0
        voltage_color = self._get_voltage_color(voltage, lite_mode=True)
        table.add_row("Voltage:", f"[{voltage_color}]{voltage:.2f}V[/{voltage_color}]")

        # Power: current / avg
        power = latest['power']
        if power_stats:
            table.add_row(*self._format_current_vs_avg("Power:", power, power_stats['avg'], "W"))
        else:
            table.add_row("Power/Avg:", f"[cyan]{power:.1f}[/cyan]W")

        # Border color based on health
        border_style = self._get_border_color_from_metrics(asic_temp, vreg_temp, voltage)

        return Panel(
            table,
            title=f"[cyan]{device_id}[/cyan] [dim]({device_ip})[/dim]",
            border_style=border_style
        )

    def create_summary_panel(self) -> Panel:
        """Create summary panel with overall stats."""
        if self.is_remote:
            summary = self.remote.get_summary()
        else:
            summary = self.analyzer.get_all_devices_summary()

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()

        total_samples = sum(d['total_samples'] for d in summary.values())
        total_hashrate = sum(
            d['latest']['hashrate'] if d['latest'] else 0
            for d in summary.values()
        )

        table.add_row("Total Samples:", f"{total_samples:,}")
        table.add_row("Combined Hashrate:", f"{total_hashrate:.1f} GH/s")
        table.add_row("Active Devices:", f"{len(self.devices)}")
        table.add_row("Poll Interval:", f"{self.config['logging']['poll_interval']}s")

        return Panel(
            table,
            title="[bold]System Summary[/bold]",
            border_style="blue"
        )

    def create_layout(self) -> Layout:
        """Create dashboard layout.

        Returns:
            Rich Layout object
        """
        layout = Layout()

        # Split into header, body, footer
        layout.split(
            Layout(name="header", size=1),
            Layout(name="body"),
            Layout(name="footer", size=5)
        )

        # Header
        layout["header"].update(
            Text(
                "⛏️  Bitaxe Multi-Miner Dashboard",
                style="bold white on blue",
                justify="center"
            )
        )

        # Choose panel creation method based on mode
        panel_method = self.create_device_panel_lite if self.lite_mode else self.create_device_panel

        # Body - split by number of devices
        if len(self.devices) == 1:
            layout["body"].update(panel_method(self.devices[0]["name"]))
        elif len(self.devices) == 2:
            layout["body"].split_row(
                Layout(name="device1"),
                Layout(name="device2")
            )
            layout["body"]["device1"].update(
                panel_method(self.devices[0]["name"])
            )
            layout["body"]["device2"].update(
                panel_method(self.devices[1]["name"])
            )
        else:
            # For 3+ devices, use grid layout
            # Split into rows of 2
            rows = (len(self.devices) + 1) // 2
            layout["body"].split_column(*[Layout(name=f"row{i}") for i in range(rows)])

            for i, device in enumerate(self.devices):
                row_idx = i // 2
                if i % 2 == 0:
                    layout["body"][f"row{row_idx}"].split_row(
                        Layout(name=f"device{i}"),
                        Layout(name=f"device{i+1}")
                    )
                layout["body"][f"row{row_idx}"][f"device{i}"].update(
                    panel_method(device["name"])
                )

        # Footer - summary
        layout["footer"].update(self.create_summary_panel())

        return layout

    def run(self, refresh_interval: int = 5):
        """Run the dashboard.

        Args:
            refresh_interval: Seconds between updates
        """
        self.running = True

        try:
            with Live(
                self.create_layout(),
                console=self.console,
                screen=True,
                refresh_per_second=1
            ) as live:
                self.console.print(
                    "\n[dim]Press Ctrl+C to exit[/dim]\n",
                    justify="center"
                )

                while self.running:
                    time.sleep(refresh_interval)
                    live.update(self.create_layout())

        except KeyboardInterrupt:
            pass


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_file) as f:
        return yaml.safe_load(f)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Bitaxe Multi-Miner Dashboard")
    parser.add_argument(
        "--lite",
        action="store_true",
        help="Use compact lite mode for monitoring 4+ miners"
    )
    parser.add_argument(
        "--remote",
        type=str,
        help="Remote API URL (overrides config.yaml setting)"
    )
    args = parser.parse_args()

    # Load config
    config = load_config()

    # Check for remote API URL (command line takes precedence)
    remote_url = args.remote
    if not remote_url:
        remote_url = config.get("dashboard", {}).get("remote_api_url", "")

    if remote_url:
        # Remote mode - fetch data from API server
        print(f"Connecting to remote API: {remote_url}")
        remote = RemoteProvider(remote_url)

        # Health check
        if not remote.health_check():
            print(f"Error: Cannot connect to API server at {remote_url}")
            print("Make sure the API server is running on the remote host.")
            sys.exit(1)

        # Create and run dashboard in remote mode
        dashboard = BitaxeDashboard(config, lite_mode=args.lite, remote_provider=remote)

        try:
            dashboard.run(refresh_interval=5)
        except KeyboardInterrupt:
            pass
    else:
        # Local mode - use local database
        db_path = config["logging"]["database_path"]
        db = Database(db_path)
        analyzer = Analyzer(db)

        # Create and run dashboard
        dashboard = BitaxeDashboard(config, db, analyzer, lite_mode=args.lite)

        try:
            dashboard.run(refresh_interval=5)
        finally:
            db.close()


if __name__ == "__main__":
    main()
