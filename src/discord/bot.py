"""Discord bot for Bitaxe monitoring."""

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

        # Register commands
        self.add_commands()

    def add_commands(self):
        """Register bot commands."""

        @self.command(name='status')
        @commands.cooldown(1, self.config.commands.status_cooldown, commands.BucketType.user)
        async def status_command(ctx):
            """Show instant snapshot of all miners."""
            await self.cmd_status(ctx)

        @self.command(name='stats')
        @commands.cooldown(1, self.config.commands.status_cooldown, commands.BucketType.user)
        async def stats_command(ctx):
            """Show 1h averaged stats of all miners."""
            await self.cmd_stats(ctx)

        @self.command(name='report')
        @commands.cooldown(1, self.config.commands.report_cooldown, commands.BucketType.user)
        async def report_command(ctx, hours: int = 24):
            """Generate detailed performance report.

            Usage: !report [hours]
            Example: !report 12
            """
            await self.cmd_report(ctx, hours)

        @self.command(name='miner')
        @commands.cooldown(1, self.config.commands.miner_cooldown, commands.BucketType.user)
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

            # Generate report (will add charts in Phase 2)
            report = self.generate_status_report()
            await channel.send(report)

            logger.info("Auto-report sent successfully")
        except Exception as e:
            logger.error(f"Failed to send auto-report: {e}", exc_info=e)

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

        # Compact swarm summary
        lines.append(f"\x1b[0;36m{avg_hashrate_1h:.1f}GH/s\x1b[0m | \x1b[0;32m{active_count}/{len(self.devices)}\x1b[0m | \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m | \x1b[0;36m{avg_power_1h:.1f}W\x1b[0m")
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

            # Super compact format - one line per miner
            lines.append(f"\x1b[1;37m{device_id}\x1b[0m {freq}MHz \x1b[0;36m{avg_hashrate:.0f}GH/s\x1b[0m \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m {asic_c}{asic_temp:.0f}°\x1b[0m/{vreg_c}{vreg_temp:.0f}°\x1b[0m \x1b[0;32m{uptime_str}\x1b[0m")

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

        # Swarm summary line
        lines.append(f"\x1b[0;36m{total_hashrate:.1f}GH/s\x1b[0m | \x1b[0;32m{active_count}/{len(self.devices)}\x1b[0m | \x1b[0;36m{avg_efficiency:.1f} J/TH\x1b[0m | \x1b[0;36m{total_power:.1f}W\x1b[0m")
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

            # Current values format
            lines.append(f"\x1b[1;37m{device_id}\x1b[0m {freq}MHz \x1b[0;36m{hashrate:.0f}GH/s\x1b[0m \x1b[0;36m{efficiency:.1f} J/TH\x1b[0m {asic_c}{asic_temp:.0f}°\x1b[0m/{vreg_c}{vreg_temp:.0f}°\x1b[0m \x1b[0;32m{uptime_str}\x1b[0m")

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
        """Handle !stats command."""
        logger.info(f"!stats command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        report = self.generate_status_report()
        await ctx.send(report)

    async def cmd_report(self, ctx, hours: int):
        """Handle !report command (will add charts in Phase 2)."""
        logger.info(f"!report {hours} command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        # Validate hours
        if hours < 1 or hours > self.config.commands.report_max_hours:
            await ctx.send(f"❌ Hours must be between 1 and {self.config.commands.report_max_hours}")
            return

        # For Phase 1, just show status + message about charts coming
        report = self.generate_status_report()
        report += f"\n\n*📊 Charts coming in Phase 2! (requested {hours}h lookback)*"

        await ctx.send(report)

    async def cmd_miner(self, ctx, name: str):
        """Handle !miner command."""
        logger.info(f"!miner {name} command from {ctx.author.name}")

        # Check channel restrictions
        if self.config.allowed_channels and ctx.channel.id not in self.config.allowed_channels:
            return

        # Validate device name
        device_names = [d['name'] for d in self.devices]
        if name not in device_names:
            await ctx.send(f"❌ Unknown miner: {name}\nAvailable: {', '.join(device_names)}")
            return

        await ctx.send(f"🔍 Detailed stats for **{name}** coming in Phase 2!")

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
`{prefix}status` - Instant snapshot (current values)
`{prefix}stats` - Averaged stats (1h averages) ⭐
`{prefix}report [hours]` - Detailed report with charts (default: 24h)
`{prefix}miner <name>` - Detailed stats for one miner
`{prefix}health` - Check for warnings and issues

**Examples**
`{prefix}status` - Quick check (noisy, instant)
`{prefix}stats` - Reliable stats (1h avg)
`{prefix}report 12` - 12-hour report with charts
`{prefix}miner bitaxe-1` - Individual deep-dive

**Info**
Auto-reports use `{prefix}stats` (1h avg) every hour to #{self.config.auto_report.channel_name}
Monitoring {len(self.devices)} devices
        """.strip()

        await ctx.send(help_text)
