#!/usr/bin/env python3
"""Discord bot entry point for Bitaxe monitoring."""

import sys
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.discord import BitaxeBot, DiscordConfig


def setup_logging(level: str = "INFO"):
    """Configure logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('data/discord_bot.log')
        ]
    )


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file

    Returns:
        Configuration dictionary
    """
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Error: Config file not found: {config_path}")
        print("Please create config.yaml from config-discord-example.yaml")
        sys.exit(1)

    with open(config_file) as f:
        return yaml.safe_load(f)


def main():
    """Main entry point."""
    # Load environment variables from .env
    load_dotenv()

    # Load main config
    config = load_config()

    # Setup logging
    log_level = config.get('logging', {}).get('log_level', 'INFO')
    setup_logging(log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting Bitaxe Discord Bot")

    # Check if Discord is enabled
    discord_config_dict = config.get('discord', {})
    if not discord_config_dict.get('enabled', False):
        logger.error("Discord bot is not enabled in config.yaml")
        logger.error("Set discord.enabled to true in config.yaml")
        sys.exit(1)

    # Parse Discord config
    try:
        discord_config = DiscordConfig.from_yaml(discord_config_dict)
    except ValueError as e:
        logger.error(f"Discord configuration error: {e}")
        logger.error("Check your .env file and config.yaml")
        sys.exit(1)

    # Connect to database
    db_path = config['logging']['database_path']
    if not Path(db_path).exists():
        logger.error(f"Database not found: {db_path}")
        logger.error("Make sure run_logger.py is running to collect data")
        sys.exit(1)

    logger.info(f"Connecting to database: {db_path}")
    db = Database(db_path)

    # Get devices
    devices = config.get('devices', [])
    enabled_devices = [d for d in devices if d.get('enabled', True)]
    logger.info(f"Monitoring {len(enabled_devices)} devices")

    # Create and run bot
    try:
        bot = BitaxeBot(discord_config, db, devices)
        logger.info("Starting Discord bot...")
        bot.run(discord_config.token)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=e)
        sys.exit(1)
    finally:
        db.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    main()
