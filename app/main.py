"""Punto de entrada del servicio recolector Net-Tool."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading

from app.config import load_config
from app.db import Database
from app.monitor import MonitorWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("net_monitor")


def main() -> int:
    parser = argparse.ArgumentParser(description="Net-Tool CCTV Monitor Worker")
    parser.add_argument(
        "--config",
        default=None,
        help="Ruta al archivo config.json (por defecto config.json o NET_MONITOR_CONFIG)",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Inicializa el esquema en PostgreSQL y sale.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    db = Database(config.database.dsn)
    db.init_schema()
    logger.info("Esquema PostgreSQL verificado correctamente.")

    if args.init_db:
        db.close()
        return 0

    worker = MonitorWorker(config, db)
    stop_event = threading.Event()

    def _handle_sig(_signum, _frame):
        logger.info("Señal de salida recibida, deteniendo worker...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    worker.start()
    try:
        stop_event.wait()
    finally:
        worker.stop()
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
