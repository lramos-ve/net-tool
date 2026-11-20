"""Pruebas de red: ping (latencia/jitter/pérdida), puertos TCP, DNS y traceroute/mtr."""

from __future__ import annotations

import platform
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from app.config import DnsTarget, PingTarget, TcpTarget, ThresholdsConfig

IS_WINDOWS = platform.system().lower() == "windows"

_PACKET_LOSS_RE = re.compile(
    r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received.*?(\d+(?:\.\d+)?)%\s+packet loss",
    re.IGNORECASE | re.DOTALL,
)
_RTT_RE = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
    r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms",
    re.IGNORECASE,
)


@dataclass
class PingResult:
    target_name: str
    host: str
    category: str
    packets_sent: int
    packets_received: int
    loss_pct: float
    min_ms: Optional[float]
    avg_ms: Optional[float]
    max_ms: Optional[float]
    jitter_ms: Optional[float]
    status: str  # ok | degraded | down
    reason: Optional[str] = None
    raw_error: Optional[str] = None


@dataclass
class TcpResult:
    target_name: str
    host: str
    port: int
    service_name: str
    is_open: bool
    connect_ms: Optional[float]
    status: str  # ok | degraded | down
    reason: Optional[str] = None
    error_msg: Optional[str] = None


@dataclass
class DnsResult:
    domain: str
    resolved_ips: str
    resolve_ms: Optional[float]
    success: bool
    error_msg: Optional[str] = None


@dataclass
class WanTrafficResult:
    interface_name: str
    rx_mbps: float
    tx_mbps: float
    rx_drops_ps: int
    tx_queue_drops_ps: int


def parse_ping_output(output: str, expected_sent: int) -> dict:
    """Extrae paquetes enviados/recibidos, % pérdida y rtt min/avg/max/jitter."""
    sent = expected_sent
    received = 0
    loss_pct = 100.0

    pkt_match = _PACKET_LOSS_RE.search(output)
    if pkt_match:
        sent = int(pkt_match.group(1))
        received = int(pkt_match.group(2))
        loss_pct = float(pkt_match.group(3))

    min_ms = avg_ms = max_ms = jitter_ms = None
    rtt_match = _RTT_RE.search(output)
    if rtt_match:
        min_ms = round(float(rtt_match.group(1)), 2)
        avg_ms = round(float(rtt_match.group(2)), 2)
        max_ms = round(float(rtt_match.group(3)), 2)
        jitter_ms = round(float(rtt_match.group(4)), 2)

    return {
        "packets_sent": sent,
        "packets_received": received,
        "loss_pct": round(loss_pct, 2),
        "min_ms": min_ms,
        "avg_ms": avg_ms,
        "max_ms": max_ms,
        "jitter_ms": jitter_ms,
    }


def classify_ping_status(
    packets_received: int,
    loss_pct: float,
    avg_ms: Optional[float],
    jitter_ms: Optional[float],
    target: PingTarget,
    thresholds: ThresholdsConfig,
) -> tuple[str, Optional[str]]:
    """Clasifica el resultado de ping en ok, degraded o down."""
    if packets_received == 0 or loss_pct >= 100.0:
        return "down", "100% pérdida de paquetes (sin respuesta)"

    lat_warn = target.latency_warn_ms or thresholds.latency_warn_ms
    jit_warn = target.jitter_warn_ms or thresholds.jitter_warn_ms
    loss_warn = (
        target.loss_warn_pct
        if target.loss_warn_pct is not None
        else thresholds.loss_warn_pct
    )

    reasons: list[str] = []
    if loss_pct > loss_warn:
        reasons.append(f"Pérdida {loss_pct:.1f}% (> {loss_warn:.1f}%)")
    if avg_ms is not None and avg_ms > lat_warn:
        reasons.append(f"Latencia {avg_ms:.1f} ms (> {lat_warn:.1f} ms)")
    if jitter_ms is not None and jitter_ms > jit_warn:
        reasons.append(f"Jitter {jitter_ms:.1f} ms (> {jit_warn:.1f} ms)")

    if reasons:
        return "degraded", "; ".join(reasons)
    return "ok", None


