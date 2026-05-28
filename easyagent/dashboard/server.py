from __future__ import annotations

import json
import mimetypes
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from easyagent.store import SQLiteStore
from easyagent.tracing.schema import EventTrace, SessionTrace


DEFAULT_DB_PATH = Path(".easyagent/traces.db")


def run_dashboard(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    """Run the local EasyAgent trace dashboard."""

    resolved_db_path = Path(db_path).expanduser().resolve()
    static_dir = _find_static_dir()
    handler = partial(DashboardHandler, db_path=resolved_db_path, static_dir=static_dir)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"

    print(f"EasyAgent dashboard: {url}")
    print(f"Trace DB: {resolved_db_path}")
    if static_dir is None:
        print("Dashboard UI build was not found; API endpoints are still available.")
        print("Build the UI with: cd apps/dashboard && npm run build")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down EasyAgent dashboard.")
    finally:
        server.server_close()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        db_path: Path,
        static_dir: Path | None,
        **kwargs: Any,
    ) -> None:
        self.db_path = db_path
        self.static_dir = static_dir
        super().__init__(*args, directory=str(static_dir) if static_dir else None, **kwargs)

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "db_path": str(self.db_path), "connected": self.db_path.exists()})
            return
        if parsed.path == "/api/traces":
            query = parse_qs(parsed.query)
            limit = _int_param(query.get("limit"), 200)
            offset = _int_param(query.get("offset"), 0)
            self._send_json(load_trace_payload(self.db_path, limit=limit, offset=offset))
            return
        if parsed.path == "/api/traces/stream":
            query = parse_qs(parsed.query)
            limit = _int_param(query.get("limit"), 200)
            offset = _int_param(query.get("offset"), 0)
            self._send_trace_stream(limit=limit, offset=offset)
            return

        if self.static_dir is None:
            self._send_html(_missing_dashboard_html())
            return

        if parsed.path != "/" and not (self.static_dir / parsed.path.lstrip("/")).exists():
            self.path = "/"
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_trace_stream(self, *, limit: int, offset: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_signature: tuple[int, int, int] | None = None
        try:
            while True:
                signature = _db_signature(self.db_path)
                if signature != last_signature:
                    payload = load_trace_payload(self.db_path, limit=limit, offset=offset)
                    self._write_sse("snapshot", payload)
                    last_signature = signature
                else:
                    self._write_sse("ping", {"ts": time.time()})
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _write_sse(self, event: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str)
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        for line in body.splitlines():
            self.wfile.write(f"data: {line}\n".encode("utf-8"))
        self.wfile.write(b"\n")
        self.wfile.flush()

    def guess_type(self, path: str) -> str:
        if path.endswith(".js"):
            return "text/javascript"
        if path.endswith(".css"):
            return "text/css"
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


def load_trace_payload(db_path: Path, *, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "connected": False,
            "sessions": [],
        }

    store = SQLiteStore(db_path)
    sessions = store.list_sessions(limit=limit, offset=offset)
    return {
        "db_path": str(db_path),
        "connected": True,
        "sessions": [_session_with_events(store, session) for session in sessions],
    }


def _session_with_events(store: SQLiteStore, session: SessionTrace) -> dict[str, Any]:
    events = store.list_events(session.session_id)
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1

    data = session.to_dict()
    data["event_counts"] = event_counts
    data["events"] = [_event_to_dict(event) for event in events]
    return data


def _event_to_dict(event: EventTrace) -> dict[str, Any]:
    return event.to_dict()


def _find_static_dir() -> Path | None:
    package_static = Path(__file__).parent / "static"
    if (package_static / "index.html").exists():
        return package_static

    repo_static = Path(__file__).resolve().parents[2] / "apps" / "dashboard" / "dist"
    if (repo_static / "index.html").exists():
        return repo_static

    return None


def _int_param(values: list[str] | None, default: int) -> int:
    if not values:
        return default
    try:
        return max(0, int(values[0]))
    except ValueError:
        return default


def _db_signature(path: Path) -> tuple[int, int, int]:
    if not path.exists():
        return (0, 0, 0)
    try:
        return SQLiteStore(path).trace_signature()
    except Exception:
        return (0, 0, 0)


def _missing_dashboard_html() -> str:
    return """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>EasyAgent Dashboard</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 48px; line-height: 1.5; }
      code { background: #f3f4f6; border-radius: 6px; padding: 2px 6px; }
    </style>
  </head>
  <body>
    <h1>EasyAgent Dashboard</h1>
    <p>The dashboard UI build was not found.</p>
    <p>From the EasyAgent repository, run <code>cd apps/dashboard && npm run build</code>, then restart <code>easyagent dashboard</code>.</p>
    <p>The trace API is still available at <code>/api/traces</code>.</p>
  </body>
</html>"""
