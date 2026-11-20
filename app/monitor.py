"""Bucle de monitoreo en segundo plano y detección de incidentes."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import AppConfig
from app.db import Database
from app.probes import (
    PingResult,
    TcpResult,
    run_dns_check,
    run_mikrotik_api_traffic_check,
    run_mikrotik_traffic_check,
    run_ping,
    run_tcp_check,
    run_traceroute,
)

logger = logging.getLogger("net_monitor.worker")


class MonitorWorker:
    """Ejecuta sondas de red periódicas y persiste métricas e incidentes en PostgreSQL."""

    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status: dict[str, str] = {}
        self._last_traceroute_at: dict[str, float] = {}
        self._last_cleanup_at: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="monitor-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "Worker de monitoreo iniciado (intervalo=%ss)",
            self.config.monitoring.interval_seconds,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Worker de monitoreo detenido.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            try:
                self.run_once()
            except Exception:
                logger.exception("Error inesperado en ciclo de monitoreo")

            elapsed = time.monotonic() - cycle_start
            sleep_for = max(1.0, self.config.monitoring.interval_seconds - elapsed)
            self._stop_event.wait(timeout=sleep_for)

    def run_once(self) -> None:
        now_mono = time.monotonic()
        ping_targets = [t for t in self.config.ping_targets if t.enabled]
        tcp_targets = [t for t in self.config.tcp_targets if t.enabled]
        dns_targets = [t for t in self.config.dns_targets if t.enabled]

        max_workers = max(4, min(16, len(ping_targets) + len(tcp_targets)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            ping_futures = [
                pool.submit(
                    run_ping,
                    t,
                    self.config.monitoring.ping_count,
                    self.config.monitoring.ping_timeout_seconds,
                    self.config.thresholds,
                )
                for t in ping_targets
            ]
            tcp_futures = [
                pool.submit(run_tcp_check, t, self.config.thresholds.tcp_warn_ms)
                for t in tcp_targets
            ]

            for fut in ping_futures:
                res: PingResult = fut.result()
                self.db.insert_ping_sample(res)
                self._handle_ping_incident(res, now_mono)

            for fut in tcp_futures:
                res_tcp: TcpResult = fut.result()
                self.db.insert_tcp_check(res_tcp)
                self._handle_tcp_incident(res_tcp, now_mono)

        for dns_t in dns_targets:
            dns_res = run_dns_check(dns_t)
            self.db.insert_dns_check(dns_res)

        if self.config.mikrotik.enabled:
            try:
                mt = self.config.mikrotik
                if mt.mode == "api" and mt.password:
                    wan_samples = run_mikrotik_api_traffic_check(
                        host=mt.host,
                        username=mt.username,
                        password=mt.password,
                        interfaces=mt.interfaces,
                        port=mt.port,
                        use_ssl=mt.use_ssl,
                    )
                else:
                    wan_samples = run_mikrotik_traffic_check(
                        mt.ssh_host,
                        mt.interfaces,
                        mt.timeout_seconds,
                    )
                for ws in wan_samples:
                    self.db.insert_wan_traffic(ws)
            except Exception as exc:
                logger.warning("No se pudo consultar tráfico WAN en MikroTik: %s", exc)

        if now_mono - self._last_cleanup_at >= 86400:
            try:
                deleted = self.db.cleanup_old_records(self.config.database.retention_days)
                self._last_cleanup_at = now_mono
                logger.info("Limpieza de retención ejecutada: %s", deleted)
            except Exception:
                logger.exception("Error ejecutando limpieza de retención")

    def _maybe_capture_traceroute(
        self, key: str, host: str, now_mono: float
    ) -> tuple[str | None, str | None]:
        cooldown = self.config.monitoring.traceroute_cooldown_seconds
        last_ts = self._last_traceroute_at.get(key, 0.0)
        if now_mono - last_ts < cooldown:
            return None, None
        self._last_traceroute_at[key] = now_mono
        tool, output = run_traceroute(host)
        return tool, output

    def _handle_ping_incident(self, res: PingResult, now_mono: float) -> None:
        key = f"ping:{res.target_name}"
        prev = self._last_status.get(key, "ok")
        self._last_status[key] = res.status

        if res.status == "ok":
            return

        # Registrar incidente en transición de estado o si pasó el cooldown
        last_trace = self._last_traceroute_at.get(key, 0.0)
        cooldown = self.config.monitoring.traceroute_cooldown_seconds
        should_record = (prev == "ok") or (prev != res.status) or (now_mono - last_trace >= cooldown)

        if not should_record:
            return

        tool, output = self._maybe_capture_traceroute(key, res.host, now_mono)
        self.db.insert_incident(
            target_name=res.target_name,
            host=res.host,
            category=res.category,
            severity=res.status,
            reason=res.reason or f"Estado {res.status}",
            loss_pct=res.loss_pct,
            avg_ms=res.avg_ms,
            jitter_ms=res.jitter_ms,
            traceroute_tool=tool,
            traceroute_output=output,
        )
        logger.warning(
            "Incidente [%s] %s (%s): %s",
            res.status.upper(),
            res.target_name,
            res.host,
            res.reason,
        )

    def _handle_tcp_incident(self, res: TcpResult, now_mono: float) -> None:
        key = f"tcp:{res.target_name}:{res.port}"
        prev = self._last_status.get(key, "ok")
        self._last_status[key] = res.status

        if res.status == "ok":
            return

        last_trace = self._last_traceroute_at.get(key, 0.0)
        cooldown = self.config.monitoring.traceroute_cooldown_seconds
        should_record = (prev == "ok") or (prev != res.status) or (now_mono - last_trace >= cooldown)

        if not should_record:
            return

        tool, output = self._maybe_capture_traceroute(key, res.host, now_mono)
        self.db.insert_incident(
            target_name=f"{res.target_name} (:{res.port})",
            host=res.host,
            category="california",
            severity=res.status,
            reason=res.reason or f"Puerto {res.port} {res.status}",
            avg_ms=res.connect_ms,
            traceroute_tool=tool,
            traceroute_output=output,
        )
        logger.warning(
            "Incidente TCP [%s] %s (%s:%s): %s",
            res.status.upper(),
            res.target_name,
            res.host,
            res.port,
            res.reason,
        )
