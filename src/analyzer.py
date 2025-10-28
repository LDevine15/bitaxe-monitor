"""Analysis tools for Bitaxe performance data."""

import sqlite3
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .database import Database


class Analyzer:
    """Performance analysis tools for Bitaxe miners."""

    def __init__(self, db: Database):
        """Initialize analyzer.

        Args:
            db: Database instance
        """
        self.db = db

    def get_config_summary(
        self,
        device_id: str,
        hours: Optional[int] = None
    ) -> List[Dict]:
        """Get comprehensive performance summary by configuration.

        Includes all bottlenecking metrics: temps, voltage sag, power draw.

        Args:
            device_id: Device identifier
            hours: Optional time window in hours (None = all data)

        Returns:
            List of config summaries with aggregate metrics
        """
        time_filter = ""
        params = [device_id]

        if hours:
            cutoff = datetime.now() - timedelta(hours=hours)
            time_filter = "AND pm.timestamp > ?"
            params.append(cutoff.isoformat())

        query = f"""
            SELECT
                cc.id as config_id,
                cc.frequency,
                cc.core_voltage,
                COUNT(*) as sample_count,

                -- Performance
                ROUND(AVG(pm.hashrate), 2) as avg_hashrate,
                ROUND(MIN(pm.hashrate), 2) as min_hashrate,
                ROUND(MAX(pm.hashrate), 2) as max_hashrate,

                -- Power & Efficiency
                ROUND(AVG(pm.power), 2) as avg_power,
                ROUND(MAX(pm.power), 2) as max_power,
                ROUND(AVG(pm.efficiency_jth), 2) as avg_efficiency_jth,
                ROUND(AVG(pm.efficiency_ghw), 2) as avg_efficiency_ghw,

                -- ASIC Temperature (thermal throttling indicator)
                ROUND(AVG(pm.asic_temp), 1) as avg_asic_temp,
                ROUND(MAX(pm.asic_temp), 1) as max_asic_temp,
                ROUND(MIN(pm.asic_temp), 1) as min_asic_temp,

                -- VR Temperature (voltage regulator stress indicator)
                ROUND(AVG(pm.vreg_temp), 1) as avg_vreg_temp,
                ROUND(MAX(pm.vreg_temp), 1) as max_vreg_temp,

                -- Input Voltage (PSU performance/sag indicator)
                ROUND(AVG(pm.voltage), 2) as avg_input_voltage,
                ROUND(MIN(pm.voltage), 2) as min_input_voltage,
                ROUND(MAX(pm.voltage), 2) as max_input_voltage,

                -- Current
                ROUND(AVG(pm.current), 2) as avg_current,
                ROUND(MAX(pm.current), 2) as max_current,

                -- Fan
                ROUND(AVG(pm.fan_speed), 0) as avg_fan_speed,
                ROUND(AVG(pm.fan_rpm), 0) as avg_fan_rpm,

                -- Timing
                MIN(pm.timestamp) as first_seen,
                MAX(pm.timestamp) as last_seen,
                CAST((julianday(MAX(pm.timestamp)) - julianday(MIN(pm.timestamp))) * 24 AS REAL) as runtime_hours

            FROM performance_metrics pm
            JOIN clock_configs cc ON pm.config_id = cc.id
            WHERE pm.device_id = ? {time_filter}
            GROUP BY cc.id
            ORDER BY avg_hashrate DESC
        """

        cursor = self.db.conn.cursor()
        cursor.execute(query, params)

        columns = [desc[0] for desc in cursor.description]
        results = []

        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))

        return results

    def get_latest_metrics(self, device_id: str) -> Optional[Dict]:
        """Get latest metrics for a device.

        Args:
            device_id: Device identifier

        Returns:
            Dictionary with latest metrics or None
        """
        return self.db.get_latest_metric(device_id)

    def get_all_devices_summary(self) -> Dict[str, Dict]:
        """Get summary for all devices.

        Returns:
            Dictionary mapping device_id to latest metrics
        """
        devices = self.db.get_devices()
        summary = {}

        for device in devices:
            device_id = device["id"]
            latest = self.get_latest_metrics(device_id)
            config_summary = self.get_config_summary(device_id)

            summary[device_id] = {
                "device": device,
                "latest": latest,
                "configs": config_summary,
                "total_samples": self.db.get_metric_count(device_id)
            }

        return summary

    def identify_bottlenecks(self, config_summary: Dict) -> List[str]:
        """Identify potential bottlenecks in a configuration.

        Args:
            config_summary: Configuration summary dictionary

        Returns:
            List of bottleneck warnings
        """
        warnings = []

        # Thermal throttling indicators
        if config_summary["max_asic_temp"] >= 65:
            warnings.append(
                f"🔥 ASIC thermal limit: {config_summary['max_asic_temp']}°C "
                f"(may cause throttling at 65°C+)"
            )
        elif config_summary["avg_asic_temp"] >= 60:
            warnings.append(
                f"⚠️  High ASIC temp: {config_summary['avg_asic_temp']}°C avg "
                f"(approaching thermal limits)"
            )

        # VR overheating
        if config_summary["max_vreg_temp"] >= 80:
            warnings.append(
                f"🔥 VR overheating: {config_summary['max_vreg_temp']}°C "
                f"(critical - voltage regulator stressed)"
            )
        elif config_summary["avg_vreg_temp"] >= 70:
            warnings.append(
                f"⚠️  High VR temp: {config_summary['avg_vreg_temp']}°C avg "
                f"(may need better cooling)"
            )

        # PSU voltage sag
        if config_summary["min_input_voltage"] < 4.8:
            warnings.append(
                f"⚡ PSU voltage sag: {config_summary['min_input_voltage']}V min "
                f"(PSU may be undersized, expect 5V)"
            )
        elif config_summary["avg_input_voltage"] < 4.9:
            warnings.append(
                f"⚠️  Low input voltage: {config_summary['avg_input_voltage']}V avg "
                f"(should be ~5V, check PSU)"
            )

        # High power draw
        if config_summary["max_power"] >= 20:
            warnings.append(
                f"⚡ High power draw: {config_summary['max_power']}W peak "
                f"(approaching 25W PSU limit)"
            )

        # Low hashrate variance (instability indicator)
        hashrate_variance = (
            (config_summary["max_hashrate"] - config_summary["min_hashrate"])
            / config_summary["avg_hashrate"] * 100
        )
        if hashrate_variance > 20:
            warnings.append(
                f"⚠️  Hashrate instability: {hashrate_variance:.1f}% variance "
                f"({config_summary['min_hashrate']}-{config_summary['max_hashrate']} GH/s)"
            )

        return warnings

    def compare_configs(
        self,
        device_id: str,
        hours: Optional[int] = None
    ) -> str:
        """Generate comparison report for all configurations.

        Args:
            device_id: Device identifier
            hours: Optional time window

        Returns:
            Formatted comparison report
        """
        configs = self.get_config_summary(device_id, hours)

        if not configs:
            return f"No data found for {device_id}"

        report = []
        report.append("=" * 100)
        report.append(f"Configuration Performance Analysis: {device_id}")
        if hours:
            report.append(f"Time window: Last {hours} hours")
        report.append("=" * 100)
        report.append("")

        for i, cfg in enumerate(configs, 1):
            config_name = f"{cfg['frequency']}MHz @ {cfg['core_voltage']}mV"

            report.append(f"[{i}] {config_name}")
            report.append("-" * 100)

            # Performance summary
            report.append(f"  📊 Performance:")
            report.append(f"     Hashrate:    {cfg['avg_hashrate']:.1f} GH/s  (range: {cfg['min_hashrate']:.1f} - {cfg['max_hashrate']:.1f})")
            report.append(f"     Efficiency:  {cfg['avg_efficiency_jth']:.1f} J/TH  |  {cfg['avg_efficiency_ghw']:.1f} GH/W")
            report.append("")

            # Power & electrical
            report.append(f"  ⚡ Power & Electrical:")
            report.append(f"     Power Draw:     {cfg['avg_power']:.1f}W  (max: {cfg['max_power']:.1f}W)")
            report.append(f"     Input Voltage:  {cfg['avg_input_voltage']:.2f}V  (range: {cfg['min_input_voltage']:.2f} - {cfg['max_input_voltage']:.2f}V)")
            report.append(f"     Current:        {cfg['avg_current']:.2f}A  (max: {cfg['max_current']:.2f}A)")
            report.append("")

            # Thermal
            report.append(f"  🌡️  Thermal:")
            report.append(f"     ASIC Temp:  {cfg['avg_asic_temp']:.1f}°C  (range: {cfg['min_asic_temp']:.1f} - {cfg['max_asic_temp']:.1f}°C)")
            report.append(f"     VR Temp:    {cfg['avg_vreg_temp']:.1f}°C  (max: {cfg['max_vreg_temp']:.1f}°C)")
            report.append(f"     Fan Speed:  {cfg['avg_fan_speed']:.0f}%  ({cfg['avg_fan_rpm']:.0f} RPM)")
            report.append("")

            # Runtime & samples
            report.append(f"  ⏱️  Runtime:")
            report.append(f"     Duration:  {cfg['runtime_hours']:.1f} hours  ({cfg['sample_count']} samples)")
            report.append(f"     Period:    {str(cfg['first_seen'])} to {str(cfg['last_seen'])}")
            report.append("")

            # Bottleneck analysis
            bottlenecks = self.identify_bottlenecks(cfg)
            if bottlenecks:
                report.append(f"  ⚠️  Potential Bottlenecks:")
                for warning in bottlenecks:
                    report.append(f"     {warning}")
                report.append("")
            else:
                report.append(f"  ✅ No bottlenecks detected")
                report.append("")

        # Summary recommendations
        report.append("=" * 100)
        report.append("Summary & Recommendations")
        report.append("=" * 100)

        best_efficiency = min(configs, key=lambda x: x['avg_efficiency_jth'])
        best_hashrate = max(configs, key=lambda x: x['avg_hashrate'])

        report.append(f"🏆 Best Efficiency: {best_efficiency['frequency']}MHz @ {best_efficiency['core_voltage']}mV")
        report.append(f"   {best_efficiency['avg_efficiency_jth']:.1f} J/TH, {best_efficiency['avg_hashrate']:.1f} GH/s")
        report.append("")

        report.append(f"🚀 Best Hashrate:   {best_hashrate['frequency']}MHz @ {best_hashrate['core_voltage']}mV")
        report.append(f"   {best_hashrate['avg_hashrate']:.1f} GH/s, {best_hashrate['avg_efficiency_jth']:.1f} J/TH")
        report.append("")

        return "\n".join(report)

    def export_csv(self, device_id: str, output_path: str):
        """Export device metrics to CSV.

        Args:
            device_id: Device identifier
            output_path: Output file path
        """
        query = """
            SELECT
                pm.timestamp,
                pm.device_id,
                cc.frequency,
                cc.core_voltage,
                pm.hashrate,
                pm.power,
                pm.voltage,
                pm.current,
                pm.asic_temp,
                pm.vreg_temp,
                pm.fan_speed,
                pm.fan_rpm,
                pm.efficiency_jth,
                pm.efficiency_ghw,
                pm.shares_accepted,
                pm.shares_rejected
            FROM performance_metrics pm
            JOIN clock_configs cc ON pm.config_id = cc.id
            WHERE pm.device_id = ?
            ORDER BY pm.timestamp
        """

        cursor = self.db.conn.cursor()
        cursor.execute(query, (device_id,))

        with open(output_path, 'w') as f:
            # Write header
            columns = [desc[0] for desc in cursor.description]
            f.write(','.join(columns) + '\n')

            # Write data
            for row in cursor.fetchall():
                f.write(','.join(str(v) for v in row) + '\n')
