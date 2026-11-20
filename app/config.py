"""Configuración tipada para el servicio de monitoreo de red."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    dsn: str = "postgresql://netmonitor:netmonitor@localhost:5432/net_monitor"
    retention_days: int = Field(default=60, ge=1)


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class MonitoringConfig(BaseModel):
    interval_seconds: int = Field(default=30, ge=5)
    ping_count: int = Field(default=5, ge=1, le=20)
    ping_timeout_seconds: int = Field(default=2, ge=1, le=10)
    traceroute_cooldown_seconds: int = Field(default=300, ge=30)
    night_start_hour: int = Field(default=19, ge=0, le=23)
    night_end_hour: int = Field(default=7, ge=0, le=23)


class ThresholdsConfig(BaseModel):
    latency_warn_ms: float = Field(default=180.0, gt=0)
    jitter_warn_ms: float = Field(default=30.0, gt=0)
    loss_warn_pct: float = Field(default=5.0, ge=0, le=100)
    tcp_warn_ms: float = Field(default=500.0, gt=0)


class PingTarget(BaseModel):
    name: str
    host: str
    category: Literal["lan", "isp", "internet", "california", "custom"] = "custom"
    enabled: bool = True
    latency_warn_ms: Optional[float] = None
    jitter_warn_ms: Optional[float] = None
    loss_warn_pct: Optional[float] = None


class TcpTarget(BaseModel):
    name: str
    host: str
    port: int = Field(ge=1, le=65535)
    service_name: str = "TCP"
    timeout_seconds: float = Field(default=3.0, gt=0)
    enabled: bool = True


class DnsTarget(BaseModel):
    domain: str
    timeout_seconds: float = Field(default=3.0, gt=0)
    enabled: bool = True


class MikrotikConfig(BaseModel):
    enabled: bool = False
    mode: Literal["api", "ssh"] = "api"
    host: str = "10.1.0.1"
    port: int = Field(default=8728, ge=1, le=65535)
    username: str = "netmonitor"
    password: str = ""
    use_ssl: bool = False
    ssh_host: str = "hex"
    interfaces: list[str] = Field(default_factory=lambda: ["pppoe-out1", "ether2"])
    timeout_seconds: int = Field(default=6, ge=2, le=30)


class AppConfig(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    mikrotik: MikrotikConfig = Field(default_factory=MikrotikConfig)
    ping_targets: list[PingTarget] = Field(default_factory=list)
    tcp_targets: list[TcpTarget] = Field(default_factory=list)
    dns_targets: list[DnsTarget] = Field(default_factory=list)


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Carga configuración desde JSON y aplica overrides de variables de entorno."""
    env_path = os.getenv("NET_MONITOR_CONFIG")
    resolved_path = Path(config_path or env_path or "config.json")

    if not resolved_path.exists():
        fallback = resolved_path.parent / "config.example.json"
        if fallback.exists():
            resolved_path = fallback
        else:
            raise FileNotFoundError(
                f"No se encontró archivo de configuración en {resolved_path}"
            )

    raw_data = json.loads(resolved_path.read_text(encoding="utf-8"))
    cfg = AppConfig.model_validate(raw_data)

    env_dsn = os.getenv("DATABASE_URL")
    if env_dsn:
        cfg.database.dsn = env_dsn

    return cfg
