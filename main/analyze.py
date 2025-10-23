#!/usr/bin/env python3
"""CLI tool for analyzing Bitaxe performance data."""

import sys
import yaml
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.analyzer import Analyzer


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_file) as f:
        return yaml.safe_load(f)


def print_usage():
    """Print usage information."""
    print("""
Bitaxe Performance Analyzer

Usage:
    python analyze.py summary [device_id] [--hours N]
    python analyze.py compare [device_id] [--hours N]
    python analyze.py export [device_id] [output.csv]
    python analyze.py stats

Commands:
    summary         Show detailed performance summary for a device
    compare         Compare all configurations with bottleneck analysis
    export          Export metrics to CSV file
    stats           Show quick stats for all devices

Options:
    device_id       Device name (e.g., bitaxe-1) [default: first device]
    --hours N       Limit analysis to last N hours [default: all data]

Examples:
    python analyze.py compare bitaxe-1
    python analyze.py summary bitaxe-2 --hours 24
    python analyze.py export bitaxe-1 data.csv
    python analyze.py stats
""")


def cmd_summary(analyzer: Analyzer, device_id: str, hours: int = None):
    """Show summary for a device."""
    configs = analyzer.get_config_summary(device_id, hours)

    if not configs:
        print(f"No data found for {device_id}")
        return

    print("=" * 100)
    print(f"Performance Summary: {device_id}")
    if hours:
        print(f"Time window: Last {hours} hours")
    print("=" * 100)
    print()

    # Summary table
    print(f"{'Config':<18} {'Samples':<8} {'Hashrate':<12} {'Efficiency':<12} {'Power':<8} {'ASIC°C':<8} {'VR°C':<8} {'Input V':<8}")
    print("-" * 100)

    for cfg in configs:
        config_name = f"{cfg['frequency']}@{cfg['core_voltage']}"
        print(
            f"{config_name:<18} "
            f"{cfg['sample_count']:<8} "
            f"{cfg['avg_hashrate']:>6.1f} GH/s  "
            f"{cfg['avg_efficiency_jth']:>6.1f} J/TH  "
            f"{cfg['avg_power']:>5.1f}W  "
            f"{cfg['avg_asic_temp']:>5.1f}  "
            f"{cfg['avg_vreg_temp']:>5.1f}  "
            f"{cfg['avg_input_voltage']:>5.2f}V"
        )

    print()


def cmd_compare(analyzer: Analyzer, device_id: str, hours: int = None):
    """Show detailed comparison with bottleneck analysis."""
    report = analyzer.compare_configs(device_id, hours)
    print(report)


def cmd_export(analyzer: Analyzer, device_id: str, output_path: str):
    """Export metrics to CSV."""
    print(f"Exporting {device_id} metrics to {output_path}...")
    analyzer.export_csv(device_id, output_path)
    print(f"✓ Export complete: {output_path}")


def cmd_stats(analyzer: Analyzer):
    """Show quick stats for all devices with config averages."""
    summary = analyzer.get_all_devices_summary()

    print("=" * 100)
    print("Quick Stats - All Devices")
    print("=" * 100)
    print()

    for device_id, data in summary.items():
        print(f"📊 {device_id}")
        print(f"   Total samples: {data['total_samples']}")
        print()

        if data['configs']:
            print(f"   {'Config':<18} {'Samples':<8} {'Avg Hash':<12} {'Efficiency':<12} {'Avg Temp':<10} {'Avg Power':<10}")
            print(f"   {'-' * 90}")

            for cfg in data['configs']:
                config_name = f"{cfg['frequency']}@{cfg['core_voltage']}"

                # Add indicator for best efficiency
                indicator = "🏆" if cfg == min(data['configs'], key=lambda x: x['avg_efficiency_jth']) else "  "

                print(
                    f"   {indicator}{config_name:<16} "
                    f"{cfg['sample_count']:<8} "
                    f"{cfg['avg_hashrate']:>6.1f} GH/s  "
                    f"{cfg['avg_efficiency_jth']:>6.1f} J/TH  "
                    f"{cfg['avg_asic_temp']:>5.1f}°C    "
                    f"{cfg['avg_power']:>5.1f}W"
                )

            print()

            # Show current/latest config
            if data['latest']:
                latest = data['latest']
                print(f"   Currently running: {latest['frequency']}MHz @ {latest['core_voltage']}mV")
                print(f"   Current: {latest['hashrate']:.1f} GH/s, {latest['asic_temp']:.1f}°C, {latest['efficiency_jth']:.1f} J/TH")
        else:
            print("   No data collected yet")

        print()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command in ['-h', '--help', 'help']:
        print_usage()
        sys.exit(0)

    # Load config and initialize
    config = load_config()
    db_path = config["logging"]["database_path"]
    db = Database(db_path)
    analyzer = Analyzer(db)

    # Get default device (first enabled device)
    enabled_devices = [d for d in config["devices"] if d.get("enabled", True)]
    default_device = enabled_devices[0]["name"] if enabled_devices else None

    try:
        if command == "stats":
            cmd_stats(analyzer)

        elif command == "summary":
            device_id = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else default_device
            hours = None

            # Parse --hours flag
            if '--hours' in sys.argv:
                hours_idx = sys.argv.index('--hours')
                if hours_idx + 1 < len(sys.argv):
                    hours = int(sys.argv[hours_idx + 1])

            if not device_id:
                print("Error: No device specified and no devices configured")
                sys.exit(1)

            cmd_summary(analyzer, device_id, hours)

        elif command == "compare":
            device_id = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else default_device
            hours = None

            # Parse --hours flag
            if '--hours' in sys.argv:
                hours_idx = sys.argv.index('--hours')
                if hours_idx + 1 < len(sys.argv):
                    hours = int(sys.argv[hours_idx + 1])

            if not device_id:
                print("Error: No device specified and no devices configured")
                sys.exit(1)

            cmd_compare(analyzer, device_id, hours)

        elif command == "export":
            if len(sys.argv) < 3:
                print("Error: Device ID required for export")
                print("Usage: python analyze.py export [device_id] [output.csv]")
                sys.exit(1)

            device_id = sys.argv[2]
            output_path = sys.argv[3] if len(sys.argv) > 3 else f"{device_id}_export.csv"

            cmd_export(analyzer, device_id, output_path)

        else:
            print(f"Unknown command: {command}")
            print_usage()
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
