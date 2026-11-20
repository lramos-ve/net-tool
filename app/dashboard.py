"""Dashboard web en Streamlit para monitoreo CCTV & conectividad."""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import pandas as pd
import streamlit as st

from app.config import AppConfig, load_config
from app.db import Database
from app.probes import (
    run_dns_check,
    run_mikrotik_api_traceroute,
    run_ping,
    run_tcp_check,
    run_traceroute,
)
from app.timewindow import choose_bucket_seconds, resolve_time_window

st.set_page_config(
    page_title="Net-Tool · Monitor CCTV",
    page_icon="📡",
    layout="wide",
)


@st.cache_resource
def get_resources() -> tuple[AppConfig, Database]:
    cfg_path = os.getenv("NET_MONITOR_CONFIG")
    cfg = load_config(cfg_path)
    db = Database(cfg.database.dsn)
    db.init_schema()
    return cfg, db


def status_label(status: str | None) -> str:
    s = (status or "down").lower()
    if s == "ok":
        return "🟢 OK"
    if s == "degraded":
        return "🟡 DEGRADADO"
    return "🔴 CAÍDO"


def format_local_ts(dt_val: Any) -> str:
    if dt_val is None or pd.isna(dt_val):
        return "-"
    if isinstance(dt_val, str):
        dt_val = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
    return dt_val.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def render_monitoring_view(
    cfg: AppConfig,
    db: Database,
    preset: str,
    custom_start: datetime | None,
    custom_end: datetime | None,
) -> None:
    start_dt, end_dt = resolve_time_window(cfg, preset, custom_start, custom_end)
    bucket_seconds = choose_bucket_seconds(start_dt, end_dt)

    st.caption(
        f"Ventana consultada: **{format_local_ts(start_dt)}** — **{format_local_ts(end_dt)}** "
        f"· Última lectura UI: **{datetime.now().strftime('%H:%M:%S')}**"
    )

    ping_summary = db.get_ping_summary(start_dt, end_dt)
    tcp_summary = db.get_tcp_summary(start_dt, end_dt)
    dns_summary = db.get_dns_summary(start_dt, end_dt)
    incidents = db.get_incidents(start_dt, end_dt, limit=100)
    timeseries = db.get_ping_timeseries(start_dt, end_dt, bucket_seconds=bucket_seconds)
    wan_summary = db.get_wan_traffic_summary(start_dt, end_dt)
    wan_timeseries = db.get_wan_traffic_timeseries(start_dt, end_dt, bucket_seconds=bucket_seconds)

    # 1. Tarjetas de estado por enlace
    st.subheader("Estado de Salida a Internet (Boom / Destinos Remotos)")
    if not ping_summary:
        st.info("No hay muestras de ping registradas en esta ventana todavía.")
    else:
        cols = st.columns(min(4, len(ping_summary)))
        for idx, item in enumerate(ping_summary):
            with cols[idx % len(cols)]:
                with st.container(border=True):
                    st.markdown(
                        f"**{item['target_name']}**  \n"
                        f"`{item['host']}` · `{item['category'].upper()}` · {status_label(item['last_status'])}"
                    )
                    c1, c2 = st.columns(2)
                    c1.metric(
                        "Latencia prom",
                        f"{item['avg_ms']} ms" if item["avg_ms"] is not None else "N/A",
                        f"p95: {item['p95_ms']} ms" if item["p95_ms"] is not None else None,
                        delta_color="off",
                    )
                    c2.metric(
                        "Pérdida / Disp.",
                        f"{item['avg_loss_pct']}%" if item["avg_loss_pct"] is not None else "N/A",
                        f"Disp: {item['uptime_pct']}%" if item["uptime_pct"] is not None else None,
                        delta_color="off",
                    )
                    st.caption(
                        f"Último: {item['last_avg_ms']} ms · Jitter prom: {item['avg_jitter_ms']} ms · Muestras: {item['samples']}"
                        if item["avg_jitter_ms"] is not None
                        else f"Muestras: {item['samples']}"
                    )

    # 2. Gráficas comparativas
    st.subheader("Evolución Histórica Comparativa")
    if not timeseries:
        st.info("Sin datos suficientes para graficar en este rango.")
    else:
        ts_df = pd.DataFrame(timeseries)
        ts_df["hora_local"] = (
            pd.to_datetime(ts_df["bucket_utc"], utc=True)
            .dt.tz_convert(datetime.now().astimezone().tzinfo)
            .dt.tz_localize(None)
        )

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown("**Latencia promedio (ms)**")
            lat_pivot = ts_df.pivot(index="hora_local", columns="target_name", values="avg_ms")
            st.line_chart(lat_pivot, height=300)

        with col_g2:
            st.markdown("**Pérdida de paquetes (%)**")
            loss_pivot = ts_df.pivot(index="hora_local", columns="target_name", values="loss_pct")
            st.line_chart(loss_pivot, height=300)

        st.markdown("**Jitter promedio (ms)**")
        jit_pivot = ts_df.pivot(index="hora_local", columns="target_name", values="jitter_ms")
        st.line_chart(jit_pivot, height=240)

    # 2.5 Tráfico WAN del hEX (Boom / MONITOREO)
    if wan_summary:
        st.subheader("Tráfico WAN · Boom (pppoe-out1 / MONITOREO)")
        w_cols = st.columns(len(wan_summary))
        for idx, w in enumerate(wan_summary):
            with w_cols[idx]:
                with st.container(border=True):
                    label = "Boom (pppoe-out1 · MONITOREO)" if w["interface_name"] == "pppoe-out1" else w["interface_name"]
                    st.markdown(f"**{label}**")
                    c1, c2 = st.columns(2)
                    c1.metric("Descarga (RX) actual", f"{w['last_rx_mbps']} Mbps", f"Máx: {w['max_rx_mbps']} Mbps", delta_color="off")
                    c2.metric("Subida (TX) actual", f"{w['last_tx_mbps']} Mbps", f"Drops: {w['total_drops']}", delta_color="off")
        if wan_timeseries:
            wan_df = pd.DataFrame(wan_timeseries)
            wan_df["hora_local"] = (
                pd.to_datetime(wan_df["bucket_utc"], utc=True)
                .dt.tz_convert(datetime.now().astimezone().tzinfo)
                .dt.tz_localize(None)
            )
            st.markdown("**Consumo de descarga WAN (Mbps)**")
            rx_pivot = wan_df.pivot(index="hora_local", columns="interface_name", values="rx_mbps")
            st.line_chart(rx_pivot, height=240)

    # 3. Puertos TCP (iVMS / CCTV) y DNS
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.subheader("Puertos iVMS / CCTV (TCP)")
        if not tcp_summary:
            st.caption("Sin pruebas TCP configuradas/registradas.")
        else:
            tcp_df = pd.DataFrame(tcp_summary)
            tcp_df["estado"] = tcp_df["last_status"].map(status_label)
            st.dataframe(
                tcp_df[
                    ["target_name", "host", "port", "service_name", "estado", "avg_connect_ms", "success_pct"]
                ].rename(
                    columns={
                        "target_name": "Destino",
                        "host": "Host",
                        "port": "Puerto",
                        "service_name": "Servicio",
                        "estado": "Estado",
                        "avg_connect_ms": "Conexión (ms)",
                        "success_pct": "Éxito (%)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with col_t2:
        st.subheader("Resolución DNS")
        if not dns_summary:
            st.caption("Sin pruebas DNS registradas.")
        else:
            dns_df = pd.DataFrame(dns_summary)
            dns_df["estado"] = dns_df["last_success"].map(lambda ok: "🟢 OK" if ok else "🔴 FALLO")
            st.dataframe(
                dns_df[["domain", "estado", "avg_resolve_ms", "last_ips", "success_pct"]].rename(
                    columns={
                        "domain": "Dominio",
                        "estado": "Estado",
                        "avg_resolve_ms": "Tiempo (ms)",
                        "last_ips": "IPs",
                        "success_pct": "Éxito (%)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    # 4. Bitácora de incidentes y trazas de ruta
    st.subheader(f"Bitácora de Incidentes ({len(incidents)})")
    if not incidents:
        st.success("Sin incidentes registrados en esta ventana de tiempo.")
    else:
        for inc in incidents:
            ts_str = format_local_ts(inc["started_at"])
            sev = status_label(inc["severity"])
            header = f"{ts_str} | {sev} | {inc['target_name']} ({inc['host']}) — {inc['reason']}"
            with st.expander(header):
                m1, m2, m3 = st.columns(3)
                m1.write(f"**Categoría:** `{inc['category']}`")
                m2.write(
                    f"**Latencia:** {inc['avg_ms']} ms" if inc["avg_ms"] is not None else "**Latencia:** N/A"
                )
                m3.write(
                    f"**Pérdida:** {inc['loss_pct']}%" if inc["loss_pct"] is not None else "**Pérdida:** N/A"
                )
                if inc.get("traceroute_output"):
                    st.markdown(f"**Traza capturada ({inc.get('traceroute_tool') or 'ruta'}):**")
                    st.code(inc["traceroute_output"], language="text")
                else:
                    st.caption("Sin nueva traza (en ventana de cooldown).")


def render_realtime_actions(cfg: AppConfig, db: Database) -> None:
    st.subheader("⚡ Acciones en Tiempo Real")
    col_a, col_b = st.columns(2)

    with col_a:
        with st.container(border=True):
            st.markdown("**Diagnóstico instantáneo (Ping + TCP + DNS)**")
            if st.button("⚡ Probar todos los enlaces ahora", use_container_width=True):
                rows = []
                with st.spinner("Ejecutando sondas en vivo..."):
                    for t in cfg.ping_targets:
                        if not t.enabled:
                            continue
                        res = run_ping(
                            t,
                            cfg.monitoring.ping_count,
                            cfg.monitoring.ping_timeout_seconds,
                            cfg.thresholds,
                        )
                        db.insert_ping_sample(res)
                        rows.append(
                            {
                                "Destino": res.target_name,
                                "Host": res.host,
                                "Estado": status_label(res.status),
                                "Latencia (ms)": res.avg_ms,
                                "Jitter (ms)": res.jitter_ms,
                                "Pérdida (%)": res.loss_pct,
                            }
                        )
                    for tc in cfg.tcp_targets:
                        if not tc.enabled:
                            continue
                        tcp_res = run_tcp_check(tc, cfg.thresholds.tcp_warn_ms)
                        db.insert_tcp_check(tcp_res)
                    for dn in cfg.dns_targets:
                        if not dn.enabled:
                            continue
                        dns_res = run_dns_check(dn)
                        db.insert_dns_check(dns_res)

                st.success("Sondas ejecutadas y guardadas en PostgreSQL.")
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with col_b:
        with st.container(border=True):
            st.markdown("**Trazar ruta en vivo (`mtr` / `traceroute` / `hEX API`)**")
            host_options = [f"{t.name} ({t.host})" for t in cfg.ping_targets if t.enabled]
            host_map = {f"{t.name} ({t.host})": t.host for t in cfg.ping_targets if t.enabled}
            host_options.append("Otro host / IP...")
            selected = st.selectbox("Destino a trazar", host_options, key="trace_select")
            target_host = (
                st.text_input("IP o dominio", value="8.8.8.8", key="trace_custom_host")
                if selected == "Otro host / IP..."
                else host_map[selected]
            )

            origins = ["Servidor local (mtr/traceroute)"]
            if cfg.mikrotik.enabled and cfg.mikrotik.mode == "api" and cfg.mikrotik.password:
                origins.extend(
                    [
                        "MikroTik hEX · Boom / MONITOREO (to_ISP1)",
                        "MikroTik hEX · Servitel (to_ISP2)",
                        "MikroTik hEX · Tabla main",
                    ]
                )
            origin = st.selectbox("Origen de la traza", origins, key="trace_origin")

            if st.button("🛣️ Ejecutar traceroute", use_container_width=True):
                if origin.startswith("MikroTik hEX"):
                    rt = (
                        "to_ISP1"
                        if "to_ISP1" in origin
                        else "to_ISP2"
                        if "to_ISP2" in origin
                        else None
                    )
                    try:
                        with st.spinner(f"Ejecutando /tool/traceroute en hEX hacia {target_host}..."):
                            hops = run_mikrotik_api_traceroute(
                                host=cfg.mikrotik.host,
                                username=cfg.mikrotik.username,
                                password=cfg.mikrotik.password,
                                target=target_host.strip(),
                                port=cfg.mikrotik.port,
                                use_ssl=cfg.mikrotik.use_ssl,
                                routing_table=rt,
                            )
                        if hops:
                            st.dataframe(pd.DataFrame(hops), use_container_width=True, hide_index=True)
                        else:
                            st.info("El router no devolvió saltos para ese destino.")
                    except Exception as exc:
                        msg = str(exc)
                        if "permission" in msg.lower():
                            st.error(
                                "El grupo `Dev` en el hEX no tiene la política `test` habilitada "
                                "(necesaria para `/tool/traceroute`). Activa `test` en System > Users > Groups > Dev."
                            )
                        else:
                            st.error(f"Error ejecutando traceroute en hEX: {exc}")
                else:
                    with st.spinner(f"Trazando ruta hacia {target_host}..."):
                        tool, output = run_traceroute(target_host.strip())
                    st.caption(f"Herramienta utilizada: `{tool}`")
                    st.code(output, language="text")


def main() -> None:
    cfg, db = get_resources()

    st.title("📡 Net-Tool · Monitor CCTV & Conectividad California")

    with st.sidebar:
        st.header("Filtros y Tiempo Real")
        live_mode = st.toggle("🟢 Auto-refresco en vivo (15s)", value=True)

        preset_labels = {
            "En vivo (Última hora)": "1h",
            "Última noche (19:00–07:00)": "last_night",
            "Últimas 6 horas": "6h",
            "Últimas 24 horas": "24h",
            "Últimos 7 días": "7d",
            "Rango personalizado": "custom",
        }
        selected_label = st.selectbox(
            "Ventana de tiempo",
            list(preset_labels.keys()),
            index=0,
        )
        preset = preset_labels[selected_label]

        custom_start = None
        custom_end = None
        if preset == "custom":
            now_local = datetime.now().astimezone()
            d_start = st.date_input("Fecha inicio", value=(now_local - timedelta(days=1)).date())
            t_start = st.time_input("Hora inicio", value=time(19, 0))
            d_end = st.date_input("Fecha fin", value=now_local.date())
            t_end = st.time_input("Hora fin", value=time(7, 0))
            custom_start = datetime.combine(d_start, t_start).astimezone()
            custom_end = datetime.combine(d_end, t_end).astimezone()

        if st.button("🔄 Actualizar ahora", use_container_width=True):
            st.rerun()

        start_dt, end_dt = resolve_time_window(cfg, preset, custom_start, custom_end)
        raw_rows = db.get_ping_rows_for_export(start_dt, end_dt)
        if raw_rows:
            csv_bytes = pd.DataFrame(raw_rows).to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Exportar CSV",
                data=csv_bytes,
                file_name=f"net_monitor_{preset}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.divider()
        st.caption(
            "Enfocado en la salida a Internet por Boom (pppoe-out1 / MONITOREO) y "
            "conectividad hacia los NVRs en California."
        )

    render_realtime_actions(cfg, db)
    st.divider()

    if live_mode:
        @st.fragment(run_every=15)
        def _live_fragment() -> None:
            render_monitoring_view(cfg, db, preset, custom_start, custom_end)

        _live_fragment()
    else:
        render_monitoring_view(cfg, db, preset, custom_start, custom_end)


if __name__ == "__main__":
    main()
