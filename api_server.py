#!/usr/bin/env python3
"""Flask API server for ESP32 display and web dashboard."""

import json
import logging
import os
import re
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify, send_from_directory, request, Response
from flask_cors import CORS
import requests
from src.database import Database
from src.analyzer import Analyzer

# Read config to get database path and devices
import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Control safety limits (from config or defaults)
control_config = config.get('discord', {}).get('control', {})
CONTROL_LIMITS = {
    'min_frequency': control_config.get('min_frequency', 400),
    'max_frequency': control_config.get('max_frequency', 650),
    'min_voltage': control_config.get('min_voltage', 1000),
    'max_voltage': control_config.get('max_voltage', 1300),
    'min_fan_speed': control_config.get('min_fan_speed', 0),
    'max_fan_speed': control_config.get('max_fan_speed', 100),
}

# Initialize Flask app with static folder
# static_url_path='' makes static files accessible from root (e.g., /css/styles.css)
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)  # Allow cross-origin requests from ESP32


# =============================================================================
# Authentication (for Cloudflare Tunnel remote access)
# =============================================================================

def is_local_request():
    """Check if request is from local network (skip auth for ESP32/local devices)."""
    remote_ip = request.remote_addr or ''
    # Local/private IP ranges
    return (remote_ip.startswith('192.168.') or
            remote_ip.startswith('10.') or
            remote_ip.startswith('172.16.') or remote_ip.startswith('172.17.') or
            remote_ip.startswith('172.18.') or remote_ip.startswith('172.19.') or
            remote_ip.startswith('172.2') or remote_ip.startswith('172.30.') or
            remote_ip.startswith('172.31.') or
            remote_ip.startswith('127.') or
            remote_ip == '::1')


def check_auth(username, password):
    """Check if username/password match config credentials."""
    auth_config = config.get('auth', {})
    if not auth_config.get('enabled', False):
        return True  # Auth disabled, allow all
    return (username == auth_config.get('username') and
            password == auth_config.get('password'))


