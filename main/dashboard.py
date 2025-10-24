#!/usr/bin/env python3
"""Real-time terminal dashboard for Bitaxe miners."""

import sys
import time
import yaml
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


class BitaxeDashboard:
    """Real-time terminal dashboard for Bitaxe monitoring."""

    def __init__(self, config: dict, db: Database, analyzer: Analyzer):
        """Initialize dashboard.

        Args:
            config: Configuration dictionary
            db: Database instance
            analyzer: Analyzer instance
        """
        self.config = config
        self.db = db
        self.analyzer = analyzer
        self.console = Console()
        self.running = False

        # Get enabled devices
        self.devices = [d for d in config["devices"] if d.get("enabled", True)]

    def get_uptime_average_hashrate(self, device_id: str, uptime_seconds: int) -> Optional[float]:
        """Get average hashrate during the current uptime period.

        Args:
            device_id: Device identifier
            uptime_seconds: Current uptime in seconds

        Returns:
            Average hashrate or None if no data
        """
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

        Detects restarts by finding where uptime decreases between consecutive polls.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with session_hours and total_hours or None if no data
        """
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

        # Calculate total uptime by detecting restarts
        total_uptime = 0
        prev_uptime = 0
        session_start_idx = 0

        for i, (uptime, timestamp) in enumerate(rows):
            # Detect restart: uptime decreased
            if uptime < prev_uptime:
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

    def get_multi_timeframe_variance(self, device_id: str) -> Dict[str, Optional[float]]:
        """Get variance percentages for multiple timeframes using bucketed averages.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary mapping timeframe labels to variance percentages
        """
        timeframes = {
            '1h': (60, 30),    # 60 minutes, 30 buckets (2-min each)
            '4h': (240, 48),   # 4 hours, 48 buckets (5-min each)
            '8h': (480, 48),   # 8 hours, 48 buckets (10-min each)
            '24h': (1440, 24), # 24 hours, 24 buckets (1-hour each)
            '3d': (4320, 36)   # 3 days, 36 buckets (2-hour each)
        }

        results = {}
        for label, (minutes, buckets) in timeframes.items():
            # Get bucketed averages (same as trend graphs)
            hashrates = self.get_bucketed_hashrate_trend(device_id, minutes, buckets)

            if hashrates and len(hashrates) > 1:
                min_hr = min(hashrates)
                max_hr = max(hashrates)
                avg_hr = sum(hashrates) / len(hashrates)

                # Calculate variance from bucketed averages
                if avg_hr > 0:
                    variance_pct = ((max_hr - min_hr) / avg_hr * 100)
                else:
                    variance_pct = 0

                results[label] = {
                    'variance': round(variance_pct, 1),
                    'samples': len(hashrates)
                }
            else:
                results[label] = None

        return results

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
        device_config = next((d for d in self.devices if d["name"] == device_id), None)
        device_ip = device_config["ip"] if device_config else "Unknown"

        latest = self.db.get_latest_metric(device_id)

        if not latest:
            return Panel(
                Text("No data available", style="dim"),
                title=f"[bold cyan]{device_id}[/bold cyan] [dim]({device_ip})[/dim]",
                border_style="red"
            )

        # Get uptime and calculate average
        uptime_seconds = latest['uptime']
        avg_hashrate = self.get_uptime_average_hashrate(device_id, uptime_seconds)

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
        table.add_row("Frequency:", f"[bold cyan]{freq} MHz[/bold cyan]")
        table.add_row("Core Voltage:", f"[bold cyan]{core_v} mV[/bold cyan]")
        table.add_row("", "")  # Spacer

        # Hashrate with bar (current)
        hashrate = latest['hashrate']
        expected = 600  # Approximate max for BM1366
        hashrate_pct = min(int(hashrate / expected * 100), 100)
        hashrate_color = "green" if hashrate > 500 else "yellow" if hashrate > 400 else "red"
        table.add_row(
            "Hashrate:",
            f"[{hashrate_color}]{hashrate:.1f} GH/s[/{hashrate_color}] {'█' * (hashrate_pct // 10)}"
        )

        # Average hashrate during uptime
        if avg_hashrate:
            avg_diff = hashrate - avg_hashrate
            avg_sign = "+" if avg_diff >= 0 else ""
            avg_color = "green" if avg_diff >= 0 else "red"
            table.add_row(
                "Avg (uptime):",
                f"{avg_hashrate:.1f} GH/s [{avg_color}]({avg_sign}{avg_diff:.1f})[/{avg_color}]"
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

        table.add_row("", "")  # Spacer before thermal section

        # ASIC Temperature with bar
        asic_temp = latest['asic_temp']
        temp_pct = int(asic_temp / 70 * 100)  # 70°C = 100%
        temp_color = "red" if asic_temp >= 65 else "yellow" if asic_temp >= 60 else "green"
        table.add_row(
            "ASIC Temp:",
            f"[{temp_color}]{asic_temp:.1f}°C[/{temp_color}] {'█' * (temp_pct // 10)}"
        )

        # VR Temperature
        vreg_temp = latest['vreg_temp']
        vr_color = "red" if vreg_temp >= 80 else "yellow" if vreg_temp >= 70 else "white"
        table.add_row(
            "VR Temp:",
            f"[{vr_color}]{vreg_temp:.1f}°C[/{vr_color}]"
        )

        # Power with color coding
        power = latest['power']
        power_color = "red" if power >= 25 else "yellow" if power >= 24 else "white"
        power_pct = int(power / 30 * 100)  # 30W = 100%
        table.add_row(
            "Power:",
            f"[{power_color}]{power:.1f}W[/{power_color}] {'█' * (power_pct // 10)} ({power_pct}% of 30W)"
        )

        # Input Voltage
        voltage = latest['voltage']
        voltage_color = "red" if voltage < 4.8 else "yellow" if voltage < 4.9 else "green"
        table.add_row(
            "Input V:",
            f"[{voltage_color}]{voltage:.2f}V[/{voltage_color}]"
        )

        # Efficiency
        efficiency = latest['efficiency_jth']
        eff_color = "green" if efficiency < 28 else "yellow" if efficiency < 32 else "red"
        eff_icon = "🟢" if efficiency < 28 else "🟡" if efficiency < 32 else "🔴"
        table.add_row(
            "Efficiency:",
            f"{eff_icon} [{eff_color}]{efficiency:.1f} J/TH[/{eff_color}]"
        )

        # Fan
        fan_rpm = latest['fan_rpm']
        fan_speed = latest['fan_speed']
        table.add_row("Fan:", f"{fan_rpm} RPM ({fan_speed}%)")

        # Uptime - show both session and total
        uptime_stats = self.get_total_uptime(device_id)
        if uptime_stats:
            session_h = uptime_stats['session_hours']
            total_h = uptime_stats['total_hours']

            # Format uptime nicely (show days if > 24h)
            def format_uptime(hours):
                if hours >= 24:
                    days = int(hours // 24)
                    remaining_hours = hours % 24
                    return f"{days}d {remaining_hours:.1f}h"
                return f"{hours:.1f}h"

            session_str = format_uptime(session_h)
            total_str = format_uptime(total_h)

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

        # Stability Analysis Section
        table.add_row("", "")  # Spacer
        table.add_row("[bold cyan]═══ Hashrate Variability ═══[/bold cyan]", "")

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
        for timeframe in ['1h', '4h', '8h', '24h', '3d']:
            data = variance_data.get(timeframe)
            if data:
                variance = data['variance']
                samples = data['samples']
                color, status = format_variance(variance)

                # Create visual bar (scaled 0-100% = 0-10 blocks for BM1370)
                bar_blocks = min(int(variance / 10), 10)
                bar = '█' * bar_blocks

                table.add_row(
                    f"  {timeframe}:",
                    f"[{color}]{variance:>4.1f}% {bar:<10}[/{color}] [{color}]{status}[/{color}] [dim]({samples} samples)[/dim]"
                )
            else:
                table.add_row(f"  {timeframe}:", "[dim]No data[/dim]")

        # Check for warnings
        warnings = []
        if asic_temp >= 65:
            warnings.append("[red]⚠️  THERMAL LIMIT[/red]")
        if vreg_temp >= 80:
            warnings.append("[red]🔥 VR OVERHEATING[/red]")
        elif vreg_temp >= 70:
            warnings.append("[yellow]⚠️  High VR Temp[/yellow]")
        if voltage < 4.8:
            warnings.append("[red]⚠️  PSU VOLTAGE SAG[/red]")
        elif voltage < 4.9:
            warnings.append("[yellow]⚠️  Low Input Voltage[/yellow]")
        if power >= 25:
            warnings.append("[red]⚠️  HIGH POWER DRAW[/red]")
        elif power >= 24:
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

    def create_summary_panel(self) -> Panel:
        """Create summary panel with overall stats."""
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

        # Body - split by number of devices
        if len(self.devices) == 1:
            layout["body"].update(self.create_device_panel(self.devices[0]["name"]))
        elif len(self.devices) == 2:
            layout["body"].split_row(
                Layout(name="device1"),
                Layout(name="device2")
            )
            layout["body"]["device1"].update(
                self.create_device_panel(self.devices[0]["name"])
            )
            layout["body"]["device2"].update(
                self.create_device_panel(self.devices[1]["name"])
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
                    self.create_device_panel(device["name"])
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
    # Load config
    config = load_config()
    db_path = config["logging"]["database_path"]

    # Initialize
    db = Database(db_path)
    analyzer = Analyzer(db)

    # Create and run dashboard
    dashboard = BitaxeDashboard(config, db, analyzer)

    try:
        dashboard.run(refresh_interval=5)
    finally:
        db.close()


if __name__ == "__main__":
    main()
