"""Chart generation for Discord bot using matplotlib."""

import logging
import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from ..database import Database

logger = logging.getLogger(__name__)

# Miner color palette (vibrant colors that work on dark backgrounds)
MINER_COLORS = [
    '#3498DB',  # Blue
    '#2ECC71',  # Green
    '#E74C3C',  # Red
    '#F39C12',  # Orange
    '#9B59B6',  # Purple
    '#1ABC9C',  # Teal
]


class ChartCache:
    """Simple time-based cache for chart images."""

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            ttl_seconds: Time to live for cached items (default 5 minutes)
        """
        self.ttl = ttl_seconds
        self.cache: Dict[str, Tuple[bytes, datetime]] = {}

    def get(self, key: str) -> Optional[bytes]:
        """Get cached item if not expired.

        Args:
            key: Cache key

        Returns:
            Cached bytes or None if expired/missing
        """
        if key in self.cache:
            data, timestamp = self.cache[key]
            if (datetime.now() - timestamp).total_seconds() < self.ttl:
                logger.debug(f"Cache hit: {key}")
                return data
            else:
                del self.cache[key]
                logger.debug(f"Cache expired: {key}")
        return None

    def set(self, key: str, data: bytes):
        """Store item in cache.

        Args:
            key: Cache key
            data: Bytes to cache
        """
        self.cache[key] = (data, datetime.now())
        logger.debug(f"Cache set: {key}")

    def clear(self):
        """Clear all cached items."""
        self.cache.clear()
        logger.debug("Cache cleared")


class ChartGenerator:
    """Generate matplotlib charts for Discord embeds."""

    def __init__(self, db: Database, config: dict):
        """Initialize chart generator.

        Args:
            db: Database instance
            config: Chart configuration dict from discord config
        """
        self.db = db
        self.config = config
        self.cache = ChartCache(ttl_seconds=config.get('cache_ttl', 300))

        # Chart styling
        self.dpi = config.get('dpi', 150)
        self.figsize = tuple(config.get('figsize', [12, 6]))
        self.style = config.get('style', 'dark_background')

    def _configure_plot_style(self):
        """Apply consistent styling to matplotlib plots."""
        plt.style.use(self.style)

        # Set default font sizes and colors
        plt.rcParams.update({
            'font.size': 10,
            'axes.titlesize': 14,
            'axes.labelsize': 11,
            'xtick.labelsize': 9,
            'ytick.labelsize': 9,
            'legend.fontsize': 9,
            'figure.titlesize': 16,
            'grid.alpha': 0.3,
            'grid.linestyle': '--',
        })

    def _save_figure_to_bytes(self, fig: Figure) -> bytes:
        """Save matplotlib figure to bytes buffer.

        Args:
            fig: Matplotlib figure

        Returns:
            PNG image as bytes
        """
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=self.dpi, bbox_inches='tight')
        buf.seek(0)
        image_bytes = buf.read()
        buf.close()
        plt.close(fig)
        return image_bytes

    def _calculate_moving_average(self, data: List[Optional[float]], window: int) -> List[Optional[float]]:
        """Calculate moving average, handling None values.

        Args:
            data: List of values (may contain None)
            window: Window size for moving average

        Returns:
            List of smoothed values
        """
        # Convert to numpy array, replacing None with nan
        arr = np.array([x if x is not None else np.nan for x in data])

        # Calculate rolling average
        result = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            window_data = arr[start:i+1]
            # Only calculate if we have at least half the window size of valid data
            valid_count = np.sum(~np.isnan(window_data))
            if valid_count >= window // 2:
                result.append(np.nanmean(window_data))
            else:
                result.append(None)

        return result

    def generate_swarm_hashrate_chart(self, hours: int, device_ids: List[str]) -> bytes:
        """Generate swarm total hashrate chart with moving averages.

        Args:
            hours: Lookback period in hours
            device_ids: List of device IDs to include

        Returns:
            PNG image as bytes
        """
        cache_key = f"swarm_hashrate_{hours}h_{'_'.join(sorted(device_ids))}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        logger.info(f"Generating swarm hashrate chart ({hours}h)")

        self._configure_plot_style()

        # Get data for all devices
        minutes = hours * 60

        # Get config changes during this period
        config_changes = self.db.get_config_changes(device_ids, minutes)

        # Use 5-minute buckets consistently for cleaner data
        bucket_minutes = 5
        # Allow enough buckets to support 24h MA (need 288 buckets minimum for 24h)
        # Cap at 576 buckets (48 hours at 5-min intervals) to keep chart reasonable
        buckets = min(576, minutes // 5)

        # Sum hashrates across all devices
        all_trends = []
        for device_id in device_ids:
            trend = self.db.get_bucketed_hashrate_trend(device_id, minutes, buckets)
            all_trends.append(trend)

        # Sum at each bucket (handling None values)
        swarm_trend = []
        for bucket_idx in range(buckets):
            bucket_sum = 0
            valid_count = 0
            for trend in all_trends:
                if trend[bucket_idx] is not None:
                    bucket_sum += trend[bucket_idx]
                    valid_count += 1
            # Only add if we have data from at least one device
            swarm_trend.append(bucket_sum if valid_count > 0 else None)

        # Generate timestamps
        now = datetime.now()
        timestamps = [now - timedelta(minutes=minutes * (buckets - i - 1) / buckets) for i in range(buckets)]

        # Calculate consistent moving averages for all timeframes
        # 15-min MA for short-term trends, 24h MA for long-term trends
        ma_short = self._calculate_moving_average(swarm_trend, window=3)  # 3 * 5min = 15min
        ma_long = self._calculate_moving_average(swarm_trend, window=288)  # 288 * 5min = 24h
        ma_short_label = '15-min MA'
        ma_long_label = '24h MA'

        # Create figure
        fig, ax = plt.subplots(figsize=self.figsize)

        # Plot adaptive moving average lines
        ax.plot(timestamps, ma_short, '-', color='#00FFFF', linewidth=2.5,
                label=ma_short_label, alpha=0.9, marker='o', markersize=2)
        ax.plot(timestamps, ma_long, '-', color='#FFD700', linewidth=3,
                label=ma_long_label, alpha=0.95)

        # Fill under long MA curve
        valid_indices = [i for i, v in enumerate(ma_long) if v is not None]
        if valid_indices:
            ax.fill_between([timestamps[i] for i in valid_indices],
                           [ma_long[i] for i in valid_indices],
                           alpha=0.15, color='#FFD700')

        # Add padding to y-axis to reduce dramatic appearance of variance
        # (do this BEFORE adding markers so we know where to place them)
        valid_data = [v for v in swarm_trend if v is not None]
        if valid_data:
            data_min = min(valid_data)
            data_max = max(valid_data)
            data_range = data_max - data_min
            # Add 20% padding above and below
            padding = data_range * 0.2
            ax.set_ylim(max(0, data_min - padding), data_max + padding)

        # Add horizontal average line for the entire sample period
        if valid_data:
            period_average = np.mean(valid_data)
            ax.axhline(y=period_average, color='white', linestyle='-', linewidth=2,
                      label=f'Period Avg ({period_average:.1f} GH/s)', alpha=0.7, zorder=5)

        # Add markers for config changes (after y-limits are set)
        if config_changes:
            y_min, y_max = ax.get_ylim()
            marker_y = y_max * 0.95  # Place markers near top of chart

            for idx, change in enumerate(config_changes):
                # Plot vertical dashed line
                ax.axvline(x=change['timestamp'], color='#FF69B4', linestyle='--',
                          linewidth=1.5, alpha=0.6, zorder=3)

                # Add diamond marker at the top
                ax.plot(change['timestamp'], marker_y, marker='D', color='#FF69B4',
                       markersize=8, markeredgecolor='white', markeredgewidth=1.5,
                       zorder=10)

                # Add label for first config change only (to avoid legend clutter)
                if idx == 0:
                    ax.plot([], [], marker='D', color='#FF69B4', linestyle='--',
                           markersize=8, markeredgecolor='white', markeredgewidth=1.5,
                           label='Config Change', alpha=0.6)

        # Formatting
        ax.set_xlabel('Time')
        ax.set_ylabel('Hashrate (GH/s)')

        # Format title based on timespan
        if hours >= 24 and hours % 24 == 0:
            title = f'Swarm Total Hashrate ({hours//24}d)'
        else:
            title = f'Swarm Total Hashrate ({hours}h)'
        ax.set_title(title, fontweight='bold', pad=20)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper left', framealpha=0.8)

        # Format x-axis based on timespan
        if hours <= 12:
            # Short: Show time only
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        elif hours <= 48:
            # 1-2 days: Show day and time
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        elif hours <= 168:
            # 3-7 days: Show day only
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        else:
            # 8+ days: Show day with more spacing
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        plt.xticks(rotation=45, ha='right')

        # Add stats text (current values from MAs and variance)
        valid_short = [v for v in ma_short if v is not None]
        valid_long = [v for v in ma_long if v is not None]
        valid_data = [v for v in swarm_trend if v is not None]
        if valid_short and valid_long and valid_data:
            current_short = ma_short[-1] if ma_short[-1] is not None else 0
            current_long = ma_long[-1] if ma_long[-1] is not None else 0
            period_avg = np.mean(valid_data)
            variance = (np.std(valid_data) / period_avg * 100) if period_avg > 0 else 0

            stats_text = f"{ma_short_label}: {current_short:.1f} GH/s | {ma_long_label}: {current_long:.1f} GH/s | Variance: ±{variance:.1f}%"
            ax.text(0.5, 0.98, stats_text, transform=ax.transAxes,
                   fontsize=10, va='top', ha='center',
                   bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))

        fig.tight_layout()

        # Save to bytes
        image_bytes = self._save_figure_to_bytes(fig)
        self.cache.set(cache_key, image_bytes)

        logger.info(f"Swarm hashrate chart generated ({len(image_bytes)} bytes)")
        return image_bytes

    def generate_miner_detail_chart(self, hours: int, device_ids: List[str]) -> bytes:
        """Generate per-miner hashrate chart with temperature overlay.

        Args:
            hours: Lookback period in hours
            device_ids: List of device IDs to include

        Returns:
            PNG image as bytes
        """
        cache_key = f"miner_detail_{hours}h_{'_'.join(sorted(device_ids))}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        logger.info(f"Generating miner detail chart ({hours}h)")

        self._configure_plot_style()

        # Get data
        minutes = hours * 60

        # Get config changes during this period
        config_changes = self.db.get_config_changes(device_ids, minutes)

        # Use 5-minute buckets consistently
        bucket_minutes = 5
        # Allow enough buckets to support 24h MA (need 288 buckets minimum for 24h)
        # Cap at 576 buckets (48 hours at 5-min intervals) to keep chart reasonable
        buckets = min(576, minutes // 5)

        # Generate timestamps
        now = datetime.now()
        timestamps = [now - timedelta(minutes=minutes * (buckets - i - 1) / buckets) for i in range(buckets)]

        # Create figure with two subplots (hashrate on top, temperature below)
        # Height ratio: 2:1 (hashrate gets 2/3, temperature gets 1/3)
        fig, (ax_hashrate, ax_temp) = plt.subplots(2, 1, figsize=(self.figsize[0], self.figsize[1] * 1.2),
                                                     height_ratios=[2, 1], sharex=True)

        # Collect all temp and hashrate data to set proper y-axis limits
        all_temps = []
        all_hashrates = []

        # Store hashrate data for each device (for config markers)
        device_hashrate_data = {}
        device_temp_data = {}

        # Plot data for each miner
        for idx, device_id in enumerate(device_ids):
            color = MINER_COLORS[idx % len(MINER_COLORS)]

            # Get hashrate trend
            hashrate_trend = self.db.get_bucketed_hashrate_trend(device_id, minutes, buckets)

            # Calculate 15-min MA for hashrate (consistent across all timeframes)
            hashrate_ma = self._calculate_moving_average(hashrate_trend, window=3)  # 15-min MA

            # Store for config change markers
            device_hashrate_data[device_id] = {
                'hashrate_ma': hashrate_ma,
                'color': color
            }

            # Collect valid hashrates for axis scaling
            valid_hr = [h for h in hashrate_ma if h is not None]
            all_hashrates.extend(valid_hr)

            # Plot smoothed hashrate line on top subplot
            ax_hashrate.plot(timestamps, hashrate_ma, '-', color=color, linewidth=2.5,
                            label=f'{device_id}', alpha=0.9, marker='o', markersize=2)

            # Get temperature trend
            temp_trend = self.db.get_bucketed_temp_trend(device_id, minutes, buckets)

            # Calculate 15-min MA for temperature
            temp_ma = self._calculate_moving_average(temp_trend, window=3)  # 15-min MA

            # Store temperature data
            device_temp_data[device_id] = temp_ma

            # Collect valid temps for axis scaling
            valid_temps = [t for t in temp_ma if t is not None]
            all_temps.extend(valid_temps)

            # Plot smoothed temperature as line on bottom subplot
            ax_temp.plot(timestamps, temp_ma, '-', color=color, linewidth=2,
                        alpha=0.8)

        # Add config change markers on the hashrate lines
        if config_changes:
            for change in config_changes:
                device_id = change['device_id']
                if device_id in device_hashrate_data:
                    # Find closest timestamp index
                    closest_idx = min(range(len(timestamps)),
                                     key=lambda i: abs((timestamps[i] - change['timestamp']).total_seconds()))

                    # Get hashrate value at that timestamp
                    hashrate_ma = device_hashrate_data[device_id]['hashrate_ma']
                    color = device_hashrate_data[device_id]['color']

                    if hashrate_ma[closest_idx] is not None:
                        # Plot diamond marker directly on the line (use miner's color)
                        ax_hashrate.plot(timestamps[closest_idx], hashrate_ma[closest_idx],
                                        marker='D', color=color, markersize=10,
                                        markeredgecolor='white', markeredgewidth=2,
                                        zorder=15)

        # Format title based on timespan
        if hours >= 24 and hours % 24 == 0:
            title = f'Individual Miner Performance ({hours//24}d)'
        else:
            title = f'Individual Miner Performance ({hours}h)'
        ax_hashrate.set_title(title, fontweight='bold', pad=20)

        # Hashrate subplot formatting
        ax_hashrate.set_ylabel('Hashrate (GH/s)', color='#FFFFFF')
        ax_hashrate.grid(True, alpha=0.3)
        ax_hashrate.legend(loc='upper left', framealpha=0.8, title='Hashrate (15-min MA)')

        # Temperature subplot formatting
        ax_temp.set_xlabel('Time')
        ax_temp.set_ylabel('Temperature (°C)', color='#FF6B6B')
        ax_temp.grid(True, alpha=0.3)

        # Add temperature average text
        if all_temps:
            temp_avg = sum(all_temps) / len(all_temps)
            ax_temp.text(0.98, 0.98, f'Avg: {temp_avg:.1f}°C',
                        transform=ax_temp.transAxes, fontsize=9, va='top', ha='right',
                        color='#FF6B6B', bbox=dict(boxstyle='round', facecolor='black', alpha=0.5))

        # Format x-axis based on timespan (only on bottom subplot since sharex=True)
        if hours <= 12:
            # Short: Show time only
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax_temp.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        elif hours <= 48:
            # 1-2 days: Show day and time
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            ax_temp.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        elif hours <= 168:
            # 3-7 days: Show day only
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax_temp.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        else:
            # 8+ days: Show day with more spacing
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax_temp.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        plt.setp(ax_temp.xaxis.get_majorticklabels(), rotation=45, ha='right')

        # Color the y-axis labels
        ax_hashrate.tick_params(axis='y', labelcolor='#FFFFFF')
        ax_temp.tick_params(axis='y', labelcolor='#FF6B6B')

        # Add padding to hashrate y-axis to reduce dramatic appearance
        if all_hashrates:
            hr_min = min(all_hashrates)
            hr_max = max(all_hashrates)
            hr_range = hr_max - hr_min
            # Add 20% padding
            padding = hr_range * 0.2
            ax_hashrate.set_ylim(max(0, hr_min - padding), hr_max + padding)

        # Set temperature y-axis limits with padding
        if all_temps:
            temp_min = min(all_temps)
            temp_max = max(all_temps)
            temp_range = temp_max - temp_min
            # Add 20% padding above and below
            padding = temp_range * 0.2
            ax_temp.set_ylim(max(30, temp_min - padding),
                            min(90, temp_max + padding))
        else:
            ax_temp.set_ylim(40, 80)  # Fallback if no data

        fig.tight_layout()

        # Save to bytes
        image_bytes = self._save_figure_to_bytes(fig)
        self.cache.set(cache_key, image_bytes)

        logger.info(f"Miner detail chart generated ({len(image_bytes)} bytes)")
        return image_bytes

    def generate_single_miner_chart(self, device_id: str, hours: int) -> bytes:
        """Generate detailed chart for a single miner.

        Args:
            device_id: Device ID
            hours: Lookback period in hours

        Returns:
            PNG image as bytes
        """
        cache_key = f"single_miner_{device_id}_{hours}h"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        logger.info(f"Generating single miner chart for {device_id} ({hours}h)")

        self._configure_plot_style()

        # Get data
        minutes = hours * 60

        # Get config changes for this device
        config_changes = self.db.get_config_changes([device_id], minutes)

        # Use 5-minute buckets consistently
        bucket_minutes = 5
        # Allow enough buckets to support 24h MA (need 288 buckets minimum for 24h)
        # Cap at 576 buckets (48 hours at 5-min intervals) to keep chart reasonable
        buckets = min(576, minutes // 5)

        hashrate_trend = self.db.get_bucketed_hashrate_trend(device_id, minutes, buckets)
        temp_trend = self.db.get_bucketed_temp_trend(device_id, minutes, buckets)

        # Generate timestamps
        now = datetime.now()
        timestamps = [now - timedelta(minutes=minutes * (buckets - i - 1) / buckets) for i in range(buckets)]

        # Create figure with dual y-axis
        fig, ax1 = plt.subplots(figsize=self.figsize)
        ax2 = ax1.twinx()

        # Calculate consistent moving averages for hashrate (15-min and 24h)
        ma_short = self._calculate_moving_average(hashrate_trend, window=3)  # 15-min MA
        ma_long = self._calculate_moving_average(hashrate_trend, window=288)  # 24h MA
        ma_short_label = '15-min MA'
        ma_long_label = '24h MA'

        # Plot hashrate with both MAs
        ax1.plot(timestamps, ma_short, '-', color='#00FFFF', linewidth=2.5,
                label=ma_short_label, marker='o', markersize=2, alpha=0.9)
        ax1.plot(timestamps, ma_long, '-', color='#FFD700', linewidth=3,
                label=ma_long_label, alpha=0.95)

        # Smooth and plot temperature as dotted line
        temp_ma = self._calculate_moving_average(temp_trend, window=3)  # 15-min MA
        ax2.plot(timestamps, temp_ma, '--', color='#FF6B6B', linewidth=1.5,
                label='ASIC Temp (15-min MA)', alpha=0.7)

        # Add config change markers on the hashrate lines
        if config_changes:
            for change in config_changes:
                # Find closest timestamp index
                closest_idx = min(range(len(timestamps)),
                                 key=lambda i: abs((timestamps[i] - change['timestamp']).total_seconds()))

                # Plot markers on both MA lines where config changed (use line colors)
                if ma_short[closest_idx] is not None:
                    ax1.plot(timestamps[closest_idx], ma_short[closest_idx],
                           marker='D', color='#00FFFF', markersize=10,
                           markeredgecolor='white', markeredgewidth=2,
                           zorder=15)
                if ma_long[closest_idx] is not None:
                    ax1.plot(timestamps[closest_idx], ma_long[closest_idx],
                           marker='D', color='#FFD700', markersize=10,
                           markeredgecolor='white', markeredgewidth=2,
                           zorder=15)

        # Formatting
        ax1.set_xlabel('Time')
        ax1.set_ylabel('Hashrate (GH/s)', color='#00FFFF')
        ax2.set_ylabel('Temperature (°C)', color='#FF6B6B')

        # Format title based on timespan
        if hours >= 24 and hours % 24 == 0:
            title = f'{device_id} Performance ({hours//24}d)'
        else:
            title = f'{device_id} Performance ({hours}h)'
        ax1.set_title(title, fontweight='bold', pad=20)

        ax1.grid(True, alpha=0.3)

        # Legends
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.8)

        # Format x-axis based on timespan
        if hours <= 12:
            # Short: Show time only
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax1.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        elif hours <= 48:
            # 1-2 days: Show day and time
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            ax1.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        elif hours <= 168:
            # 3-7 days: Show day only
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax1.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        else:
            # 8+ days: Show day with more spacing
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax1.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        plt.xticks(rotation=45, ha='right')

        # Color y-axis labels
        ax1.tick_params(axis='y', labelcolor='#00FFFF')
        ax2.tick_params(axis='y', labelcolor='#FF6B6B')

        # Add padding to y-axes to reduce dramatic appearance of variance
        valid_short = [v for v in ma_short if v is not None]
        valid_long = [v for v in ma_long if v is not None]
        all_hr_values = valid_short + valid_long

        if all_hr_values:
            hr_min = min(all_hr_values)
            hr_max = max(all_hr_values)
            hr_range = hr_max - hr_min
            # Add 20% padding
            padding = hr_range * 0.2
            ax1.set_ylim(max(0, hr_min - padding), hr_max + padding)

        valid_temps = [v for v in temp_ma if v is not None]
        if valid_temps:
            temp_min = min(valid_temps)
            temp_max = max(valid_temps)
            temp_range = temp_max - temp_min
            # Add 20% padding
            padding = temp_range * 0.2
            ax2.set_ylim(max(30, temp_min - padding), min(90, temp_max + padding))

        # Add stats (reuse valid data from axis scaling)
        if valid_short and valid_long:
            current_short = ma_short[-1] if ma_short[-1] is not None else 0
            current_long = ma_long[-1] if ma_long[-1] is not None else 0
            avg_hr = np.mean(valid_long)
            current_temp = temp_ma[-1] if temp_ma[-1] is not None else 0
            avg_temp = np.mean(valid_temps) if valid_temps else 0

            stats_text = (f"Hashrate: {ma_short_label}={current_short:.1f} | {ma_long_label}={current_long:.1f} | Avg={avg_hr:.1f} GH/s | "
                         f"Temp: {current_temp:.1f}°C (avg: {avg_temp:.1f})")
            ax1.text(0.5, 0.98, stats_text, transform=ax1.transAxes,
                    fontsize=10, va='top', ha='center',
                    bbox=dict(boxstyle='round', facecolor='black', alpha=0.7))

        fig.tight_layout()

        # Save to bytes
        image_bytes = self._save_figure_to_bytes(fig)
        self.cache.set(cache_key, image_bytes)

        logger.info(f"Single miner chart generated ({len(image_bytes)} bytes)")
        return image_bytes
