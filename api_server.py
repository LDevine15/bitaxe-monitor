#!/usr/bin/env python3
"""Flask API server for ESP32 display to fetch swarm data."""

import logging
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

        response = {
            'total_hashrate': round(total_hashrate, 2),  # GH/s
            'total_power': round(total_power, 1),  # W
            'avg_efficiency': round(avg_efficiency, 1),  # J/TH
            'active_count': active_count,
            'total_count': len(devices),
            'miners': miners,
            'timestamp': data['latest']['timestamp'] if data and data.get('latest') else None
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


if __name__ == '__main__':
    logger.info(f"Starting API server for {len(devices)} device(s)")
    logger.info(f"Database: {db_path}")
    logger.info("API endpoints:")
    logger.info("  GET /swarm - Swarm status for ESP32")
    logger.info("  GET /health - Health check")

    # Run on all interfaces so ESP32 can connect
    # Using port 5001 (port 5000 conflicts with macOS AirPlay Receiver)
    app.run(host='0.0.0.0', port=5001, debug=False)
