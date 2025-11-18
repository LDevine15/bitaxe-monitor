"""Remote data provider for fetching dashboard data from API server."""

import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RemoteProvider:
    """Fetches dashboard data from a remote API server."""

    def __init__(self, base_url: str, timeout: int = 10):
        """Initialize remote provider.

        Args:
            base_url: Base URL of the API server (e.g., 'http://raspberrypi.local:5001')
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._devices_cache = None

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make GET request to API.

        Args:
            endpoint: API endpoint (e.g., '/api/devices')
            params: Query parameters

        Returns:
            JSON response or None on error
        """
        try:
            url = f"{self.base_url}{endpoint}"
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {endpoint} - {e}")
            return None

    def get_devices(self) -> List[dict]:
        """Get list of configured devices."""
        if self._devices_cache is None:
            result = self._get('/api/devices')
            if result:
                self._devices_cache = result.get('devices', [])
            else:
                self._devices_cache = []
        return self._devices_cache

    def get_latest_metric(self, device_id: str) -> Optional[dict]:
        """Get latest metrics for a device."""
        return self._get(f'/api/metrics/latest/{device_id}')

    def get_uptime_averages(self, device_id: str, uptime_seconds: int) -> dict:
        """Get average hashrate and efficiency during uptime period."""
        result = self._get(f'/api/metrics/uptime-avg/{device_id}/{uptime_seconds}')
        return result or {'avg_hashrate': None, 'avg_efficiency': None}

    def get_session_stats(self, device_id: str, metric: str, uptime_seconds: int) -> Optional[dict]:
        """Get statistics for a metric during the current uptime session."""
        return self._get(f'/api/metrics/session-stats/{device_id}/{metric}/{uptime_seconds}')

    def get_hashrate_trend(self, device_id: str, minutes: int, num_buckets: int) -> List[float]:
        """Get bucketed hashrate trend."""
        result = self._get(
            f'/api/metrics/hashrate-trend/{device_id}',
            params={'minutes': minutes, 'buckets': num_buckets}
        )
        return result if result else []

    def get_total_uptime(self, device_id: str) -> Optional[dict]:
        """Get total cumulative uptime stats."""
        return self._get(f'/api/metrics/total-uptime/{device_id}')

    def get_highest_difficulty(self, device_id: str) -> Optional[dict]:
        """Get highest difficulty achieved."""
        return self._get(f'/api/metrics/highest-difficulty/{device_id}')

    def get_variance(self, device_id: str) -> Dict[str, Optional[dict]]:
        """Get multi-timeframe variance data."""
        result = self._get(f'/api/metrics/variance/{device_id}')
        return result if result else {}

    def get_device_info(self, device_id: str) -> Optional[dict]:
        """Get device info from devices table."""
        return self._get(f'/api/device-info/{device_id}')

    def get_summary(self) -> Dict[str, dict]:
        """Get summary for all devices."""
        result = self._get('/api/summary')
        return result if result else {}

    def health_check(self) -> bool:
        """Check if API server is reachable."""
        result = self._get('/health')
        return result is not None and result.get('status') == 'ok'
