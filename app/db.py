"""Capa de acceso a datos PostgreSQL usando psycopg3 y pool de conexiones."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.probes import DnsResult, PingResult, TcpResult, WanTrafficResult

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ping_samples (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_name TEXT NOT NULL,
    host TEXT NOT NULL,
    category TEXT NOT NULL,
    packets_sent INT NOT NULL,
    packets_received INT NOT NULL,
    loss_pct DOUBLE PRECISION NOT NULL,
    min_ms DOUBLE PRECISION,
    avg_ms DOUBLE PRECISION,
    max_ms DOUBLE PRECISION,
    jitter_ms DOUBLE PRECISION,
    status TEXT NOT NULL,
    raw_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_ping_samples_recorded_at
    ON ping_samples (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_ping_samples_target_time
    ON ping_samples (target_name, recorded_at DESC);

CREATE TABLE IF NOT EXISTS tcp_checks (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INT NOT NULL,
    service_name TEXT NOT NULL,
    is_open BOOLEAN NOT NULL,
    connect_ms DOUBLE PRECISION,
    status TEXT NOT NULL,
    error_msg TEXT
);

CREATE INDEX IF NOT EXISTS idx_tcp_checks_recorded_at
    ON tcp_checks (recorded_at DESC);

CREATE TABLE IF NOT EXISTS dns_checks (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain TEXT NOT NULL,
    resolved_ips TEXT NOT NULL DEFAULT '',
    resolve_ms DOUBLE PRECISION,
    success BOOLEAN NOT NULL,
    error_msg TEXT
);

CREATE INDEX IF NOT EXISTS idx_dns_checks_recorded_at
    ON dns_checks (recorded_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_name TEXT NOT NULL,
    host TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT NOT NULL,
    loss_pct DOUBLE PRECISION,
    avg_ms DOUBLE PRECISION,
    jitter_ms DOUBLE PRECISION,
    traceroute_tool TEXT,
    traceroute_output TEXT
);

CREATE INDEX IF NOT EXISTS idx_incidents_started_at
    ON incidents (started_at DESC);

CREATE TABLE IF NOT EXISTS wan_traffic (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    interface_name TEXT NOT NULL,
    rx_mbps DOUBLE PRECISION NOT NULL,
    tx_mbps DOUBLE PRECISION NOT NULL,
    rx_drops_ps INT NOT NULL DEFAULT 0,
    tx_queue_drops_ps INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wan_traffic_recorded_at
    ON wan_traffic (recorded_at DESC);
"""


