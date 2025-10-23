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

    def create_device_panel(self, device_id: str) -> Panel:
        """Create a panel showing device status.

        Args:
            device_id: Device identifier

        Returns:
            Rich Panel with device information
        """
        latest = self.db.get_latest_metric(device_id)

        if not latest:
            return Panel(
                Text("No data available", style="dim"),
                title=f"[bold cyan]{device_id}[/bold cyan]",
                border_style="red"
            )

        # Get uptime and calculate average
        uptime_seconds = latest['uptime']
        avg_hashrate = self.get_uptime_average_hashrate(device_id, uptime_seconds)

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
        vr_color = "red" if vreg_temp >= 65 else "yellow" if vreg_temp >= 58 else "white"
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

        # Uptime
        uptime_hours = latest['uptime'] / 3600
        table.add_row("Uptime:", f"{uptime_hours:.1f}h")

        # Check for warnings
        warnings = []
        if asic_temp >= 65:
            warnings.append("[red]⚠️  THERMAL LIMIT[/red]")
        if vreg_temp >= 65:
            warnings.append("[red]⚠️  VR OVERHEATING[/red]")
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
            title=f"[bold cyan]{device_id}[/bold cyan]",
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

    def run(self, refresh_interval: int = 3):
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
        dashboard.run(refresh_interval=3)
    finally:
        db.close()


if __name__ == "__main__":
    main()
