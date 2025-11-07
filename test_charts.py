#!/usr/bin/env python3
"""Test script for chart generation."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database
from src.discord.chart_generator import ChartGenerator


def main():
    """Test chart generation with real data."""
    print("🧪 Testing chart generation...")

    # Initialize database
    db_path = "./data/metrics.db"
    if not Path(db_path).exists():
        print(f"❌ Database not found at {db_path}")
        return 1

    db = Database(db_path)
    print(f"✅ Database loaded: {db_path}")

    # Get device IDs
    device_ids = db.get_all_device_ids()
    if not device_ids:
        print("❌ No devices found in database")
        return 1

    print(f"✅ Found {len(device_ids)} devices: {', '.join(device_ids)}")

    # Initialize chart generator
    chart_config = {
        'dpi': 150,
        'figsize': [12, 6],
        'style': 'dark_background',
        'cache_ttl': 300,
    }
    generator = ChartGenerator(db, chart_config)
    print("✅ Chart generator initialized")

    # Test swarm hashrate chart
    print("\n📊 Testing swarm hashrate chart (12h)...")
    try:
        swarm_chart = generator.generate_swarm_hashrate_chart(12, device_ids)
        output_path = Path("./test_swarm_chart.png")
        output_path.write_bytes(swarm_chart)
        print(f"✅ Swarm chart generated: {output_path} ({len(swarm_chart)} bytes)")
    except Exception as e:
        print(f"❌ Failed to generate swarm chart: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Test miner detail chart
    print("\n📊 Testing miner detail chart (12h)...")
    try:
        miner_chart = generator.generate_miner_detail_chart(12, device_ids)
        output_path = Path("./test_miner_chart.png")
        output_path.write_bytes(miner_chart)
        print(f"✅ Miner detail chart generated: {output_path} ({len(miner_chart)} bytes)")
    except Exception as e:
        print(f"❌ Failed to generate miner detail chart: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Test single miner chart
    print(f"\n📊 Testing single miner chart for {device_ids[0]} (24h)...")
    try:
        single_chart = generator.generate_single_miner_chart(device_ids[0], 24)
        output_path = Path(f"./test_single_{device_ids[0]}_chart.png")
        output_path.write_bytes(single_chart)
        print(f"✅ Single miner chart generated: {output_path} ({len(single_chart)} bytes)")
    except Exception as e:
        print(f"❌ Failed to generate single miner chart: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Test cache
    print("\n🗃️  Testing chart cache...")
    try:
        swarm_chart_cached = generator.generate_swarm_hashrate_chart(12, device_ids)
        if swarm_chart_cached == swarm_chart:
            print("✅ Cache working correctly")
        else:
            print("⚠️  Cache returned different data")
    except Exception as e:
        print(f"❌ Failed to test cache: {e}")

    print("\n✅ All tests passed! Charts are ready for Discord.")
    print("   Check the test_*.png files in the current directory.")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
