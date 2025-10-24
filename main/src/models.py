"""Data models for Bitaxe API responses and database records."""

from pydantic import BaseModel, Field, computed_field, field_validator
from datetime import datetime
from typing import Optional, Union


class SystemInfo(BaseModel):
    """System information from /api/system/info endpoint."""

    # Performance Metrics
    hashRate: float = Field(alias="hashRate")
    expectedHashrate: Optional[float] = Field(None, alias="expectedHashrate")
    power: float
    voltage: float
    current: float

    # ASIC Configuration
    frequency: int
    coreVoltage: int = Field(alias="coreVoltage")
    coreVoltageActual: Optional[int] = Field(None, alias="coreVoltageActual")
    overclockEnabled: Optional[int] = Field(None, alias="overclockEnabled")

    # Thermal Monitoring
    temp: float
    temp2: Optional[float] = None
    vrTemp: float = Field(alias="vrTemp")
    fanspeed: int
    fanrpm: int
    autofanspeed: Optional[int] = None

    # Mining Statistics
    sharesAccepted: int = Field(alias="sharesAccepted")
    sharesRejected: int = Field(alias="sharesRejected")
    uptimeSeconds: int = Field(alias="uptimeSeconds")
    bestDiff: Optional[float] = Field(None, alias="bestDiff")
    bestSessionDiff: Optional[float] = Field(None, alias="bestSessionDiff")

    @field_validator('bestDiff', 'bestSessionDiff', mode='before')
    @classmethod
    def parse_difficulty(cls, v: Union[str, float, None]) -> Optional[float]:
        """Parse difficulty values that may be formatted strings.

        Handles formats like:
        - "6.13 M" -> 6130000.0
        - "27.21M" -> 27210000.0
        - 12345.67 -> 12345.67
        """
        if v is None or v == "":
            return None

        if isinstance(v, (int, float)):
            return float(v)

        if isinstance(v, str):
            # Remove spaces and convert to uppercase
            v = v.strip().upper()

            # Handle suffixes
            multiplier = 1.0
            if v.endswith('K'):
                multiplier = 1_000
                v = v[:-1]
            elif v.endswith('M'):
                multiplier = 1_000_000
                v = v[:-1]
            elif v.endswith('G'):
                multiplier = 1_000_000_000
                v = v[:-1]
            elif v.endswith('T'):
                multiplier = 1_000_000_000_000
                v = v[:-1]

            try:
                return float(v.strip()) * multiplier
            except ValueError:
                return None

        return None

    # Pool Configuration
    stratumURL: Optional[str] = Field(None, alias="stratumURL")
    stratumPort: Optional[int] = Field(None, alias="stratumPort")
    stratumUser: Optional[str] = Field(None, alias="stratumUser")
    poolDifficulty: Optional[float] = Field(None, alias="poolDifficulty")

    # Device Information
    hostname: str
    ASICModel: str = Field(alias="ASICModel")
    version: Optional[str] = None
    ssid: Optional[str] = None
    ipv4: Optional[str] = None
    wifiRSSI: Optional[int] = Field(None, alias="wifiRSSI")

    @computed_field
    @property
    def efficiency_jth(self) -> float:
        """Calculate J/TH (Joules per Terahash) efficiency.

        Lower is better. Formula: Power(W) / (Hashrate(GH/s) / 1000)
        """
        if self.hashRate == 0:
            return 0.0
        return self.power / (self.hashRate / 1000.0)

    @computed_field
    @property
    def efficiency_ghw(self) -> float:
        """Calculate GH/W (Gigahash per Watt) efficiency.

        Higher is better. Formula: Hashrate(GH/s) / Power(W)
        """
        if self.power == 0:
            return 0.0
        return self.hashRate / self.power

    class Config:
        populate_by_name = True


class ClockConfig(BaseModel):
    """Clock configuration (frequency + voltage combination)."""

    id: Optional[int] = None
    frequency: int  # MHz
    core_voltage: int  # mV

    def __str__(self) -> str:
        return f"{self.frequency}MHz@{self.core_voltage}mV"


class PerformanceMetric(BaseModel):
    """Performance metric record for database storage."""

    device_id: str
    timestamp: datetime
    config_id: int

    # Performance
    hashrate: float
    power: float
    voltage: float
    current: float

    # Thermal
    asic_temp: float
    vreg_temp: float
    fan_speed: int
    fan_rpm: int

    # Mining Stats
    shares_accepted: int
    shares_rejected: int
    uptime: int

    # Calculated Metrics
    efficiency_jth: float
    efficiency_ghw: float

    # Difficulty Stats
    best_diff: Optional[float] = None
    best_session_diff: Optional[float] = None

    @classmethod
    def from_system_info(
        cls,
        device_id: str,
        config_id: int,
        info: SystemInfo
    ) -> "PerformanceMetric":
        """Create PerformanceMetric from SystemInfo response."""
        return cls(
            device_id=device_id,
            timestamp=datetime.now(),
            config_id=config_id,
            hashrate=info.hashRate,
            power=info.power,
            voltage=info.voltage,
            current=info.current,
            asic_temp=info.temp,
            vreg_temp=info.vrTemp,
            fan_speed=info.fanspeed,
            fan_rpm=info.fanrpm,
            shares_accepted=info.sharesAccepted,
            shares_rejected=info.sharesRejected,
            uptime=info.uptimeSeconds,
            efficiency_jth=info.efficiency_jth,
            efficiency_ghw=info.efficiency_ghw,
            best_diff=info.bestDiff,
            best_session_diff=info.bestSessionDiff
        )
