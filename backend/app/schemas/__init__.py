import ipaddress
import json
import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

# Даты хранятся в UTC без tzinfo — отдаём их с суффиксом Z
UTCDatetime = Annotated[
    datetime, PlainSerializer(lambda d: d.isoformat(timespec="seconds") + "Z", return_type=str)
]

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$")


def is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value.strip())
        return True
    except ValueError:
        return False


def normalize_ip(value: str) -> str:
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError as e:
        raise ValueError(f"Некорректный IPv4: {value}") from e


def normalize_ip_list(values: list[str]) -> list[str]:
    result: list[str] = []
    for v in values:
        if not v or not v.strip():
            continue
        ip = normalize_ip(v)
        if ip not in result:
            result.append(ip)
    return result


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------ auth
class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=64)


# ------------------------------------------------------------ domains
class DomainIPOut(ORM):
    id: int
    ip: str
    position: int
    is_blocked: bool | None
    blocked_since: UTCDatetime | None
    last_checked_at: UTCDatetime | None
    last_error: str | None
    details: dict[str, Any] | None = None

    @field_validator("details", mode="before")
    @classmethod
    def _parse_details(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return None
        return v


class DomainOut(ORM):
    id: int
    name: str
    kind: str
    source: str
    check_port: int | None
    enabled: bool
    auto_switch: bool
    notes: str
    current_ip: str | None
    status: str
    status_message: str
    last_checked_at: UTCDatetime | None
    last_switch_at: UTCDatetime | None
    created_at: UTCDatetime
    ips: list[DomainIPOut]
    nodes: list[str] = []


class DomainCreate(BaseModel):
    name: str
    ips: list[str] = []
    auto_switch: bool = True
    enabled: bool = True
    notes: str = ""

    check_port: int | None = Field(None, ge=1, le=65535)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        for prefix in ("https://", "http://"):
            if v.startswith(prefix):
                v = v[len(prefix):]
        v = v.split("/")[0]
        if is_ipv4(v) or DOMAIN_RE.match(v):
            return v
        raise ValueError("Укажите домен (sub.example.com) или IPv4-адрес")

    @field_validator("ips")
    @classmethod
    def _ips(cls, v: list[str]) -> list[str]:
        return normalize_ip_list(v)


class DomainUpdate(BaseModel):
    enabled: bool | None = None
    auto_switch: bool | None = None
    notes: str | None = None
    # null — использовать порт из общих настроек
    check_port: int | None = Field(None, ge=1, le=65535)


class DomainIPsUpdate(BaseModel):
    ips: list[str]

    @field_validator("ips")
    @classmethod
    def _ips(cls, v: list[str]) -> list[str]:
        return normalize_ip_list(v)


class SwitchIn(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def _ip(cls, v: str) -> str:
        return normalize_ip(v)


# ------------------------------------------------------------ nodes
class NodeOut(ORM):
    uuid: str
    name: str
    address: str
    port: int | None
    country_code: str
    is_connected: bool
    is_disabled: bool
    is_connecting: bool
    users_online: int | None
    xray_version: str | None
    last_status_message: str | None
    offline_since: UTCDatetime | None
    updated_at: UTCDatetime
    speed_bps: int | None = None
    baseline_bps: int | None = None
    speed_drop_since: UTCDatetime | None = None
    domain_id: int | None = None
    domain_status: str | None = None


# ------------------------------------------------------------ events
class EventOut(ORM):
    id: int
    created_at: UTCDatetime
    type: str
    level: str
    title: str
    message: str
    domain: str | None
    node: str | None
    ip: str | None


class EventsPage(BaseModel):
    items: list[EventOut]
    total: int


# ------------------------------------------------------------ investigations
class InvestigationOut(ORM):
    id: int
    domain_id: int
    domain_name: str
    node_name: str
    ip: str | None
    reason: str
    status: str
    checks_total: int
    checks_done: int
    blocked_count: int
    attempts: int
    results: list[dict[str, Any]] = []
    summary: str
    started_at: UTCDatetime
    next_check_at: UTCDatetime | None
    finished_at: UTCDatetime | None

    @field_validator("results", mode="before")
    @classmethod
    def _parse_results(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except ValueError:
                return []
        return v or []


# ------------------------------------------------------------ settings
class SettingsUpdate(BaseModel):
    node_poll_interval_seconds: int | None = Field(None, ge=10, le=3600)
    auto_import_nodes: bool | None = None
    speed_drop_percent: int | None = Field(None, ge=10, le=100)
    speed_window_minutes: int | None = Field(None, ge=1, le=60)
    speed_baseline_hours: int | None = Field(None, ge=1, le=48)
    speed_min_baseline_mbps: float | None = Field(None, ge=0, le=100000)
    speed_confirm_minutes: int | None = Field(None, ge=0, le=240)
    investigation_checks: int | None = Field(None, ge=1, le=10)
    investigation_interval_minutes: int | None = Field(None, ge=1, le=720)
    investigation_cooldown_minutes: int | None = Field(None, ge=0, le=10080)
    auto_switch_enabled: bool | None = None
    tcp_check_port: int | None = Field(None, ge=1, le=65535)
    latencylab_fail_percent: int | None = Field(None, ge=1, le=100)
    enabled_checkers: list[str] | None = None
    checker_delay_ms: int | None = Field(None, ge=0, le=60000)
    daily_summary_enabled: bool | None = None
    daily_summary_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    notify: dict[str, bool] | None = None
    events_retention_days: int | None = Field(None, ge=1, le=3650)


class IntegrationsUpdate(BaseModel):
    """None — не менять, пустая строка — удалить значение из панели."""
    values: dict[str, str | None]
