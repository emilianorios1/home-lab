"""Internal HTTP runner for the dashboard's allow-listed sync operations."""

from __future__ import annotations

import json
import logging
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

from home_lab.logging import configure_logging


SYNC_COMMANDS = {
    "/sync/gmail": "sync-gmail",
    "/sync/mercadopago": "sync-mercadopago",
    "/sync/siat-tgi": "sync-siat-tgi",
}
# ponytail: one global lock is enough while every sync finishes with dbt build.
SYNC_LOCK = Lock()


class SyncRequestHandler(BaseHTTPRequestHandler):
    """Run only the three sync commands exposed to the internal Docker network."""

    def do_GET(self) -> None:
        if self.path != "/health":
            self._respond(HTTPStatus.NOT_FOUND, "Endpoint inexistente.")
            return
        self._respond(HTTPStatus.OK, "Runner disponible.")

    def do_POST(self) -> None:
        command = SYNC_COMMANDS.get(self.path)
        if command is None:
            self._respond(HTTPStatus.NOT_FOUND, "Sincronización inexistente.")
            return
        if not SYNC_LOCK.acquire(blocking=False):
            self._respond(
                HTTPStatus.CONFLICT,
                "Ya hay una sincronización en ejecución.",
            )
            return

        try:
            logging.info("Starting %s", command)
            result = subprocess.run(
                ["home-lab", command],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode:
                logging.error("%s failed with exit code %s", command, result.returncode)
                self._respond(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "La sincronización falló.",
                )
                return
            logging.info("%s completed", command)
            self._respond(HTTPStatus.OK, "Sincronización completada.")
        except OSError:
            logging.exception("Could not start %s", command)
            self._respond(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "No se pudo iniciar la sincronización.",
            )
        finally:
            SYNC_LOCK.release()

    def _respond(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            logging.info("Client disconnected before receiving the sync result")

    def log_message(self, format: str, *args: object) -> None:
        logging.info("%s - %s", self.client_address[0], format % args)


def main() -> None:
    configure_logging()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), SyncRequestHandler)
    logging.info("Sync runner listening on port 8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