def run_ping(
    target: PingTarget,
    count: int,
    timeout_seconds: int,
    thresholds: ThresholdsConfig,
) -> PingResult:
    """Ejecuta ping ICMP contra un destino y devuelve métricas detalladas."""
    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_seconds * 1000), target.host]
    else:
        cmd = [
            "ping",
            "-c",
            str(count),
            "-i",
            "0.2",
            "-W",
            str(timeout_seconds),
            "-n",
            target.host,
        ]

    total_timeout = max(5, count * timeout_seconds + 3)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=total_timeout,
        )
        combined = f"{proc.stdout}\n{proc.stderr}".strip()
        metrics = parse_ping_output(combined, count)
        status, reason = classify_ping_status(
            packets_received=metrics["packets_received"],
            loss_pct=metrics["loss_pct"],
            avg_ms=metrics["avg_ms"],
            jitter_ms=metrics["jitter_ms"],
            target=target,
            thresholds=thresholds,
        )
        raw_error = None
        if status == "down" and proc.stderr.strip():
            raw_error = proc.stderr.strip()[:500]
        return PingResult(
            target_name=target.name,
            host=target.host,
            category=target.category,
            packets_sent=metrics["packets_sent"],
            packets_received=metrics["packets_received"],
            loss_pct=metrics["loss_pct"],
            min_ms=metrics["min_ms"],
            avg_ms=metrics["avg_ms"],
            max_ms=metrics["max_ms"],
            jitter_ms=metrics["jitter_ms"],
            status=status,
            reason=reason,
            raw_error=raw_error,
        )
    except subprocess.TimeoutExpired:
        return PingResult(
            target_name=target.name,
            host=target.host,
            category=target.category,
            packets_sent=count,
            packets_received=0,
            loss_pct=100.0,
            min_ms=None,
            avg_ms=None,
            max_ms=None,
            jitter_ms=None,
            status="down",
            reason=f"Timeout ejecutando ping ({total_timeout}s)",
            raw_error="TimeoutExpired",
        )
    except Exception as exc:
        return PingResult(
            target_name=target.name,
            host=target.host,
            category=target.category,
            packets_sent=count,
            packets_received=0,
            loss_pct=100.0,
            min_ms=None,
            avg_ms=None,
            max_ms=None,
            jitter_ms=None,
            status="down",
            reason=f"Error ejecutando ping: {exc}",
            raw_error=str(exc)[:500],
        )


def run_tcp_check(target: TcpTarget, tcp_warn_ms: float) -> TcpResult:
    """Mide apertura y latencia de conexión TCP (útil para puertos iVMS/RTSP)."""
    start = time.perf_counter()
    try:
        with socket.create_connection(
            (target.host, target.port), timeout=target.timeout_seconds
        ):
            elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        if elapsed_ms > tcp_warn_ms:
            return TcpResult(
                target_name=target.name,
                host=target.host,
                port=target.port,
                service_name=target.service_name,
                is_open=True,
                connect_ms=elapsed_ms,
                status="degraded",
                reason=f"Puerto {target.port} lento ({elapsed_ms:.1f} ms > {tcp_warn_ms:.1f} ms)",
            )
        return TcpResult(
            target_name=target.name,
            host=target.host,
            port=target.port,
            service_name=target.service_name,
            is_open=True,
            connect_ms=elapsed_ms,
            status="ok",
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return TcpResult(
            target_name=target.name,
            host=target.host,
            port=target.port,
            service_name=target.service_name,
            is_open=False,
            connect_ms=elapsed_ms,
            status="down",
            reason=f"Puerto {target.port} cerrado/timeout ({exc})",
            error_msg=str(exc)[:500],
        )


def run_dns_check(target: DnsTarget) -> DnsResult:
    """Mide resolución DNS de un dominio."""
    start = time.perf_counter()
    prev_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(target.timeout_seconds)
        infos = socket.getaddrinfo(target.domain, None, proto=socket.IPPROTO_TCP)
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        ips = sorted({info[4][0] for info in infos})
        return DnsResult(
            domain=target.domain,
            resolved_ips=", ".join(ips),
            resolve_ms=elapsed_ms,
            success=True,
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return DnsResult(
            domain=target.domain,
            resolved_ips="",
            resolve_ms=elapsed_ms,
            success=False,
            error_msg=str(exc)[:500],
        )
    finally:
        socket.setdefaulttimeout(prev_timeout)


def run_traceroute(host: str) -> tuple[str, str]:
    """Captura traza de ruta usando mtr, traceroute o tracepath."""
    candidates: list[tuple[str, list[str]]] = []
    if shutil.which("mtr"):
        candidates.append(("mtr", ["mtr", "-r", "-c", "5", "-n", host]))
    if shutil.which("traceroute"):
        candidates.append(("traceroute", ["traceroute", "-n", "-w", "2", "-q", "1", host]))
    if shutil.which("tracepath"):
        candidates.append(("tracepath", ["tracepath", "-n", host]))
    if IS_WINDOWS and shutil.which("tracert"):
        candidates.append(("tracert", ["tracert", "-d", "-w", "2000", host]))

    if not candidates:
        return "none", "No se encontró mtr, traceroute ni tracepath en el sistema."

    tool_name, cmd = candidates[0]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
        )
        output = proc.stdout.strip() or proc.stderr.strip() or "(sin salida)"
        return tool_name, output[:8000]
    except subprocess.TimeoutExpired:
        return tool_name, "Timeout al capturar traza de ruta (35s)."
    except Exception as exc:
        return tool_name, f"Error ejecutando {tool_name}: {exc}"


_RATE_RE = re.compile(r"^([\d.]+)\s*(bps|kbps|mbps|gbps)$", re.IGNORECASE)


def _parse_rate_to_mbps(token: str) -> float:
    m = _RATE_RE.match(token.strip())
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "bps":
        return round(val / 1_000_000.0, 4)
    if unit == "kbps":
        return round(val / 1_000.0, 3)
    if unit == "mbps":
        return round(val, 2)
    if unit == "gbps":
        return round(val * 1000.0, 2)
    return 0.0


def parse_mikrotik_monitor_traffic(output: str) -> list[WanTrafficResult]:
    """Parsea la salida de `/interface monitor-traffic ... once` de RouterOS."""
    kv: dict[str, list[str]] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if ":" not in line or line.startswith(";;;"):
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        tokens = val.strip().split()
        if tokens:
            kv[key] = tokens

    names = kv.get("name", [])
    rx_rates = kv.get("rx-bits-per-second", [])
    tx_rates = kv.get("tx-bits-per-second", [])
    rx_drops = kv.get("rx-drops-per-second", [])
    tx_qdrops = kv.get("tx-queue-drops-per-second", [])

    results: list[WanTrafficResult] = []
    for idx, iface in enumerate(names):
        rx_mbps = _parse_rate_to_mbps(rx_rates[idx]) if idx < len(rx_rates) else 0.0
        tx_mbps = _parse_rate_to_mbps(tx_rates[idx]) if idx < len(tx_rates) else 0.0
        rx_d = int(rx_drops[idx]) if idx < len(rx_drops) and rx_drops[idx].isdigit() else 0
        tx_qd = int(tx_qdrops[idx]) if idx < len(tx_qdrops) and tx_qdrops[idx].isdigit() else 0
        results.append(
            WanTrafficResult(
                interface_name=iface,
                rx_mbps=rx_mbps,
                tx_mbps=tx_mbps,
                rx_drops_ps=rx_d,
                tx_queue_drops_ps=tx_qd,
            )
        )
    return results


def run_mikrotik_traffic_check(
    ssh_host: str, interfaces: list[str], timeout_seconds: int = 6
) -> list[WanTrafficResult]:
    """Consulta tráfico WAN actual en el MikroTik por SSH (solo lectura)."""
    if not interfaces:
        return []
    iface_arg = ",".join(interfaces)
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        ssh_host,
        f"/interface monitor-traffic {iface_arg} once",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds + 4,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"SSH exit code {proc.returncode}")
    return parse_mikrotik_monitor_traffic(proc.stdout)