def requires_auth(f):
    """Decorator to require HTTP Basic Auth on routes (skips for local network)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth for local network requests (ESP32, local browser)
        if is_local_request():
            return f(*args, **kwargs)
        auth = request.authorization
        if not check_auth(auth.username if auth else None,
                          auth.password if auth else None):
            return Response('Unauthorized', 401,
                            {'WWW-Authenticate': 'Basic realm="Bitaxe Monitor"'})
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# Web Dashboard
# =============================================================================

@app.route('/')
@requires_auth
def serve_dashboard():
    """Serve the web dashboard."""
    return send_from_directory('static', 'index.html')

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

# Cache for expensive queries
_best_diff_cache = {'value': None, 'updated': None}
BEST_DIFF_CACHE_TTL = 300  # Refresh every 5 minutes


def get_cached_best_diff():
    """Get best difficulty with caching to avoid full table scans on every request."""
    now = datetime.now()
    if _best_diff_cache['updated'] and (now - _best_diff_cache['updated']).total_seconds() < BEST_DIFF_CACHE_TTL:
        return _best_diff_cache['value']

    try:
        device_ids = [d['name'] for d in devices]
        placeholders = ','.join('?' * len(device_ids))
        cursor = db.conn.cursor()
        cursor.execute(f"""
            SELECT MAX(best_diff)
            FROM performance_metrics
            WHERE device_id IN ({placeholders})
              AND best_diff IS NOT NULL
        """, device_ids)
        row = cursor.fetchone()
        _best_diff_cache['value'] = row[0] if row and row[0] is not None else None
        _best_diff_cache['updated'] = now
        logger.debug(f"Refreshed best_diff cache: {_best_diff_cache['value']}")
    except Exception as e:
        logger.error(f"Error refreshing best_diff cache: {e}")

    return _best_diff_cache['value']


@app.route('/swarm', methods=['GET'])
@requires_auth
def get_swarm_data():
    """Get current swarm status for ESP32 display and web dashboard.

    Lightweight endpoint - only fetches latest metrics per device.

    Returns JSON with:
    - total_hashrate: Total swarm hashrate in GH/s
    - total_power: Total power consumption in watts
    - avg_efficiency: Average efficiency in J/TH
    - active_count: Number of active miners
    - total_count: Total number of miners
    - miners: Array of individual miner stats
    """
    try:
        # Calculate swarm totals from current values
        total_hashrate = 0.0
        total_power = 0.0
        active_count = 0
        miners = []
        latest_timestamp = None

        for device in devices:
            device_id = device['name']

            # Direct lightweight query - just get latest metric
            latest = db.get_latest_metric(device_id)

            if not latest:
                # Miner is offline
                miners.append({
                    'name': device_id,
                    'group': device.get('group', 'default'),
                    'online': False,
                    'hashrate': 0,
                    'power': 0,
                    'efficiency': 0,
                    'asic_temp': 0,
                    'vreg_temp': 0,
                    'frequency': 0,
                    'core_voltage': 0,
                    'input_voltage': 0,
                    'fan_speed': 0,
                    'fan_rpm': 0,
                    'uptime_hours': 0
                })
                continue

            # Add to totals
            total_hashrate += latest['hashrate']
            total_power += latest['power']
            active_count += 1

            # Capture timestamp from first online miner (for ESP32)
            if latest_timestamp is None and latest.get('timestamp'):
                try:
                    dt = datetime.fromisoformat(latest['timestamp'])
                    latest_timestamp = str(int(dt.timestamp()))
                except (ValueError, TypeError):
                    pass

            # Input voltage - convert from mV to V if needed
            input_voltage = latest['voltage']
            if input_voltage > 100:  # Stored in mV
                input_voltage = input_voltage / 1000.0

            # Individual miner data
            miners.append({
                'name': device_id,
                'group': device.get('group', 'default'),
                'online': True,
                'hashrate': round(latest['hashrate'], 2),  # GH/s
                'power': round(latest['power'], 1),  # W
                'efficiency': round(latest['efficiency_jth'], 1),  # J/TH
                'asic_temp': round(latest['asic_temp'], 1),  # °C
                'vreg_temp': round(latest['vreg_temp'], 1),  # °C
                'frequency': int(latest['frequency']),  # MHz
                'core_voltage': int(latest['core_voltage']),  # mV
                'input_voltage': round(input_voltage, 2),  # V
                'fan_speed': int(latest['fan_speed']),  # %
                'fan_rpm': int(latest['fan_rpm']),  # RPM
                'uptime_hours': round(latest['uptime'] / 3600, 1)  # hours
            })

        # Calculate average efficiency
        avg_efficiency = (total_power / (total_hashrate / 1000.0)) if total_hashrate > 0 else 0

        response = {
            'total_hashrate': round(total_hashrate, 2),  # GH/s
            'total_power': round(total_power, 1),  # W
            'avg_efficiency': round(avg_efficiency, 1),  # J/TH
            'active_count': active_count,
            'total_count': len(devices),
            'best_diff': get_cached_best_diff(),
            'miners': miners,
            'timestamp': latest_timestamp  # Unix timestamp from actual data
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

    minutes = request.args.get('minutes', 120, type=int)
    num_buckets = request.args.get('buckets', 60, type=int)

    try:
        # Get max timestamp as reference (handles stale data)
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT MAX(timestamp) FROM performance_metrics WHERE device_id = ?",
            (device_id,)
        )
        max_row = cursor.fetchone()

        if not max_row or not max_row[0]:
            return jsonify({'labels': [], 'data': []})

        end_time = datetime.fromisoformat(max_row[0])
        start_time = end_time - timedelta(minutes=minutes)
        bucket_size_minutes = minutes / num_buckets

        cursor.execute("""
            SELECT hashrate, timestamp
            FROM performance_metrics
            WHERE device_id = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (device_id, start_time))

        rows = cursor.fetchall()
        if not rows:
            return jsonify({'labels': [], 'data': []})

        # Group samples into buckets and average
        buckets = [[] for _ in range(num_buckets)]

        for hashrate, timestamp_str in rows:
            timestamp = datetime.fromisoformat(timestamp_str)
            elapsed_minutes = (timestamp - start_time).total_seconds() / 60
            bucket_idx = int(elapsed_minutes / bucket_size_minutes)
            if bucket_idx >= num_buckets:
                bucket_idx = num_buckets - 1
            if bucket_idx < 0:
                bucket_idx = 0
            buckets[bucket_idx].append(hashrate)

        # Calculate average for each bucket and generate labels
        data = []
        labels = []
        for i, bucket in enumerate(buckets):
            bucket_time = start_time + timedelta(minutes=i * bucket_size_minutes)
            labels.append(bucket_time.strftime('%H:%M'))

            if bucket:
                data.append(round(sum(bucket) / len(bucket), 1))
            elif data:
                data.append(data[-1])  # Carry forward last value
            else:
                data.append(None)

        return jsonify({'labels': labels, 'data': data})
    except Exception as e:
        logger.error(f"Error getting hashrate trend for {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/swarm/hashrate-trend', methods=['GET'])
def get_swarm_hashrate_trend():
    """Get combined swarm hashrate trend for visualization."""
    from datetime import timedelta
    from flask import request

    minutes = request.args.get('minutes', 120, type=int)  # Default 2 hours
    num_buckets = request.args.get('buckets', 60, type=int)  # Default 60 points

    try:
        # Get max timestamp as reference (handles stale data)
        cursor = db.conn.cursor()
        cursor.execute("SELECT MAX(timestamp) FROM performance_metrics")
        max_row = cursor.fetchone()

        if not max_row or not max_row[0]:
            return jsonify({'labels': [], 'data': []})

        end_time = datetime.fromisoformat(max_row[0])
        start_time = end_time - timedelta(minutes=minutes)
        bucket_size_minutes = minutes / num_buckets

        # Get all hashrates in the time range
        device_ids = [d['name'] for d in devices]
        placeholders = ','.join('?' * len(device_ids))

        cursor.execute(f"""
            SELECT hashrate, timestamp, device_id
            FROM performance_metrics
            WHERE device_id IN ({placeholders})
              AND timestamp >= ?
            ORDER BY timestamp ASC
        """, device_ids + [start_time])

        rows = cursor.fetchall()
        if not rows:
            return jsonify({'labels': [], 'data': []})

        # Group samples into buckets by time, then sum across devices
        # Each bucket: {device_id: [hashrates]}
        buckets = [{} for _ in range(num_buckets)]

        for hashrate, timestamp_str, device_id in rows:
            ts = datetime.fromisoformat(timestamp_str)
            elapsed_minutes = (ts - start_time).total_seconds() / 60
            bucket_idx = int(elapsed_minutes / bucket_size_minutes)
            if bucket_idx >= num_buckets:
                bucket_idx = num_buckets - 1
            if bucket_idx < 0:
                bucket_idx = 0

            if device_id not in buckets[bucket_idx]:
                buckets[bucket_idx][device_id] = []
            buckets[bucket_idx][device_id].append(hashrate)

        # Calculate swarm total for each bucket (sum of device averages)
        data = []
        labels = []
        for i, bucket in enumerate(buckets):
            bucket_time = start_time + timedelta(minutes=i * bucket_size_minutes)
            labels.append(bucket_time.strftime('%H:%M'))

            if bucket:
                # Sum the average hashrate of each device in this bucket
                total = sum(
                    sum(hrs) / len(hrs) for hrs in bucket.values()
                )
                data.append(round(total, 1))
            elif data:
                data.append(data[-1])  # Carry forward last value
            else:
                data.append(None)

        return jsonify({'labels': labels, 'data': data})
    except Exception as e:
        logger.error(f"Error getting swarm hashrate trend: {e}")
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
    try:
        results = analyzer.get_multi_timeframe_variance(device_id)
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


# =============================================================================
# Device Control Endpoints
# =============================================================================

def get_device_ip(device_id: str) -> str | None:
    """Get IP address for a device by its name."""
    for device in devices:
        if device['name'] == device_id:
            return device.get('ip')
    return None


@app.route('/api/control/limits', methods=['GET'])
@requires_auth
def get_control_limits():
    """Get safety limits for control sliders."""
    return jsonify(CONTROL_LIMITS)



def version_supports_min_fan(version: str) -> bool:
    """Check if firmware version supports minFanSpeed parameter.

    Standard Bitaxe AxeOS v2.10.0+ supports minFanSpeed.
    NerdQAxe++ firmware (v1.x.x) does not support it.
    """
    if not version:
        return False
    # Strip leading 'v' if present
    v = version.lstrip('v').lstrip('V')
    # NerdQAxe++ uses 1.x.x versioning - doesn't support minFanSpeed
    if v.startswith('1.'):
        return False
    # Standard Bitaxe 2.10.0+ supports it
    try:
        parts = v.split('.')
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        if major >= 2 and minor >= 10:
            return True
    except (ValueError, IndexError):
        pass
    return False

@app.route('/api/control/<device_id>/settings', methods=['GET'])
@requires_auth
def get_device_settings(device_id):
    """Get current device settings directly from the Bitaxe."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    try:
        response = requests.get(f"http://{ip}/api/system/info", timeout=5)
        response.raise_for_status()
        data = response.json()

        version = data.get('version', '')
        return jsonify({
            'frequency': data.get('frequency', 0),
            'core_voltage': data.get('coreVoltage', 0),
            'fan_speed': data.get('fanspeed', 0),
            'autofan': data.get('autofanspeed', 1) == 1,  # True if auto mode
            'fan_rpm': data.get('fanrpm', 0),
            'temp_target': data.get('temptarget', 65),  # Auto fan target temp
            'min_fan_speed': data.get('minFanSpeed', 0),  # Auto fan min speed
            'version': version,  # Firmware version
            'supports_min_fan': version_supports_min_fan(version),  # Capability flag
        })
    except requests.RequestException as e:
        logger.error(f"Failed to get settings from {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device_id>/frequency', methods=['POST'])
@requires_auth
def set_device_frequency(device_id):
    """Set device frequency (MHz)."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json()
    frequency = data.get('frequency')

    if frequency is None:
        return jsonify({'error': 'frequency is required'}), 400

    frequency = int(frequency)
    if not CONTROL_LIMITS['min_frequency'] <= frequency <= CONTROL_LIMITS['max_frequency']:
        return jsonify({
            'error': f"Frequency must be between {CONTROL_LIMITS['min_frequency']}-{CONTROL_LIMITS['max_frequency']} MHz"
        }), 400

    try:
        response = requests.patch(
            f"http://{ip}/api/system",
            json={'frequency': frequency},
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"Set {device_id} frequency to {frequency} MHz")
        return jsonify({'success': True, 'frequency': frequency})
    except requests.RequestException as e:
        logger.error(f"Failed to set frequency on {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device_id>/voltage', methods=['POST'])
@requires_auth
def set_device_voltage(device_id):
    """Set device core voltage (mV)."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json()
    voltage = data.get('voltage')

    if voltage is None:
        return jsonify({'error': 'voltage is required'}), 400

    voltage = int(voltage)
    if not CONTROL_LIMITS['min_voltage'] <= voltage <= CONTROL_LIMITS['max_voltage']:
        return jsonify({
            'error': f"Voltage must be between {CONTROL_LIMITS['min_voltage']}-{CONTROL_LIMITS['max_voltage']} mV"
        }), 400

    try:
        response = requests.patch(
            f"http://{ip}/api/system",
            json={'coreVoltage': voltage},
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"Set {device_id} voltage to {voltage} mV")
        return jsonify({'success': True, 'voltage': voltage})
    except requests.RequestException as e:
        logger.error(f"Failed to set voltage on {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device_id>/fan', methods=['POST'])
@requires_auth
def set_device_fan(device_id):
    """Set device fan speed (%) - disables auto mode."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json()
    fan_speed = data.get('fan_speed')

    if fan_speed is None:
        return jsonify({'error': 'fan_speed is required'}), 400

    fan_speed = int(fan_speed)
    if not CONTROL_LIMITS['min_fan_speed'] <= fan_speed <= CONTROL_LIMITS['max_fan_speed']:
        return jsonify({
            'error': f"Fan speed must be between {CONTROL_LIMITS['min_fan_speed']}-{CONTROL_LIMITS['max_fan_speed']}%"
        }), 400

    try:
        response = requests.patch(
            f"http://{ip}/api/system",
            json={'autofanspeed': 0, 'manualFanSpeed': fan_speed},
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"Set {device_id} fan speed to {fan_speed}%")
        return jsonify({'success': True, 'fan_speed': fan_speed})
    except requests.RequestException as e:
        logger.error(f"Failed to set fan on {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device_id>/autofan', methods=['POST'])
@requires_auth
def enable_device_autofan(device_id):
    """Enable auto fan mode with optional target temp and min fan speed."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json() or {}

    # Check device firmware version to determine parameter format
    is_nerdqaxe = False
    try:
        info_response = requests.get(f"http://{ip}/api/system/info", timeout=5)
        if info_response.ok:
            version = info_response.json().get('version', '')
            # NerdQAxe++ uses v1.x versioning and different parameters
            is_nerdqaxe = not version_supports_min_fan(version)
    except requests.RequestException:
        pass  # If we can't check, assume standard device

    if is_nerdqaxe:
        # NerdQAxe++ uses autofanspeed: 2 and pidTargetTemp
        payload = {'autofanspeed': 2}
        if 'temp_target' in data:
            temp_target = int(data['temp_target'])
            if 0 <= temp_target <= 100:
                payload['pidTargetTemp'] = temp_target
    else:
        # Standard Bitaxe uses autofanspeed: 1, temptarget, and minFanSpeed
        payload = {'autofanspeed': 1}
        if 'temp_target' in data:
            temp_target = int(data['temp_target'])
            if 0 <= temp_target <= 100:
                payload['temptarget'] = temp_target
        if 'min_fan_speed' in data:
            min_fan = int(data['min_fan_speed'])
            if 0 <= min_fan <= 100:
                payload['minFanSpeed'] = min_fan

    try:
        response = requests.patch(
            f"http://{ip}/api/system",
            json=payload,
            timeout=5
        )
        response.raise_for_status()
        logger.info(f"Enabled auto fan on {device_id} with settings: {payload}")
        return jsonify({'success': True, **payload})
    except requests.RequestException as e:
        logger.error(f"Failed to enable auto fan on {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device_id>/restart', methods=['POST'])
@requires_auth
def restart_device(device_id):
    """Restart the device."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    try:
        response = requests.post(
            f"http://{ip}/api/system/restart",
            timeout=5
        )
        response.raise_for_status()
        logger.warning(f"Restarted {device_id}")
        return jsonify({'success': True})
    except requests.RequestException as e:
        logger.error(f"Failed to restart {device_id}: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Device Profiles (Presets)
# =============================================================================

PROFILES_PATH = os.path.join('data', 'profiles.json')
PROFILE_NAME_RE = re.compile(r'^[a-zA-Z0-9 \-]{1,30}$')


def _load_profiles():
    """Load all profiles from disk."""
    if not os.path.exists(PROFILES_PATH):
        return {}
    with open(PROFILES_PATH, 'r') as fh:
        return json.load(fh)


def _save_profiles(profiles):
    """Write profiles dict to disk."""
    os.makedirs(os.path.dirname(PROFILES_PATH), exist_ok=True)
    with open(PROFILES_PATH, 'w') as fh:
        json.dump(profiles, fh, indent=2)


def _validate_profile_settings(data):
    """Validate profile settings against CONTROL_LIMITS. Returns (cleaned, error)."""
    required = ['frequency', 'core_voltage', 'fan_mode']
    for key in required:
        if key not in data:
            return None, f'{key} is required'

    frequency = int(data['frequency'])
    core_voltage = int(data['core_voltage'])
    fan_mode = data['fan_mode']

    if not CONTROL_LIMITS['min_frequency'] <= frequency <= CONTROL_LIMITS['max_frequency']:
        return None, f"Frequency must be between {CONTROL_LIMITS['min_frequency']}-{CONTROL_LIMITS['max_frequency']} MHz"
    if not CONTROL_LIMITS['min_voltage'] <= core_voltage <= CONTROL_LIMITS['max_voltage']:
        return None, f"Voltage must be between {CONTROL_LIMITS['min_voltage']}-{CONTROL_LIMITS['max_voltage']} mV"
    if fan_mode not in ('auto', 'manual'):
        return None, 'fan_mode must be "auto" or "manual"'

    cleaned = {
        'frequency': frequency,
        'core_voltage': core_voltage,
        'fan_mode': fan_mode,
        'fan_speed': int(data.get('fan_speed', 100)),
        'temp_target': int(data.get('temp_target', 65)),
        'min_fan_speed': int(data.get('min_fan_speed', 0)),
    }
    return cleaned, None


@app.route('/api/profiles/<device_id>', methods=['GET'])
@requires_auth
def get_profiles(device_id):
    """Return saved profiles for a device."""
    profiles = _load_profiles()
    return jsonify(profiles.get(device_id, []))


@app.route('/api/profiles/<device_id>', methods=['POST'])
@requires_auth
def save_profile(device_id):
    """Save or overwrite a profile for a device."""
    if not get_device_ip(device_id):
        return jsonify({'error': 'Device not found'}), 404

    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name or not PROFILE_NAME_RE.match(name):
        return jsonify({'error': 'Invalid profile name (alphanumeric, spaces, dashes, max 30 chars)'}), 400

    cleaned, error = _validate_profile_settings(data)
    if error:
        return jsonify({'error': error}), 400

    cleaned['name'] = name
    profiles = _load_profiles()
    device_profiles = profiles.get(device_id, [])

    # Overwrite if same name exists
    device_profiles = [p for p in device_profiles if p['name'] != name]
    device_profiles.append(cleaned)
    profiles[device_id] = device_profiles
    _save_profiles(profiles)

    logger.info(f"Saved profile '{name}' for {device_id}")
    return jsonify({'success': True, 'profile': cleaned})


@app.route('/api/profiles/<device_id>/<profile_name>', methods=['DELETE'])
@requires_auth
def delete_profile(device_id, profile_name):
    """Delete a saved profile."""
    profiles = _load_profiles()
    device_profiles = profiles.get(device_id, [])
    before = len(device_profiles)
    device_profiles = [p for p in device_profiles if p['name'] != profile_name]

    if len(device_profiles) == before:
        return jsonify({'error': 'Profile not found'}), 404

    profiles[device_id] = device_profiles
    _save_profiles(profiles)
    logger.info(f"Deleted profile '{profile_name}' from {device_id}")
    return jsonify({'success': True})


@app.route('/api/profiles/<device_id>/<profile_name>/apply', methods=['POST'])
@requires_auth
def apply_profile(device_id, profile_name):
    """Apply a saved profile to a device."""
    ip = get_device_ip(device_id)
    if not ip:
        return jsonify({'error': 'Device not found'}), 404

    profiles = _load_profiles()
    device_profiles = profiles.get(device_id, [])
    profile = next((p for p in device_profiles if p['name'] == profile_name), None)
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404

    errors = []

    # 1. Apply frequency + voltage together
    try:
        response = requests.patch(
            f"http://{ip}/api/system",
            json={'frequency': profile['frequency'], 'coreVoltage': profile['core_voltage']},
            timeout=5
        )
        response.raise_for_status()
    except requests.RequestException as e:
        errors.append(f"frequency/voltage: {e}")

    # 2. Apply fan settings
    try:
        if profile['fan_mode'] == 'auto':
            # Check device type for autofan parameter format
            is_nerdqaxe = False
            try:
                info_response = requests.get(f"http://{ip}/api/system/info", timeout=5)
                if info_response.ok:
                    version = info_response.json().get('version', '')
                    is_nerdqaxe = not version_supports_min_fan(version)
            except requests.RequestException:
                pass

            if is_nerdqaxe:
                payload = {'autofanspeed': 2, 'pidTargetTemp': profile['temp_target']}
            else:
                payload = {
                    'autofanspeed': 1,
                    'temptarget': profile['temp_target'],
                    'minFanSpeed': profile['min_fan_speed'],
                }
        else:
            payload = {'autofanspeed': 0, 'manualFanSpeed': profile['fan_speed']}

        response = requests.patch(f"http://{ip}/api/system", json=payload, timeout=5)
        response.raise_for_status()
    except requests.RequestException as e:
        errors.append(f"fan: {e}")

    if errors:
        logger.error(f"Errors applying profile '{profile_name}' to {device_id}: {errors}")
        return jsonify({'error': f"Partial failure: {'; '.join(errors)}"}), 500

    logger.info(f"Applied profile '{profile_name}' to {device_id}")
    return jsonify({'success': True, 'profile': profile})


if __name__ == '__main__':
    import signal
    import sys
    import atexit

    # Register cleanup at exit (safer than signal handler)
    atexit.register(lambda: db.close())

    def signal_handler(_sig, _frame):
        logger.info("Shutting down API server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"Starting API server for {len(devices)} device(s)")
    logger.info(f"Database: {db_path}")
    logger.info("Endpoints:")
    logger.info("  GET /        - Web Dashboard")
    logger.info("  GET /swarm   - Swarm status (JSON)")
    logger.info("  GET /health  - Health check")
    logger.info("")
    logger.info("Web Dashboard: http://localhost:5001")

    # Run on all interfaces so ESP32 can connect
    # Using port 5001 (port 5000 conflicts with macOS AirPlay Receiver)
    # threaded=True allows handling multiple requests and cleaner shutdown
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
