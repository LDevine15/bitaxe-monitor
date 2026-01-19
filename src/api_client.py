"""Async HTTP client for Bitaxe REST API."""

import aiohttp
import logging
from typing import Dict, Optional
from .models import SystemInfo

logger = logging.getLogger(__name__)


class BitaxeClient:
    """Async HTTP client for Bitaxe API endpoints."""

    def __init__(self, ip_address: str, timeout: int = 10):
        """Initialize client.

        Args:
            ip_address: IP address of Bitaxe device
            timeout: Request timeout in seconds
        """
        self.base_url = f"http://{ip_address}"
        self.ip_address = ip_address
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Create session on context entry."""
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close session on context exit."""
        if self.session:
            await self.session.close()

    async def get_system_info(self) -> SystemInfo:
        """Fetch current system information.

        Returns:
            SystemInfo object with current device metrics

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
            ValueError: On invalid response data
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        url = f"{self.base_url}/api/system/info"
        logger.debug(f"Fetching system info from {url}")

        try:
            async with self.session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                return SystemInfo(**data)
        except aiohttp.ClientError as e:
            logger.error(f"Failed to fetch system info from {self.ip_address}: {e}")
            raise
        except Exception as e:
            logger.error(f"Invalid response from {self.ip_address}: {e}")
            raise ValueError(f"Invalid system info response: {e}")

    async def get_statistics(self, columns: list[str]) -> Dict:
        """Fetch historical statistics.

        Args:
            columns: List of metric columns to retrieve
                    (e.g., ['hashrate', 'asicTemp', 'power'])

        Returns:
            Dictionary with currentTimestamp, labels, and statistics arrays

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        params = {"columns": ",".join(columns)}
        url = f"{self.base_url}/api/system/statistics"

        async with self.session.get(url, params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def update_config(self, frequency: int, core_voltage: int) -> None:
        """Update device frequency and voltage configuration.

        Args:
            frequency: Frequency in MHz
            core_voltage: Core voltage in mV

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        payload = {
            "frequency": frequency,
            "coreVoltage": core_voltage
        }

        url = f"{self.base_url}/api/system"
        logger.info(f"Updating {self.ip_address} config: {frequency}MHz @ {core_voltage}mV")

        async with self.session.patch(url, json=payload) as response:
            response.raise_for_status()

    async def restart(self) -> None:
        """Restart the device.

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        url = f"{self.base_url}/api/system/restart"
        logger.warning(f"Restarting device at {self.ip_address}")

        async with self.session.post(url) as response:
            response.raise_for_status()

    async def set_frequency(self, frequency: int) -> None:
        """Update device frequency.

        Args:
            frequency: Frequency in MHz

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        payload = {"frequency": frequency}
        url = f"{self.base_url}/api/system"
        logger.info(f"Setting {self.ip_address} frequency: {frequency}MHz")

        async with self.session.patch(url, json=payload) as response:
            response.raise_for_status()

    async def set_voltage(self, core_voltage: int) -> None:
        """Update device core voltage.

        Args:
            core_voltage: Core voltage in mV

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        payload = {"coreVoltage": core_voltage}
        url = f"{self.base_url}/api/system"
        logger.info(f"Setting {self.ip_address} voltage: {core_voltage}mV")

        async with self.session.patch(url, json=payload) as response:
            response.raise_for_status()

    async def set_fan_speed(self, fan_speed: int) -> None:
        """Update device fan speed.

        Disables auto fan mode and sets manual fan speed.

        Args:
            fan_speed: Fan speed percentage (0-100)

        Raises:
            aiohttp.ClientError: On connection/HTTP errors
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        # Disable auto mode and set manual fan speed
        payload = {"autofanspeed": 0, "manualFanSpeed": fan_speed}
        url = f"{self.base_url}/api/system"
        logger.info(f"Setting {self.ip_address} fan speed: {fan_speed}%")

        async with self.session.patch(url, json=payload) as response:
            response.raise_for_status()

    async def health_check(self) -> bool:
        """Check if device is reachable.

        Returns:
            True if device responds, False otherwise
        """
        try:
            await self.get_system_info()
            return True
        except Exception:
            return False
