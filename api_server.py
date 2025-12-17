#!/usr/bin/env python3
"""Flask API server for ESP32 display to fetch swarm data."""

import logging
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
from src.database import Database
from src.analyzer import Analyzer

# Read config to get database path and devices
import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Allow cross-origin requests from ESP32

# Initialize database and analyzer
db_path = config.get('logging', {}).get('database_path', './data/metrics.db')
db = Database(db_path)
analyzer = Analyzer(db)
devices = [d for d in config.get('devices', []) if d.get('enabled', True)]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.route('/swarm', methods=['GET'])
def get_swarm_data():
    """Get current swarm status for ESP32 display.

    Returns JSON with:
    - total_hashrate: Total swarm hashrate in GH/s
    - total_power: Total power consumption in watts
    - avg_efficiency: Average efficiency in J/TH
    - active_count: Number of active miners
    - total_count: Total number of miners
    - miners: Array of individual miner stats
    """
    try:
        # Get summary data (same as Discord bot)
        summary = analyzer.get_all_devices_summary()

        # Calculate swarm totals from current values
        total_hashrate = 0.0
        total_power = 0.0
        active_count = 0
        miners = []

        for device in devices:
            device_id = device['name']
            data = summary.get(device_id)

            if not data or not data['latest']:
                # Miner is offline
                miners.append({
                    'name': device_id,
                    'online': False,
                    'hashrate': 0,
                    'power': 0,
                    'efficiency': 0,
                    'asic_temp': 0,
                    'vreg_temp': 0,
                    'frequency': 0,
                    'uptime_hours': 0
                })
                continue

            latest = data['latest']

            # Add to totals
            total_hashrate += latest['hashrate']
            total_power += latest['power']
            active_count += 1

            # Individual miner data
            miners.append({
                'name': device_id,
                'online': True,
                'hashrate': round(latest['hashrate'], 2),  # GH/s
                'power': round(latest['power'], 1),  # W
                'efficiency': round(latest['efficiency_jth'], 1),  # J/TH
                'asic_temp': round(latest['asic_temp'], 1),  # °C
                'vreg_temp': round(latest['vreg_temp'], 1),  # °C
                'frequency': int(latest['frequency']),  # MHz
                'uptime_hours': round(latest['uptime'] / 3600, 1)  # hours
            })

        # Calculate average efficiency
        avg_efficiency = (total_power / (total_hashrate / 1000.0)) if total_hashrate > 0 else 0

        # Use simple Unix timestamp to avoid parsing issues on ESP32
        import time

        response = {
            'total_hashrate': round(total_hashrate, 2),  # GH/s
            'total_power': round(total_power, 1),  # W
            'avg_efficiency': round(avg_efficiency, 1),  # J/TH
            'active_count': active_count,
            'total_count': len(devices),
            'miners': miners,
            'timestamp': str(int(time.time()))  # Simple unix timestamp as string
        }

        logger.info(f"Swarm data requested: {active_count}/{len(devices)} active, {total_hashrate:.2f} GH/s")
        return jsonify(response)

    except Exception as e:
        logger.error(f"Error generating swarm data: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({'status': 'ok'})


# =============================================================================
# Dashboard API Endpoints
# =============================================================================

@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get list of configured devices."""
    return jsonify({
        'devices': devices
    })


@app.route('/api/metrics/latest/<device_id>', methods=['GET'])
def get_latest_metric(device_id):
    """Get latest metrics for a specific device."""
    try:
        latest = db.get_latest_metric(device_id)
        if not latest:
            return jsonify({'error': 'No data found'}), 404
        return jsonify(latest)
    except Exception as e:
        logger.error(f"Error getting latest metric for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/uptime-avg/<device_id>/<int:uptime_seconds>', methods=['GET'])
def get_uptime_averages(device_id, uptime_seconds):
    """Get average hashrate and efficiency during current uptime period."""
    from datetime import datetime, timedelta

    try:
        reboot_time = datetime.now() - timedelta(seconds=uptime_seconds)
        cursor = db.conn.cursor()

        # Get average hashrate
        cursor.execute("""
            SELECT AVG(hashrate) as avg_hashrate
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
        """, (device_id, reboot_time))
        row = cursor.fetchone()
        avg_hashrate = round(row[0], 1) if row and row[0] else None

        # Get average efficiency
        cursor.execute("""
            SELECT AVG(efficiency_jth) as avg_efficiency
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
              AND efficiency_jth IS NOT NULL
        """, (device_id, reboot_time))
        row = cursor.fetchone()
        avg_efficiency = round(row[0], 1) if row and row[0] else None

        return jsonify({
            'avg_hashrate': avg_hashrate,
            'avg_efficiency': avg_efficiency
        })
    except Exception as e:
        logger.error(f"Error getting uptime averages for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/session-stats/<device_id>/<metric>/<int:uptime_seconds>', methods=['GET'])
def get_session_stats(device_id, metric, uptime_seconds):
    """Get statistics for a metric during the current uptime session."""
    from datetime import datetime, timedelta

    # Whitelist allowed metrics to prevent SQL injection
    allowed_metrics = ['power', 'current', 'hashrate', 'asic_temp', 'vreg_temp']
    if metric not in allowed_metrics:
        return jsonify({'error': f'Invalid metric. Allowed: {allowed_metrics}'}), 400

    try:
        reboot_time = datetime.now() - timedelta(seconds=uptime_seconds)
        cursor = db.conn.cursor()

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
            return jsonify({
                'min': round(row[0], 2),
                'max': round(row[1], 2),
                'avg': round(row[2], 2),
                'samples': row[3]
            })
        return jsonify(None)
    except Exception as e:
        logger.error(f"Error getting session stats for {device_id}/{metric}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/hashrate-trend/<device_id>', methods=['GET'])
def get_hashrate_trend(device_id):
    """Get bucketed hashrate trend for visualization."""
    from datetime import datetime, timedelta
    from flask import request

    minutes = request.args.get('minutes', 60, type=int)
    num_buckets = request.args.get('buckets', 30, type=int)

    try:
        lookback_time = datetime.now() - timedelta(minutes=minutes)
        bucket_size_minutes = minutes / num_buckets

        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT hashrate, timestamp
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (device_id, lookback_time))

        rows = cursor.fetchall()
        if not rows:
            return jsonify([])

        # Group samples into buckets and average
        buckets = [[] for _ in range(num_buckets)]
        start_time = datetime.fromisoformat(rows[0][1])

        for hashrate, timestamp_str in rows:
            timestamp = datetime.fromisoformat(timestamp_str)
            elapsed_minutes = (timestamp - start_time).total_seconds() / 60
            bucket_idx = int(elapsed_minutes / bucket_size_minutes)
            if bucket_idx >= num_buckets:
                bucket_idx = num_buckets - 1
            buckets[bucket_idx].append(hashrate)

        # Calculate average for each bucket
        averages = []
        for bucket in buckets:
            if bucket:
                averages.append(sum(bucket) / len(bucket))
            elif averages:
                averages.append(averages[-1])

        return jsonify(averages)
    except Exception as e:
        logger.error(f"Error getting hashrate trend for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/total-uptime/<device_id>', methods=['GET'])
def get_total_uptime(device_id):
    """Calculate total cumulative uptime vs current session uptime."""
    try:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT uptime, timestamp
            FROM performance_metrics
            WHERE device_id = ?
            ORDER BY timestamp ASC
        """, (device_id,))

        rows = cursor.fetchall()
        if not rows:
            return jsonify(None)

        current_uptime = rows[-1][0]
        MAX_RESTART_UPTIME = 3600  # 1 hour

        total_uptime = 0
        prev_uptime = 0
        session_start_idx = 0

        for i, (uptime, timestamp) in enumerate(rows):
            if uptime < prev_uptime and uptime < MAX_RESTART_UPTIME:
                session_uptimes = [rows[j][0] for j in range(session_start_idx, i)]
                if session_uptimes:
                    total_uptime += max(session_uptimes)
                session_start_idx = i
            prev_uptime = uptime

        total_uptime += current_uptime

        return jsonify({
            'session_hours': current_uptime / 3600,
            'total_hours': total_uptime / 3600
        })
    except Exception as e:
        logger.error(f"Error getting total uptime for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/highest-difficulty/<device_id>', methods=['GET'])
def get_highest_difficulty(device_id):
    """Get the highest difficulty ever achieved by this device."""
    try:
        cursor = db.conn.cursor()
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
            return jsonify({
                'all_time': row[0],
                'session': row[1] if row[1] else row[0]
            })
        return jsonify(None)
    except Exception as e:
        logger.error(f"Error getting highest difficulty for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/metrics/variance/<device_id>', methods=['GET'])
def get_multi_timeframe_variance(device_id):
    """Get variance percentages for multiple timeframes."""
    from datetime import datetime, timedelta

    timeframes = {
        '1h': (60, 30),
        '4h': (240, 48),
        '8h': (480, 48),
        '24h': (1440, 24),
        '3d': (4320, 36)
    }

    results = {}

    try:
        for label, (minutes, num_buckets) in timeframes.items():
            lookback_time = datetime.now() - timedelta(minutes=minutes)
            bucket_size_minutes = minutes / num_buckets

            cursor = db.conn.cursor()
            cursor.execute("""
                SELECT hashrate, timestamp
                FROM performance_metrics
                WHERE device_id = ?
                  AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (device_id, lookback_time))

            rows = cursor.fetchall()
            if not rows:
                results[label] = None
                continue

            # Group into buckets
            buckets = [[] for _ in range(num_buckets)]
            start_time = datetime.fromisoformat(rows[0][1])

            for hashrate, timestamp_str in rows:
                timestamp = datetime.fromisoformat(timestamp_str)
                elapsed_minutes = (timestamp - start_time).total_seconds() / 60
                bucket_idx = int(elapsed_minutes / bucket_size_minutes)
                if bucket_idx >= num_buckets:
                    bucket_idx = num_buckets - 1
                buckets[bucket_idx].append(hashrate)

            # Calculate averages
            hashrates = []
            for bucket in buckets:
                if bucket:
                    hashrates.append(sum(bucket) / len(bucket))
                elif hashrates:
                    hashrates.append(hashrates[-1])

            if hashrates and len(hashrates) > 1:
                min_hr = min(hashrates)
                max_hr = max(hashrates)
                avg_hr = sum(hashrates) / len(hashrates)

                sorted_hrs = sorted(hashrates)
                n = len(sorted_hrs)
                if n % 2 == 0:
                    median_hr = (sorted_hrs[n//2 - 1] + sorted_hrs[n//2]) / 2
                else:
                    median_hr = sorted_hrs[n//2]

                variance_pct = ((max_hr - min_hr) / avg_hr * 100) if avg_hr > 0 else 0

                results[label] = {
                    'variance': round(variance_pct, 1),
                    'mean': round(avg_hr, 1),
                    'median': round(median_hr, 1),
                    'samples': len(hashrates)
                }
            else:
                results[label] = None

        return jsonify(results)
    except Exception as e:
        logger.error(f"Error getting variance for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/device-info/<device_id>', methods=['GET'])
def get_device_info(device_id):
    """Get device info from devices table."""
    try:
        cursor = db.conn.cursor()
        cursor.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
        row = cursor.fetchone()

        if row:
            return jsonify(dict(row))
        return jsonify(None)
    except Exception as e:
        logger.error(f"Error getting device info for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/summary', methods=['GET'])
def get_summary():
    """Get summary for all devices."""
    try:
        summary = analyzer.get_all_devices_summary()
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import signal
    import sys

    def signal_handler(sig, frame):
        logger.info("Shutting down API server...")
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"Starting API server for {len(devices)} device(s)")
    logger.info(f"Database: {db_path}")
    logger.info("API endpoints:")
    logger.info("  GET /swarm - Swarm status for ESP32")
    logger.info("  GET /health - Health check")

    # Run on all interfaces so ESP32 can connect
    # Using port 5001 (port 5000 conflicts with macOS AirPlay Receiver)
    # threaded=True allows handling multiple requests and cleaner shutdown
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
