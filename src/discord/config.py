"""Discord bot configuration."""

import os
from typing import Optional, List
from pydantic import BaseModel, Field


class AutoReportConfig(BaseModel):
    """Auto-report configuration."""
    enabled: bool = False
    channel_name: str = "swarm"
    channel_id: Optional[int] = None
    schedule: str = "0 * * * *"  # Cron format
    include_charts: bool = True
    graph_lookback_hours: int = 12


class WeeklyReportConfig(BaseModel):
    """Weekly report configuration."""
    enabled: bool = False
    channel_name: str = "swarm"
    channel_id: Optional[int] = None
    schedule: str = "0 12 * * 1"  # Monday 12:00 UTC (7am EST)
    include_charts: bool = True
    graph_lookback_hours: int = 168  # 7 days


class AlertConfig(BaseModel):
    """Alert configuration for offline miners."""
    enabled: bool = False
    channel_id: Optional[int] = None
    user_id_to_tag: Optional[int] = None  # Discord user ID to mention
    check_interval_minutes: int = 5  # How often to check for offline miners
    offline_threshold_minutes: int = 10  # Minutes without data to consider offline


class ChartConfig(BaseModel):
    """Chart generation configuration."""
    dpi: int = 150
    style: str = "dark_background"
    figsize: List[int] = Field(default_factory=lambda: [14, 7])
    cache_ttl: int = 300  # seconds


class CommandConfig(BaseModel):
    """Command-specific configuration."""
    status_cooldown: int = 10
    report_cooldown: int = 60
    report_max_hours: int = 336  # 14 days
    miner_cooldown: int = 30


class ControlConfig(BaseModel):
    """Remote control configuration for miner commands."""
    enabled: bool = False
    admin_role_id: Optional[int] = None  # Discord role ID required for control commands
    admin_role_name: str = "Miner Admin"  # For display purposes
    # Safety limits
    min_frequency: int = 400  # MHz
    max_frequency: int = 650  # MHz
    min_voltage: int = 1000  # mV
    max_voltage: int = 1300  # mV
    min_fan_speed: int = 0  # %
    max_fan_speed: int = 100  # %


class DiscordConfig(BaseModel):
    """Discord bot configuration."""
    enabled: bool = False
    token: str
    command_prefix: str = "!"
    allowed_channels: List[int] = Field(default_factory=list)
    auto_report: AutoReportConfig = Field(default_factory=AutoReportConfig)
    weekly_report: WeeklyReportConfig = Field(default_factory=WeeklyReportConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    charts: ChartConfig = Field(default_factory=ChartConfig)
    commands: CommandConfig = Field(default_factory=CommandConfig)
    control: ControlConfig = Field(default_factory=ControlConfig)

    @classmethod
    def from_yaml(cls, yaml_config: dict) -> 'DiscordConfig':
        """Create config from YAML dict, resolving environment variables.

        Args:
            yaml_config: Discord section from config.yaml

        Returns:
            DiscordConfig instance
        """
        # Resolve environment variables in token
        token = yaml_config.get('token', '')
        if token.startswith('${') and token.endswith('}'):
            env_var = token[2:-1]
            token = os.getenv(env_var, '')
            if not token:
                raise ValueError(f"Environment variable {env_var} not set")

        # Convert channel_id to int if present
        if 'auto_report' in yaml_config:
            auto_report = yaml_config['auto_report'].copy()
            if 'channel_id' in auto_report and auto_report['channel_id']:
                auto_report['channel_id'] = int(auto_report['channel_id'])
            yaml_config['auto_report'] = auto_report

        # Convert weekly_report channel_id to int if present
        if 'weekly_report' in yaml_config:
            weekly_report = yaml_config['weekly_report'].copy()
            if 'channel_id' in weekly_report and weekly_report['channel_id']:
                weekly_report['channel_id'] = int(weekly_report['channel_id'])
            yaml_config['weekly_report'] = weekly_report

        # Convert alerts channel_id and user_id_to_tag to ints
        if 'alerts' in yaml_config:
            alerts = yaml_config['alerts'].copy()
            if 'channel_id' in alerts and alerts['channel_id']:
                alerts['channel_id'] = int(alerts['channel_id'])
            if 'user_id_to_tag' in alerts and alerts['user_id_to_tag']:
                alerts['user_id_to_tag'] = int(alerts['user_id_to_tag'])
            yaml_config['alerts'] = alerts

        # Convert allowed_channels to ints
        if 'allowed_channels' in yaml_config:
            yaml_config['allowed_channels'] = [
                int(ch) for ch in yaml_config['allowed_channels']
            ]

        # Convert control admin_role_id to int if present
        if 'control' in yaml_config:
            control = yaml_config['control'].copy()
            if 'admin_role_id' in control and control['admin_role_id']:
                control['admin_role_id'] = int(control['admin_role_id'])
            yaml_config['control'] = control

        return cls(token=token, **{k: v for k, v in yaml_config.items() if k != 'token'})

    def validate_auto_report(self) -> bool:
        """Check if auto-report is properly configured.

        Returns:
            True if auto-report can be enabled

        Raises:
            ValueError if configuration is invalid
        """
        if not self.auto_report.enabled:
            return False

        if not self.auto_report.channel_id:
            raise ValueError("auto_report.channel_id is required when auto_report is enabled")

        return True