def run_mikrotik_api_traffic_check(
    host: str,
    username: str,
    password: str,
    interfaces: list[str],
    port: int = 8728,
    use_ssl: bool = False,
) -> list[WanTrafficResult]:
    """Consulta tráfico WAN en el MikroTik usando la API binaria (puerto 8728/8729)."""
    if not interfaces:
        return []
    import routeros_api  # import local para mantener pruebas rápidas

    pool = routeros_api.RouterOsApiPool(
        host=host,
        username=username,
        password=password,
        port=port,
        use_ssl=use_ssl,
        ssl_verify=False,
        plaintext_login=True,
    )
    try:
        api = pool.get_api()
        resource = api.get_resource("/interface")
        raw_rows = resource.call(
            "monitor-traffic",
            {"interface": ",".join(interfaces), "once": ""},
        )
        results: list[WanTrafficResult] = []
        for row in raw_rows:
            iface = row.get("name", "")
            if not iface:
                continue
            rx_bps = float(row.get("rx-bits-per-second", 0) or 0)
            tx_bps = float(row.get("tx-bits-per-second", 0) or 0)
            rx_drops = int(row.get("rx-drops-per-second", 0) or 0)
            tx_qdrops = int(row.get("tx-queue-drops-per-second", 0) or 0)
            results.append(
                WanTrafficResult(
                    interface_name=iface,
                    rx_mbps=round(rx_bps / 1_000_000.0, 2),
                    tx_mbps=round(tx_bps / 1_000_000.0, 2),
                    rx_drops_ps=rx_drops,
                    tx_queue_drops_ps=tx_qdrops,
                )
            )
        return results
    finally:
        pool.disconnect()


def run_mikrotik_api_traceroute(
    host: str,
    username: str,
    password: str,
    target: str,
    port: int = 8728,
    use_ssl: bool = False,
    routing_table: Optional[str] = None,
    count: int = 2,
) -> list[dict]:
    """Ejecuta /tool/traceroute en el MikroTik vía API (requiere política 'test')."""
    import routeros_api

    pool = routeros_api.RouterOsApiPool(
        host=host,
        username=username,
        password=password,
        port=port,
        use_ssl=use_ssl,
        ssl_verify=False,
        plaintext_login=True,
    )
    try:
        api = pool.get_api()
        tool_res = api.get_resource("/tool")
        params: dict[str, str] = {
            "address": target,
            "count": str(count),
            "max-hops": "20",
        }
        if routing_table:
            params["routing-table"] = routing_table
        rows = tool_res.call("traceroute", params)
        hops: list[dict] = []
        for idx, row in enumerate(rows, start=1):
            hops.append(
                {
                    "Salto": row.get("hop", idx),
                    "IP": row.get("address", "*") or "*",
                    "Pérdida (%)": row.get("loss", ""),
                    "Prom (ms)": row.get("avg", ""),
                    "Mín (ms)": row.get("best", ""),
                    "Máx (ms)": row.get("worst", ""),
                }
            )
        return hops
    finally:
        pool.disconnect()
