"""Pruebas unitarias para sondas, configuración, rangos horarios y helpers del dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import PingTarget, ThresholdsConfig, load_config
from app.dashboard import status_label
from app.probes import (
    classify_ping_status,
    parse_mikrotik_monitor_traffic,
    parse_ping_output,
)
from app.timewindow import choose_bucket_seconds, resolve_time_window


def test_parse_ping_iputils_ok():
    sample = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=45.1 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=47.3 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 804ms
rtt min/avg/max/mdev = 44.100/46.200/49.500/1.850 ms
"""
    res = parse_ping_output(sample, 5)
    assert res["packets_sent"] == 5
    assert res["packets_received"] == 5
    assert res["loss_pct"] == 0.0
    assert res["min_ms"] == 44.1
    assert res["avg_ms"] == 46.2
    assert res["max_ms"] == 49.5
    assert res["jitter_ms"] == 1.85


def test_parse_ping_100_loss():
    sample = """--- 192.168.100.1 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4096ms
"""
    res = parse_ping_output(sample, 5)
    assert res["packets_received"] == 0
    assert res["loss_pct"] == 100.0
    assert res["avg_ms"] is None


def test_classify_ping_status():
    target = PingTarget(name="California", host="8.8.4.4", category="california")
    thresholds = ThresholdsConfig(
        latency_warn_ms=180.0, jitter_warn_ms=30.0, loss_warn_pct=5.0
    )

    assert classify_ping_status(5, 0.0, 90.0, 5.0, target, thresholds)[0] == "ok"

    status, reason = classify_ping_status(4, 20.0, 210.0, 40.0, target, thresholds)
    assert status == "degraded"
    assert "Pérdida" in reason and "Latencia" in reason and "Jitter" in reason

    status_down, _ = classify_ping_status(0, 100.0, None, None, target, thresholds)
    assert status_down == "down"


def test_load_config_example(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/testdb")
    cfg = load_config(Path("config.example.json"))
    assert cfg.database.dsn == "postgresql://u:p@db:5432/testdb"
    assert len(cfg.ping_targets) >= 2


def test_resolve_time_window_and_buckets():
    cfg = load_config(Path("config.example.json"))
    s, e = resolve_time_window(cfg, preset="last_night")
    assert s < e
    assert s.tzinfo == timezone.utc

    assert choose_bucket_seconds(
        datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc),
    ) == 60
    assert choose_bucket_seconds(
        datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc),
    ) == 120


def test_status_label():
    assert "OK" in status_label("ok")
    assert "DEGRADADO" in status_label("degraded")
    assert "CAÍDO" in status_label("down")


def test_parse_mikrotik_monitor_traffic():
    sample = """                         ;;;     Boom            Servitel
                       name:   pppoe-out1   ether2
      rx-packets-per-second:        8 165    4 948
         rx-bits-per-second:     73.8Mbps 50.9Mbps
      tx-bits-per-second:         3.3Mbps  2.6Mbps
        rx-drops-per-second:            0        0
  tx-queue-drops-per-second:            1        0
"""
    res = parse_mikrotik_monitor_traffic(sample)
    assert len(res) == 2
    assert res[0].interface_name == "pppoe-out1"
    assert res[0].rx_mbps == 73.8
    assert res[0].tx_mbps == 3.3
    assert res[0].tx_queue_drops_ps == 1
    assert res[1].interface_name == "ether2"
    assert res[1].rx_mbps == 50.9
