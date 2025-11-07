"""Discord bot for Bitaxe monitoring."""

import io
import logging
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands, tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import Database
from ..analyzer import Analyzer
from .config import DiscordConfig
from .chart_generator import ChartGenerator


logger = logging.getLogger(__name__)


class BitaxeBot(commands.Bot):
    """Discord bot for Bitaxe mining monitoring."""

    def __init__(self, config: DiscordConfig, database: Database, devices: list):
        """Initialize the bot.

        Args:
            config: Discord configuration
            database: Database instance
            devices: List of device configs from main config
        """
        intents = discord.Intents.default()
        intents.message_content = True  # Required for text commands

        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            help_command=None  # We'll create custom help
        )

        self.config = config
        self.db = database
        self.analyzer = Analyzer(database)
        self.devices = [d for d in devices if d.get('enabled', True)]
        self.scheduler = AsyncIOScheduler()

        # Initialize chart generator
        chart_config = {
            'dpi': config.charts.dpi,
            'figsize': config.charts.figsize,
            'style': config.charts.style,
            'cache_ttl': config.charts.cache_ttl,
        }
        self.chart_generator = ChartGenerator(database, chart_config)

        # Register commands
        self.add_commands()

    def add_commands(self):
        """Register bot commands."""

        @self.command(name='status')
        # @commands.cooldown(1, self.config.commands.status_cooldown, commands.BucketType.user)  # Disabled for testing
        async def status_command(ctx):
            """Show instant snapshot of all miners."""
            await self.cmd_status(ctx)

        @self.command(name='stats')
        # @commands.cooldown(1, self.config.commands.status_cooldown, commands.BucketType.user)  # Disabled for testing
        async def stats_command(ctx):
            """Show detailed statistics from stats.py."""
            await self.cmd_stats(ctx)

        @self.command(name='report')
        # @commands.cooldown(1, self.config.commands.report_cooldown, commands.BucketType.user)  # Disabled for testing
        async def report_command(ctx, timespan: str = "24"):
            """Generate detailed performance report.

            Usage: !report [hours|days]
            Examples: !report 12, !report 7d, !report 168
            """
            await self.cmd_report(ctx, timespan)

        @self.command(name='miner')
        # @commands.cooldown(1, self.config.commands.miner_cooldown, commands.BucketType.user)  # Disabled for testing
        async def miner_command(ctx, name: str):
            """Show detailed stats for a specific miner.

            Usage: !miner <name>
            Example: !miner bitaxe-1
            """
            await self.cmd_miner(ctx, name)

        @self.command(name='health')
        async def health_command(ctx):
            """Check system health and warnings."""
            await self.cmd_health(ctx)

        @self.command(name='help')
        async def help_command(ctx):
            """Show available commands."""
            await self.cmd_help(ctx)

    async def on_ready(self):
        """Called when bot is connected and ready."""
        logger.info(f"Connected to Discord as {self.user.name}#{self.user.discriminator}")
        logger.info(f"Bot ID: {self.user.id}")
        logger.info(f"Command prefix: {self.config.command_prefix}")

        # Start auto-reporting if enabled
        if self.config.auto_report.enabled:
            try:
                self.config.validate_auto_report()
                self.schedule_auto_report()
                logger.info(f"Auto-report scheduled: {self.config.auto_report.schedule}")
                logger.info(f"Auto-report channel: #{self.config.auto_report.channel_name} ({self.config.auto_report.channel_id})")
            except ValueError as e:
                logger.error(f"Auto-report configuration error: {e}")

        # Start weekly reporting if enabled
        if self.config.weekly_report.enabled:
            try:
                if not self.config.weekly_report.channel_id:
                    raise ValueError("weekly_report.channel_id is required")
                self.schedule_weekly_report()
                logger.info(f"Weekly report scheduled: {self.config.weekly_report.schedule}")
                logger.info(f"Weekly report channel: #{self.config.weekly_report.channel_name} ({self.config.weekly_report.channel_id})")
            except ValueError as e:
                logger.error(f"Weekly report configuration error: {e}")

        logger.info(f"Bot ready! Monitoring {len(self.devices)} devices")

    async def on_command_error(self, ctx, error):
        """Handle command errors."""
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Command on cooldown. Try again in {error.retry_after:.0f} seconds.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Invalid argument. Use `{self.config.command_prefix}help` for usage.")
        else:
            logger.error(f"Command error: {error}", exc_info=error)
            await ctx.send(f"❌ An error occurred. Check bot logs for details.")

    def schedule_auto_report(self):
        """Schedule automatic reports using cron syntax."""
        # Parse cron schedule (format: "minute hour day month day_of_week")
        parts = self.config.auto_report.schedule.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron schedule: {self.config.auto_report.schedule}")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4]
        )

        self.scheduler.add_job(
            self.send_auto_report,
            trigger=trigger,
            id='auto_report',
            name='Auto Report'
        )
        self.scheduler.start()

    async def send_auto_report(self):
        """Send scheduled auto-report to configured channel."""
        try:
            channel = self.get_channel(self.config.auto_report.channel_id)
            if not channel:
                logger.error(f"Auto-report channel not found: {self.config.auto_report.channel_id}")
                return

            logger.info(f"Sending auto-report to #{self.config.auto_report.channel_name}")

            # Generate report (with charts if enabled)
            report = self.generate_status_report()

            if self.config.auto_report.include_charts:
                # Generate charts
                hours = self.config.auto_report.graph_lookback_hours
                device_ids = [d['name'] for d in self.devices]

                swarm_chart = self.chart_generator.generate_swarm_hashrate_chart(hours, device_ids)
                miner_chart = self.chart_generator.generate_miner_detail_chart(hours, device_ids)

                swarm_file = discord.File(io.BytesIO(swarm_chart), filename=f"swarm_hashrate_{hours}h.png")
                miner_file = discord.File(io.BytesIO(miner_chart), filename=f"miner_details_{hours}h.png")

                await channel.send(content=f"**⛏️ Hourly Report ({hours}h)**\n{report}", files=[swarm_file, miner_file])
            else:
                await channel.send(report)

            logger.info("Auto-report sent successfully")
        except Exception as e:
            logger.error(f"Failed to send auto-report: {e}", exc_info=e)

    def schedule_weekly_report(self):
        """Schedule weekly report using cron syntax (UTC)."""
        parts = self.config.weekly_report.schedule.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron schedule: {self.config.weekly_report.schedule}")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4]
        )

        self.scheduler.add_job(
            self.send_weekly_report,
            trigger=trigger,
            id='weekly_report',
            name='Weekly Report'
        )

    async def send_weekly_report(self):
        """Send scheduled weekly report to configured channel."""
        try:
            channel = self.get_channel(self.config.weekly_report.channel_id)
            if not channel:
                logger.error(f"Weekly report channel not found: {self.config.weekly_report.channel_id}")
                return

            logger.info(f"Sending weekly report to #{self.config.weekly_report.channel_name}")

            # Generate 7-day report
            hours = self.config.weekly_report.graph_lookback_hours
            device_ids = [d['name'] for d in self.devices]

            # Generate text report
            report = self.generate_status_report()

            if self.config.weekly_report.include_charts:
                # Generate charts
                swarm_chart = self.chart_generator.generate_swarm_hashrate_chart(hours, device_ids)
                miner_chart = self.chart_generator.generate_miner_detail_chart(hours, device_ids)

                swarm_file = discord.File(io.BytesIO(swarm_chart), filename=f"swarm_hashrate_7d.png")
                miner_file = discord.File(io.BytesIO(miner_chart), filename=f"miner_details_7d.png")

                await channel.send(
                    content=f"**⛏️ Weekly Report (7 days)**\n{report}",
                    files=[swarm_file, miner_file]
                )
            else:
                await channel.send(f"**⛏️ Weekly Report (7 days)**\n{report}")

            logger.info("Weekly report sent successfully")
        except Exception as e:
            logger.error(f"Failed to send weekly report: {e}", exc_info=e)

    def get_swarm_1h_average(self) -> tuple[float, float]:
        """Calculate 1-hour average hashrate and power for entire swarm.

        Returns:
            Tuple of (avg_hashrate, avg_power) or (0, 0) if no data
        """
        from datetime import datetime, timedelta

        # Get 1h averages for each device
        lookback = datetime.now() - timedelta(hours=1)

        total_hashrate = 0
        total_power = 0
        device_count = 0

        for device in self.devices:
            device_id = device['name']

            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT AVG(hashrate) as avg_hr, AVG(power) as avg_pwr
                FROM performance_metrics
                WHERE device_id = ?
                  AND timestamp >= ?
            """, (device_id, lookback))

            row = cursor.fetchone()
            if row and row[0]:
                total_hashrate += row[0]
                total_power += row[1] if row[1] else 0
                device_count += 1

        return (total_hashrate, total_power)

    def generate_status_report(self) -> str:
        """Generate compact status report with ANSI colors.

        Returns:
            Formatted status string with ANSI color codes (under 2000 chars)
        """
        lines = []
        lines.append("```ansi")  # Start ANSI code block
        lines.append("\x1b[1;36m⛏️  Bitaxe Swarm (1h avg)\x1b[0m")  # Shorter header

        # Get summary data
        summary = self.analyzer.get_all_devices_summary()

        # Calculate 1h averages (more meaningful than snapshot)
        avg_hashrate_1h, avg_power_1h = self.get_swarm_1h_average()

        # Count active miners
        active_count = sum(1 for data in summary.values() if data['latest'])

        # Calculate efficiency from 1h averages
        avg_efficiency = (avg_power_1h / (avg_hashrate_1h / 1000.0)) if avg_hashrate_1h > 0 else 0

        # Compact swarm summary - convert to TH/s
        lines.append(f"\x1b[0;36m{avg_hashrate_1h/1000:.2f} Th/s\x1b[0m | \x1b[0;32m{active_count}/{len(self.devices)}\x1b[0m | \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m | \x1b[0;36m{avg_power_1h:.1f}W\x1b[0m")
        lines.append("")

        for device in self.devices:
            device_id = device['name']

            data = summary.get(device_id)
            if not data or not data['latest']:
                lines.append(f"\x1b[0;31m{device_id}: No data\x1b[0m")
                continue

            latest = data['latest']

            # Get 1h averages for hashrate and efficiency
            from datetime import datetime, timedelta
            lookback = datetime.now() - timedelta(hours=1)

            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT AVG(hashrate) as avg_hr, AVG(efficiency_jth) as avg_eff
                FROM performance_metrics
                WHERE device_id = ? AND timestamp >= ? AND efficiency_jth IS NOT NULL
            """, (device_id, lookback))

            row = cursor.fetchone()
            avg_hashrate = row[0] if row and row[0] else latest['hashrate']
            avg_efficiency = row[1] if row and row[1] else latest['efficiency_jth']

            # Get data
            freq = latest['frequency']
            voltage = latest['core_voltage']
            asic_temp = latest['asic_temp']
            vreg_temp = latest['vreg_temp']
            power = latest['power']
            uptime_hours = latest['uptime'] / 3600

            # Temp colors
            asic_c = "\x1b[0;31m" if asic_temp >= 65 else "\x1b[0;33m" if asic_temp >= 60 else "\x1b[0;32m"
            vreg_c = "\x1b[0;31m" if vreg_temp >= 80 else "\x1b[0;33m" if vreg_temp >= 70 else "\x1b[0;32m"

            # Compact uptime
            uptime_str = f"{int(uptime_hours//24)}d" if uptime_hours >= 24 else f"{uptime_hours:.1f}h"

            # Super compact format - one line per miner - convert to TH/s
            lines.append(f"\x1b[1;37m{device_id}\x1b[0m {freq} MHz \x1b[0;36m{avg_hashrate/1000:.2f} TH/s\x1b[0m \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m {asic_c}{asic_temp:.0f}°\x1b[0m/{vreg_c}{vreg_temp:.0f}°\x1b[0m \x1b[0;32m{uptime_str}\x1b[0m")

        lines.append("```")
        return "\n".join(lines)

    def generate_status_snapshot(self) -> str:
        """Generate instant snapshot report (no averaging).

        Returns:
            Formatted status string with current values
        """
        lines = []
        lines.append("```ansi")
        lines.append("\x1b[1;36m⛏️  Bitaxe Swarm (snapshot)\x1b[0m")

        # Get summary data
        summary = self.analyzer.get_all_devices_summary()

        # Calculate swarm totals from current values
        total_hashrate = 0
        total_power = 0
        active_count = 0

        for data in summary.values():
            if data['latest']:
                total_hashrate += data['latest']['hashrate']
                total_power += data['latest']['power']
                active_count += 1

        avg_efficiency = (total_power / (total_hashrate / 1000.0)) if total_hashrate > 0 else 0

        # Swarm summary line - convert to TH/s
        lines.append(f"\x1b[0;36m{total_hashrate/1000:.2f} Th/s\x1b[0m | \x1b[0;32m{active_count}/{len(self.devices)}\x1b[0m | \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m | \x1b[0;36m{total_power:.1f}W\x1b[0m")
        lines.append("")

        for device in self.devices:
            device_id = device['name']
            data = summary.get(device_id)

            if not data or not data['latest']:
                lines.append(f"\x1b[0;31m{device_id}: No data\x1b[0m")
                continue

            latest = data['latest']

            # All current values
            freq = latest['frequency']
            hashrate = latest['hashrate']
            efficiency = latest['efficiency_jth']
            asic_temp = latest['asic_temp']
            vreg_temp = latest['vreg_temp']
            uptime_hours = latest['uptime'] / 3600

            # Temp colors
            asic_c = "\x1b[0;31m" if asic_temp >= 65 else "\x1b[0;33m" if asic_temp >= 60 else "\x1b[0;32m"
            vreg_c = "\x1b[0;31m" if vreg_temp >= 80 else "\x1b[0;33m" if vreg_temp >= 70 else "\x1b[0;32m"

            # Compact uptime
            uptime_str = f"{int(uptime_hours//24)}d" if uptime_hours >= 24 else f"{uptime_hours:.1f}h"

            # Current values format - convert to TH/s
            lines.append(f"\x1b[1;37m{device_id}\x1b[0m {freq} MHz \x1b[0;36m{hashrate/1000:.2f} Th/s\x1b[0m \x1b[0;36m{efficiency:.1f} J/TH\x1b[0m {asic_c}{asic_temp:.0f}°\x1b[0m/{vreg_c}{vreg_temp:.0f}°\x1b[0m \x1b[0;32m{uptime_str}\x1b[0m")

        lines.append("```")
        return "\n".join(lines)

    async def cmd_status(self, ctx):
        """Handle !status command (instant snapshot)."""
        logger.info(f"!status command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        report = self.generate_status_snapshot()
        await ctx.send(report)

    async def cmd_stats(self, ctx):
        """Handle !stats command - run stats.py stats and render as image."""
        logger.info(f"!stats command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        await ctx.send("📊 Generating detailed statistics report...")

        try:
            # Run stats.py stats command
            import subprocess
            result = subprocess.run(
                ['python', 'stats.py', 'stats'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                await ctx.send(f"❌ Failed to generate stats: {result.stderr[:500]}")
                return

            stats_output = result.stdout

            # Convert text to image for mobile-friendly viewing
            stats_image = self._text_to_image(stats_output)

            # Send as image
            file = discord.File(io.BytesIO(stats_image), filename='bitaxe_stats.png')
            await ctx.send(
                content="📊 **Detailed Statistics Report**",
                file=file
            )

            logger.info("Stats sent successfully")

        except subprocess.TimeoutExpired:
            await ctx.send("❌ Stats generation timed out")
        except Exception as e:
            logger.error(f"Failed to generate stats: {e}", exc_info=e)
            await ctx.send(f"❌ Failed to generate stats: {str(e)}")

    def _text_to_image(self, text: str) -> bytes:
        """Convert text to PNG image for mobile-friendly viewing.

        Args:
            text: Text content to render

        Returns:
            PNG image as bytes
        """
        import matplotlib.pyplot as plt
        import re

        # Remove emojis (they don't render well in monospace)
        # Replace common emojis with text equivalents
        text = text.replace('📊', '[Stats]')
        text = text.replace('🏆', '[Best]')
        # Remove any remaining emojis
        text = re.sub(r'[^\x00-\x7F]+', '', text)

        # Use monospace font for alignment
        plt.rcParams['font.family'] = 'monospace'
        plt.rcParams['font.size'] = 9

        # Calculate figure size based on text
        lines = text.split('\n')
        max_line_length = max(len(line) for line in lines) if lines else 80
        num_lines = len(lines)

        # Size: ~0.1 inch per character width, 0.15 inch per line height
        fig_width = min(20, max(12, max_line_length * 0.08))
        fig_height = min(30, max(8, num_lines * 0.15))

        fig, ax = plt.subplots(figsize=(fig_width, fig_height))
        fig.patch.set_facecolor('#2B2D31')  # Discord dark background
        ax.set_facecolor('#2B2D31')
        ax.axis('off')

        # Render text
        ax.text(0.02, 0.98, text,
               transform=ax.transAxes,
               fontfamily='monospace',
               fontsize=9,
               color='#DCDDDE',  # Discord text color
               verticalalignment='top',
               horizontalalignment='left')

        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                   facecolor='#2B2D31', edgecolor='none')
        buf.seek(0)
        image_bytes = buf.read()
        buf.close()
        plt.close(fig)

        return image_bytes

    async def cmd_report(self, ctx, timespan: str):
        """Handle !report command with charts."""
        logger.info(f"!report {timespan} command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        # Parse timespan (support "7d" for days, or plain hours)
        try:
            if timespan.lower().endswith('d'):
                # Days format: "7d" = 7 * 24 hours
                days = int(timespan[:-1])
                hours = days * 24
                timespan_label = f"{days}d"
            else:
                # Plain hours: "168"
                hours = int(timespan)
                # Show as days if >= 24h and divisible by 24
                if hours >= 24 and hours % 24 == 0:
                    timespan_label = f"{hours//24}d"
                else:
                    timespan_label = f"{hours}h"
        except ValueError:
            await ctx.send(f"❌ Invalid timespan: {timespan}. Use hours (e.g., 24) or days (e.g., 7d)")
            return

        # Validate hours
        if hours < 1 or hours > self.config.commands.report_max_hours:
            max_days = self.config.commands.report_max_hours // 24
            await ctx.send(f"❌ Timespan must be between 1h and {max_days}d ({self.config.commands.report_max_hours}h)")
            return

        # Send status message first
        await ctx.send(f"📊 Generating {timespan_label} performance report with charts...")

        try:
            # Get device IDs
            device_ids = [d['name'] for d in self.devices]

            # Generate charts
            logger.info("Generating swarm hashrate chart...")
            swarm_chart = self.chart_generator.generate_swarm_hashrate_chart(hours, device_ids)

            logger.info("Generating miner detail chart...")
            miner_chart = self.chart_generator.generate_miner_detail_chart(hours, device_ids)

            # Create Discord files
            swarm_file = discord.File(io.BytesIO(swarm_chart), filename=f"swarm_hashrate_{hours}h.png")
            miner_file = discord.File(io.BytesIO(miner_chart), filename=f"miner_details_{hours}h.png")

            # Generate text report
            report = self.generate_status_report()

            # Send with attachments
            await ctx.send(
                content=f"**⛏️ Bitaxe Mining Report ({timespan_label})**\n{report}",
                files=[swarm_file, miner_file]
            )

            logger.info("Report sent successfully")

        except Exception as e:
            logger.error(f"Failed to generate report: {e}", exc_info=e)
            await ctx.send(f"❌ Failed to generate report: {str(e)}")

    async def cmd_miner(self, ctx, name: str):
        """Handle !miner command with detailed chart."""
        logger.info(f"!miner {name} command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        # Validate device name
        device_names = [d['name'] for d in self.devices]
        if name not in device_names:
            await ctx.send(f"❌ Unknown miner: {name}\nAvailable: {', '.join(device_names)}")
            return

        # Send status message
        await ctx.send(f"🔍 Generating detailed stats for **{name}**...")

        try:
            # Get latest metrics for this miner
            latest = self.db.get_latest_metric(name)

            if not latest:
                await ctx.send(f"❌ No data available for {name}")
                return

            # Generate chart (default 24h)
            hours = 24
            logger.info(f"Generating chart for {name} ({hours}h)")
            chart = self.chart_generator.generate_single_miner_chart(name, hours)

            # Create Discord file
            chart_file = discord.File(io.BytesIO(chart), filename=f"{name}_{hours}h.png")

            # Build stats message
            freq = latest['frequency']
            voltage = latest['core_voltage']
            hashrate = latest['hashrate']
            efficiency = latest['efficiency_jth']
            asic_temp = latest['asic_temp']
            vreg_temp = latest['vreg_temp']
            power = latest['power']
            uptime_hours = latest['uptime'] / 3600

            # Calculate 1h average for comparison
            from datetime import datetime, timedelta
            lookback = datetime.now() - timedelta(hours=1)
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT AVG(hashrate) as avg_hr, AVG(efficiency_jth) as avg_eff
                FROM performance_metrics
                WHERE device_id = ? AND timestamp >= ? AND efficiency_jth IS NOT NULL
            """, (name, lookback))
            row = cursor.fetchone()
            avg_hashrate = row[0] if row and row[0] else hashrate
            avg_efficiency = row[1] if row and row[1] else efficiency

            # Format uptime
            uptime_str = f"{int(uptime_hours//24)}d {int(uptime_hours%24)}h" if uptime_hours >= 24 else f"{uptime_hours:.1f}h"

            stats_msg = f"""**🔍 Detailed Stats: {name}**

**Configuration**
⚙️ Clock: {freq} MHz @ {voltage} mV
⏱️ Uptime: {uptime_str}

**Performance**
⛏️ Current Hashrate: {hashrate/1000:.3f} TH/s
📊 1h Average: {avg_hashrate/1000:.3f} TH/s
⚡ Efficiency: {efficiency:.1f} J/TH (1h avg: {avg_efficiency:.1f})
🔌 Power: {power:.1f}W

**Thermals**
🌡️ ASIC Temp: {asic_temp:.1f}°C
🌡️ VRM Temp: {vreg_temp:.1f}°C
"""

            # Send with chart
            await ctx.send(content=stats_msg, file=chart_file)

            logger.info(f"Miner detail sent for {name}")

        except Exception as e:
            logger.error(f"Failed to generate miner detail: {e}", exc_info=e)
            await ctx.send(f"❌ Failed to generate miner detail: {str(e)}")

    async def cmd_health(self, ctx):
        """Handle !health command."""
        logger.info(f"!health command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        summary = self.analyzer.get_all_devices_summary()

        warnings = []

        for device_id, data in summary.items():
            if not data or not data['latest']:
                warnings.append(f"❌ {device_id}: No data available")
                continue

            latest = data['latest']

            # Check temperature
            if latest['asic_temp'] >= 65:
                warnings.append(f"🔥 {device_id}: High ASIC temp ({latest['asic_temp']:.1f}°C)")
            if latest['vreg_temp'] >= 80:
                warnings.append(f"🔥 {device_id}: High VRM temp ({latest['vreg_temp']:.1f}°C)")

            # Check voltage
            if latest['voltage'] < 4.8:
                warnings.append(f"⚡ {device_id}: Low voltage ({latest['voltage']:.2f}V)")

            # Check hashrate
            if latest['hashrate'] < 400:
                warnings.append(f"📉 {device_id}: Low hashrate ({latest['hashrate']:.1f} GH/s)")

        if warnings:
            message = "⚠️ **Health Check - Warnings Found**\n" + "\n".join(warnings)
        else:
            message = "✅ **Health Check - All Systems Nominal**\n"
            message += "- No temperature warnings\n"
            message += "- All voltages stable\n"
            message += "- All hashrates normal"

        await ctx.send(message)

    async def cmd_help(self, ctx):
        """Handle !help command."""
        prefix = self.config.command_prefix

        help_text = f"""
⛏️ **Bitaxe Monitor Bot Commands**

**Status & Reports**
`{prefix}status` - Instant snapshot (current values, noisy)
`{prefix}stats` - Detailed configuration statistics ⭐
`{prefix}report [hours|days]` - Performance report with charts (default: 24h)
`{prefix}miner <name>` - Individual miner deep-dive with chart
`{prefix}health` - Check for warnings and issues

**Examples**
`{prefix}status` - Quick check (instant values)
`{prefix}stats` - All clock configs tested, efficiency rankings
`{prefix}report` - 24-hour report with charts (default)
`{prefix}report 1` - 1-hour report (like old !stats)
`{prefix}report 12` - 12-hour report
`{prefix}report 7d` - 7-day report
`{prefix}report 14d` - 14-day report (max)
`{prefix}miner bitaxe-1` - Individual miner performance

**Info**
Charts use 15-min and 1h moving averages for clean visualization
Hourly auto-reports post 12h charts to #{self.config.auto_report.channel_name}
Weekly reports post 7d charts every Monday
Monitoring {len(self.devices)} devices
        """.strip()

        await ctx.send(help_text)