class Database:
    """Administra el pool de conexiones y consultas en PostgreSQL."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    def init_schema(self) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()

    def insert_ping_sample(self, sample: PingResult) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ping_samples (
                        target_name, host, category,
                        packets_sent, packets_received, loss_pct,
                        min_ms, avg_ms, max_ms, jitter_ms, status, raw_error
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sample.target_name,
                        sample.host,
                        sample.category,
                        sample.packets_sent,
                        sample.packets_received,
                        sample.loss_pct,
                        sample.min_ms,
                        sample.avg_ms,
                        sample.max_ms,
                        sample.jitter_ms,
                        sample.status,
                        sample.raw_error,
                    ),
                )
            conn.commit()

    def insert_tcp_check(self, check: TcpResult) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tcp_checks (
                        target_name, host, port, service_name,
                        is_open, connect_ms, status, error_msg
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        check.target_name,
                        check.host,
                        check.port,
                        check.service_name,
                        check.is_open,
                        check.connect_ms,
                        check.status,
                        check.error_msg,
                    ),
                )
            conn.commit()

    def insert_dns_check(self, check: DnsResult) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dns_checks (
                        domain, resolved_ips, resolve_ms, success, error_msg
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        check.domain,
                        check.resolved_ips,
                        check.resolve_ms,
                        check.success,
                        check.error_msg,
                    ),
                )
            conn.commit()

    def insert_wan_traffic(self, sample: WanTrafficResult) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO wan_traffic (
                        interface_name, rx_mbps, tx_mbps, rx_drops_ps, tx_queue_drops_ps
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        sample.interface_name,
                        sample.rx_mbps,
                        sample.tx_mbps,
                        sample.rx_drops_ps,
                        sample.tx_queue_drops_ps,
                    ),
                )
            conn.commit()

    def insert_incident(
        self,
        target_name: str,
        host: str,
        category: str,
        severity: str,
        reason: str,
        loss_pct: Optional[float] = None,
        avg_ms: Optional[float] = None,
        jitter_ms: Optional[float] = None,
        traceroute_tool: Optional[str] = None,
        traceroute_output: Optional[str] = None,
    ) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incidents (
                        target_name, host, category, severity, reason,
                        loss_pct, avg_ms, jitter_ms,
                        traceroute_tool, traceroute_output
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        target_name,
                        host,
                        category,
                        severity,
                        reason,
                        loss_pct,
                        avg_ms,
                        jitter_ms,
                        traceroute_tool,
                        traceroute_output,
                    ),
                )
            conn.commit()

    def cleanup_old_records(self, retention_days: int) -> dict[str, int]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted: dict[str, int] = {}
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                for table, col in (
                    ("ping_samples", "recorded_at"),
                    ("tcp_checks", "recorded_at"),
                    ("dns_checks", "recorded_at"),
                    ("wan_traffic", "recorded_at"),
                    ("incidents", "started_at"),
                ):
                    cur.execute(f"DELETE FROM {table} WHERE {col} < %s", (cutoff,))
                    deleted[table] = cur.rowcount
            conn.commit()
        return deleted

    def get_ping_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                target_name,
                host,
                category,
                COUNT(*) AS samples,
                ROUND(AVG(avg_ms)::numeric, 2) AS avg_ms,
                ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY avg_ms))::numeric, 2) AS p95_ms,
                ROUND(MAX(max_ms)::numeric, 2) AS max_ms,
                ROUND(AVG(jitter_ms)::numeric, 2) AS avg_jitter_ms,
                ROUND(AVG(loss_pct)::numeric, 2) AS avg_loss_pct,
                ROUND((100.0 * COUNT(*) FILTER (WHERE status <> 'down') / NULLIF(COUNT(*), 0))::numeric, 2) AS uptime_pct,
                COUNT(*) FILTER (WHERE status = 'degraded') AS degraded_count,
                COUNT(*) FILTER (WHERE status = 'down') AS down_count
            FROM ping_samples
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY target_name, host, category
        ),
        latest AS (
            SELECT DISTINCT ON (target_name)
                target_name,
                recorded_at AS last_seen,
                avg_ms AS last_avg_ms,
                jitter_ms AS last_jitter_ms,
                loss_pct AS last_loss_pct,
                status AS last_status
            FROM ping_samples
            ORDER BY target_name, recorded_at DESC
        )
        SELECT
            w.target_name,
            w.host,
            w.category,
            w.samples,
            w.avg_ms::float8,
            w.p95_ms::float8,
            w.max_ms::float8,
            w.avg_jitter_ms::float8,
            w.avg_loss_pct::float8,
            w.uptime_pct::float8,
            w.degraded_count,
            w.down_count,
            l.last_seen,
            l.last_avg_ms,
            l.last_jitter_ms,
            l.last_loss_pct,
            l.last_status
        FROM window_stats w
        JOIN latest l USING (target_name)
        ORDER BY
            CASE w.category
                WHEN 'lan' THEN 1
                WHEN 'isp' THEN 2
                WHEN 'internet' THEN 3
                WHEN 'california' THEN 4
                ELSE 5
            END,
            w.target_name;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                interface_name,
                COUNT(*) AS samples,
                ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS avg_rx_mbps,
                ROUND(MAX(rx_mbps)::numeric, 2)::float8 AS max_rx_mbps,
                ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS avg_tx_mbps,
                SUM(rx_drops_ps + tx_queue_drops_ps) AS total_drops
            FROM wan_traffic
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY interface_name
        ),
        latest AS (
            SELECT DISTINCT ON (interface_name)
                interface_name,
                rx_mbps AS last_rx_mbps,
                tx_mbps AS last_tx_mbps,
                recorded_at AS last_seen
            FROM wan_traffic
            ORDER BY interface_name, recorded_at DESC
        )
        SELECT w.*, l.last_rx_mbps, l.last_tx_mbps, l.last_seen
        FROM window_stats w
        JOIN latest l USING (interface_name)
        ORDER BY w.interface_name;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_timeseries(
        self, start_dt: datetime, end_dt: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            to_timestamp(
                floor(extract(epoch FROM recorded_at) / %s) * %s
            ) AT TIME ZONE 'UTC' AS bucket_utc,
            interface_name,
            ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS rx_mbps,
            ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS tx_mbps
        FROM wan_traffic
        WHERE recorded_at >= %s AND recorded_at <= %s
        GROUP BY bucket_utc, interface_name
        ORDER BY bucket_utc ASC, interface_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bucket_seconds, bucket_seconds, start_dt, end_dt))
                rows = list(cur.fetchall())
                for row in rows:
                    if row["bucket_utc"] is not None:
                        row["bucket_utc"] = row["bucket_utc"].replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                return rows

    def get_ping_timeseries(
        self, start_dt: datetime, end_dt: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            to_timestamp(
                floor(extract(epoch FROM recorded_at) / %s) * %s
            ) AT TIME ZONE 'UTC' AS bucket_utc,
            target_name,
            category,
            ROUND(AVG(avg_ms)::numeric, 2)::float8 AS avg_ms,
            ROUND(AVG(jitter_ms)::numeric, 2)::float8 AS jitter_ms,
            ROUND(AVG(loss_pct)::numeric, 2)::float8 AS loss_pct
        FROM ping_samples
        WHERE recorded_at >= %s AND recorded_at <= %s
        GROUP BY bucket_utc, target_name, category
        ORDER BY bucket_utc ASC, target_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bucket_seconds, bucket_seconds, start_dt, end_dt))
                rows = list(cur.fetchall())
                for row in rows:
                    if row["bucket_utc"] is not None:
                        row["bucket_utc"] = row["bucket_utc"].replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                return rows

    def get_tcp_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                target_name,
                host,
                port,
                service_name,
                COUNT(*) AS checks,
                ROUND(AVG(connect_ms) FILTER (WHERE is_open)::numeric, 2)::float8 AS avg_connect_ms,
                ROUND((100.0 * COUNT(*) FILTER (WHERE is_open) / NULLIF(COUNT(*), 0))::numeric, 2)::float8 AS success_pct
            FROM tcp_checks
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY target_name, host, port, service_name
        ),
        latest AS (
            SELECT DISTINCT ON (target_name, port)
                target_name,
                port,
                recorded_at AS last_seen,
                is_open AS last_is_open,
                connect_ms AS last_connect_ms,
                status AS last_status,
                error_msg AS last_error
            FROM tcp_checks
            ORDER BY target_name, port, recorded_at DESC
        )
        SELECT
            w.*,
            l.last_seen,
            l.last_is_open,
            l.last_connect_ms,
            l.last_status,
            l.last_error
        FROM window_stats w
        JOIN latest l USING (target_name, port)
        ORDER BY w.target_name, w.port;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                interface_name,
                COUNT(*) AS samples,
                ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS avg_rx_mbps,
                ROUND(MAX(rx_mbps)::numeric, 2)::float8 AS max_rx_mbps,
                ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS avg_tx_mbps,
                SUM(rx_drops_ps + tx_queue_drops_ps) AS total_drops
            FROM wan_traffic
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY interface_name
        ),
        latest AS (
            SELECT DISTINCT ON (interface_name)
                interface_name,
                rx_mbps AS last_rx_mbps,
                tx_mbps AS last_tx_mbps,
                recorded_at AS last_seen
            FROM wan_traffic
            ORDER BY interface_name, recorded_at DESC
        )
        SELECT w.*, l.last_rx_mbps, l.last_tx_mbps, l.last_seen
        FROM window_stats w
        JOIN latest l USING (interface_name)
        ORDER BY w.interface_name;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_timeseries(
        self, start_dt: datetime, end_dt: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            to_timestamp(
                floor(extract(epoch FROM recorded_at) / %s) * %s
            ) AT TIME ZONE 'UTC' AS bucket_utc,
            interface_name,
            ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS rx_mbps,
            ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS tx_mbps
        FROM wan_traffic
        WHERE recorded_at >= %s AND recorded_at <= %s
        GROUP BY bucket_utc, interface_name
        ORDER BY bucket_utc ASC, interface_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bucket_seconds, bucket_seconds, start_dt, end_dt))
                rows = list(cur.fetchall())
                for row in rows:
                    if row["bucket_utc"] is not None:
                        row["bucket_utc"] = row["bucket_utc"].replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                return rows

    def get_dns_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                domain,
                COUNT(*) AS checks,
                ROUND(AVG(resolve_ms) FILTER (WHERE success)::numeric, 2)::float8 AS avg_resolve_ms,
                ROUND((100.0 * COUNT(*) FILTER (WHERE success) / NULLIF(COUNT(*), 0))::numeric, 2)::float8 AS success_pct
            FROM dns_checks
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY domain
        ),
        latest AS (
            SELECT DISTINCT ON (domain)
                domain,
                recorded_at AS last_seen,
                resolved_ips AS last_ips,
                resolve_ms AS last_resolve_ms,
                success AS last_success,
                error_msg AS last_error
            FROM dns_checks
            ORDER BY domain, recorded_at DESC
        )
        SELECT w.*, l.last_seen, l.last_ips, l.last_resolve_ms, l.last_success, l.last_error
        FROM window_stats w
        JOIN latest l USING (domain)
        ORDER BY w.domain;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                interface_name,
                COUNT(*) AS samples,
                ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS avg_rx_mbps,
                ROUND(MAX(rx_mbps)::numeric, 2)::float8 AS max_rx_mbps,
                ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS avg_tx_mbps,
                SUM(rx_drops_ps + tx_queue_drops_ps) AS total_drops
            FROM wan_traffic
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY interface_name
        ),
        latest AS (
            SELECT DISTINCT ON (interface_name)
                interface_name,
                rx_mbps AS last_rx_mbps,
                tx_mbps AS last_tx_mbps,
                recorded_at AS last_seen
            FROM wan_traffic
            ORDER BY interface_name, recorded_at DESC
        )
        SELECT w.*, l.last_rx_mbps, l.last_tx_mbps, l.last_seen
        FROM window_stats w
        JOIN latest l USING (interface_name)
        ORDER BY w.interface_name;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_timeseries(
        self, start_dt: datetime, end_dt: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            to_timestamp(
                floor(extract(epoch FROM recorded_at) / %s) * %s
            ) AT TIME ZONE 'UTC' AS bucket_utc,
            interface_name,
            ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS rx_mbps,
            ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS tx_mbps
        FROM wan_traffic
        WHERE recorded_at >= %s AND recorded_at <= %s
        GROUP BY bucket_utc, interface_name
        ORDER BY bucket_utc ASC, interface_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bucket_seconds, bucket_seconds, start_dt, end_dt))
                rows = list(cur.fetchall())
                for row in rows:
                    if row["bucket_utc"] is not None:
                        row["bucket_utc"] = row["bucket_utc"].replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                return rows

    def get_incidents(
        self, start_dt: datetime, end_dt: datetime, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            id, started_at, target_name, host, category,
            severity, reason, loss_pct, avg_ms, jitter_ms,
            traceroute_tool, traceroute_output
        FROM incidents
        WHERE started_at >= %s AND started_at <= %s
        ORDER BY started_at DESC
        LIMIT %s;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt, limit))
                return list(cur.fetchall())

    def get_ping_rows_for_export(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            recorded_at, target_name, host, category,
            packets_sent, packets_received, loss_pct,
            min_ms, avg_ms, max_ms, jitter_ms, status
        FROM ping_samples
        WHERE recorded_at >= %s AND recorded_at <= %s
        ORDER BY recorded_at ASC, target_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_summary(
        self, start_dt: datetime, end_dt: datetime
    ) -> list[dict[str, Any]]:
        query = """
        WITH window_stats AS (
            SELECT
                interface_name,
                COUNT(*) AS samples,
                ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS avg_rx_mbps,
                ROUND(MAX(rx_mbps)::numeric, 2)::float8 AS max_rx_mbps,
                ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS avg_tx_mbps,
                SUM(rx_drops_ps + tx_queue_drops_ps) AS total_drops
            FROM wan_traffic
            WHERE recorded_at >= %s AND recorded_at <= %s
            GROUP BY interface_name
        ),
        latest AS (
            SELECT DISTINCT ON (interface_name)
                interface_name,
                rx_mbps AS last_rx_mbps,
                tx_mbps AS last_tx_mbps,
                recorded_at AS last_seen
            FROM wan_traffic
            ORDER BY interface_name, recorded_at DESC
        )
        SELECT w.*, l.last_rx_mbps, l.last_tx_mbps, l.last_seen
        FROM window_stats w
        JOIN latest l USING (interface_name)
        ORDER BY w.interface_name;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (start_dt, end_dt))
                return list(cur.fetchall())

    def get_wan_traffic_timeseries(
        self, start_dt: datetime, end_dt: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        query = """
        SELECT
            to_timestamp(
                floor(extract(epoch FROM recorded_at) / %s) * %s
            ) AT TIME ZONE 'UTC' AS bucket_utc,
            interface_name,
            ROUND(AVG(rx_mbps)::numeric, 2)::float8 AS rx_mbps,
            ROUND(AVG(tx_mbps)::numeric, 2)::float8 AS tx_mbps
        FROM wan_traffic
        WHERE recorded_at >= %s AND recorded_at <= %s
        GROUP BY bucket_utc, interface_name
        ORDER BY bucket_utc ASC, interface_name ASC;
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bucket_seconds, bucket_seconds, start_dt, end_dt))
                rows = list(cur.fetchall())
                for row in rows:
                    if row["bucket_utc"] is not None:
                        row["bucket_utc"] = row["bucket_utc"].replace(
                            tzinfo=timezone.utc
                        ).isoformat()
                return rows
