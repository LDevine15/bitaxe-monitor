#!/usr/bin/env python3
"""Simple entry point script to run the Bitaxe logger."""

import asyncio
import logging
import sys
import yaml
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.logger import BitaxeLogger


def setup_logging(level: str = "INFO"):
    """Configure logging with color and formatting.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

    # Reduce noise from aiohttp
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}")
        print("Please copy config.yaml.example to config.yaml and update with your device IPs")
        sys.exit(1)

    with open(config_file) as f:
        config = yaml.safe_load(f)

    return config


async def main():
    """Main entry point."""
    print("\n" + "=" * 60)
    print("Bitaxe Multi-Miner Performance Logger")
    print("=" * 60 + "\n")

    # Load configuration
    try:
        config = load_config()
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)

    # Setup logging
    log_level = config.get("logging", {}).get("log_level", "INFO")
    setup_logging(log_level)

    logger = logging.getLogger(__name__)

    # Initialize database
    db_path = config["logging"]["database_path"]
    logger.info(f"Initializing database: {db_path}")
    db = Database(db_path)

    # Create logger instance
    bitaxe_logger = BitaxeLogger(config, db)

    try:
        # Run logger
        await bitaxe_logger.run()

    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # Cleanup
        logger.info("Closing database...")
        db.close()

        # Print final stats
        print("\n" + "=" * 60)
        print("Session Summary")
        print("=" * 60)

        stats = bitaxe_logger.get_stats()
        print(f"Total metrics collected: {stats['total_metrics']}")

        for device_name, device_stats in stats["devices"].items():
            print(f"\n{device_name}:")
            print(f"  Samples: {device_stats['metrics_count']}")

            if device_stats["latest"]:
                latest = device_stats["latest"]
                print(f"  Latest: {latest['hashrate']:.1f} GH/s, "
                      f"{latest['asic_temp']:.1f}°C, "
                      f"{latest['efficiency_jth']:.1f} J/TH")

        print("\n" + "=" * 60)
        print("Logger stopped. Data saved to database.")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
