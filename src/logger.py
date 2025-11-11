"""Main logger daemon for Bitaxe device monitoring."""

import asyncio
import logging
import subprocess
import platform
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .api_client import BitaxeClient
from .database import Database
from .models import SystemInfo, PerformanceMetric

logger = logging.getLogger(__name__)


class BitaxeLogger:
    """Main logger daemon for monitoring Bitaxe devices."""

    def __init__(self, config: dict, db: Database):
        """Initialize logger.

        Args:
            config: Configuration dictionary with devices and logging settings
            db: Database instance
        """
        self.config = config
        self.db = db
        self.devices = config["devices"]
        self.poll_interval = config["logging"]["poll_interval"]
        self.safety_config = config.get("safety", {})
        self.running = False

        # Track device states
        self.device_states: Dict[str, dict] = {}

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
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError, IndexError):
            return None

    async def poll_device(self, device: dict) -> Optional[SystemInfo]:
        """Poll a single device for current metrics.

        Args:
            device: Device configuration dictionary

        Returns:
            SystemInfo object or None if polling failed
        """
        device_name = device["name"]

        try:
            async with BitaxeClient(device["ip"]) as client:
                info = await client.get_system_info()
                logger.debug(f"Successfully polled {device_name}")
                return info

        except Exception as e:
            logger.error(f"Failed to poll {device_name} ({device['ip']}): {e}")
            return None

    async def poll_all_devices(self) -> List[Tuple[str, SystemInfo]]:
        """Poll all enabled devices concurrently.

        Returns:
            List of (device_name, SystemInfo) tuples for successful polls
        """
        tasks = []

        for device in self.devices:
            if device.get("enabled", True):
                task = self.poll_device(device)
                tasks.append((device["name"], device["ip"], task))

        results = []
        for device_name, device_ip, task in tasks:
            info = await task
            if info:
                results.append((device_name, info))

        return results

    def check_safety_thresholds(self, device_name: str, info: SystemInfo):
        """Check safety thresholds and log warnings.

        Args:
            device_name: Device identifier
            info: Current system info
        """
        # Temperature warnings
        max_temp_warning = self.safety_config.get("max_temp_warning", 65)
        max_temp_shutdown = self.safety_config.get("max_temp_shutdown", 70)

        if info.temp >= max_temp_shutdown:
            logger.critical(
                f"🔥 {device_name}: CRITICAL TEMPERATURE {info.temp:.1f}°C "
                f"(shutdown threshold: {max_temp_shutdown}°C)"
            )
        elif info.temp >= max_temp_warning:
            logger.warning(
                f"⚠️  {device_name}: High temperature {info.temp:.1f}°C "
                f"(warning threshold: {max_temp_warning}°C)"
            )

        # Hashrate warnings
        min_hashrate = self.safety_config.get("min_hashrate_warning")
        if min_hashrate and info.hashRate < min_hashrate:
            logger.warning(
                f"⚠️  {device_name}: Low hashrate {info.hashRate:.1f} GH/s "
                f"(minimum: {min_hashrate} GH/s)"
            )

    def store_metrics(self, device_name: str, device_ip: str, info: SystemInfo):
        """Store metrics in database.

        Args:
            device_name: Device identifier
            device_ip: Device IP address
            info: System information from API
        """
        # Register/update device with pool info
        self.db.register_device(
            device_id=device_name,
            ip_address=device_ip,
            hostname=info.hostname,
            model=info.ASICModel,
            stratum_url=info.stratumURL,
            stratum_port=info.stratumPort,
            stratum_user=info.stratumUser
        )

        # Get or create clock config
        config_id = self.db.get_or_create_config(
            frequency=info.frequency,
            core_voltage=info.coreVoltage
        )

        # Check if config changed
        prev_state = self.device_states.get(device_name, {})
        prev_config_id = prev_state.get("config_id")

        if prev_config_id is not None and prev_config_id != config_id:
            prev_config = self.db.get_config(prev_config_id)
            new_config = self.db.get_config(config_id)
            logger.info(
                f"🔄 {device_name}: Config changed from {prev_config} to {new_config}"
            )

        # Update device state
        self.device_states[device_name] = {
            "config_id": config_id,
            "last_poll": datetime.now()
        }

        # Create and store metric
        metric = PerformanceMetric.from_system_info(
            device_id=device_name,
            config_id=config_id,
            info=info
        )
        self.db.insert_metric(metric)

    def log_status(self, device_name: str, device_ip: str, info: SystemInfo):
        """Log current device status to console.

        Args:
            device_name: Device identifier
            device_ip: Device IP address
            info: System information
        """
        # Get ping latency
        ping_ms = self.ping_device(device_ip)

        # Format efficiency with color indicator
        jth = info.efficiency_jth
        if jth < 28:
            eff_indicator = "🟢"  # Excellent
        elif jth < 32:
            eff_indicator = "🟡"  # Good
        else:
            eff_indicator = "🔴"  # Poor

        # Format power with color coding
        # ANSI color codes: Yellow=\033[93m, Red=\033[91m, Reset=\033[0m
        power = info.power
        if power >= 40:
            power_str = f"\033[91m{power:.1f}W\033[0m"  # Red for 40W+
        elif power >= 35:
            power_str = f"\033[93m{power:.1f}W\033[0m"  # Yellow for 35-40W
        else:
            power_str = f"{power:.1f}W"  # Normal

        # Format ping with color coding
        # ANSI color codes: Green=\033[92m, Yellow=\033[93m, Red=\033[91m, Reset=\033[0m
        if ping_ms is not None:
            if ping_ms < 50:
                ping_str = f"\033[92m{ping_ms:.1f}ms\033[0m"  # Green
            elif ping_ms < 100:
                ping_str = f"\033[93m{ping_ms:.1f}ms\033[0m"  # Yellow
            else:
                ping_str = f"\033[91m{ping_ms:.1f}ms\033[0m"  # Red
        else:
            ping_str = f"\033[91mN/A\033[0m"  # Red for unreachable

        logger.info(
            f"{device_name}: "
            f"{info.hashRate:.1f} GH/s | "
            f"{info.temp:.1f}°C | "
            f"{power_str} | "
            f"{ping_str} | "
            f"{eff_indicator} {jth:.1f} J/TH | "
            f"{info.frequency}MHz@{info.coreVoltage}mV"
        )

    async def run(self):
        """Main logging loop."""
        self.running = True
        logger.info("=" * 60)
        logger.info("Starting Bitaxe Logger")
        logger.info(f"Monitoring {len([d for d in self.devices if d.get('enabled', True)])} devices")
        logger.info(f"Poll interval: {self.poll_interval}s")
        logger.info("=" * 60)

        poll_count = 0

        while self.running:
            try:
                poll_count += 1
                logger.debug(f"Poll #{poll_count} at {datetime.now().strftime('%H:%M:%S')}")

                # Poll all devices
                results = await self.poll_all_devices()

                if not results:
                    logger.warning("No devices responded this cycle")

                # Process results
                for device_name, info in results:
                    # Find device config for IP
                    device_config = next(d for d in self.devices if d["name"] == device_name)

                    # Store in database
                    self.store_metrics(device_name, device_config["ip"], info)

                    # Check safety thresholds
                    self.check_safety_thresholds(device_name, info)

                    # Log status with ping
                    self.log_status(device_name, device_config["ip"], info)

                # Wait for next poll
                await asyncio.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("\nReceived interrupt signal, stopping...")
                break

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                logger.info("Waiting 10 seconds before retry...")
                await asyncio.sleep(10)

        logger.info("Logger stopped")

    def stop(self):
        """Stop the logger."""
        self.running = False

    def get_stats(self) -> dict:
        """Get logger statistics.

        Returns:
            Dictionary with stats about logged data
        """
        stats = {
            "devices": {},
            "total_metrics": self.db.get_metric_count()
        }

        for device in self.devices:
            if device.get("enabled", True):
                device_name = device["name"]
                device_metrics = self.db.get_metric_count(device_name)
                latest = self.db.get_latest_metric(device_name)

                stats["devices"][device_name] = {
                    "metrics_count": device_metrics,
                    "latest": latest
                }

        return stats
