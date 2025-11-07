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


class DiscordConfig(BaseModel):
    """Discord bot configuration."""
    enabled: bool = False
    token: str
    command_prefix: str = "!"
    allowed_channels: List[int] = Field(default_factory=list)
    auto_report: AutoReportConfig = Field(default_factory=AutoReportConfig)
    weekly_report: WeeklyReportConfig = Field(default_factory=WeeklyReportConfig)
    charts: ChartConfig = Field(default_factory=ChartConfig)
    commands: CommandConfig = Field(default_factory=CommandConfig)

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

        # Convert allowed_channels to ints
        if 'allowed_channels' in yaml_config:
            yaml_config['allowed_channels'] = [
                int(ch) for ch in yaml_config['allowed_channels']
            ]

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
