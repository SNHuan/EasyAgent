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

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
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
            "runs": [],
        }

    store = SQLiteStore(db_path)
    sessions = [_session_with_events(store, session) for session in store.list_sessions(limit=limit, offset=offset)]
    return {
        "db_path": str(db_path),
        "connected": True,
        "runs": _runs_from_sessions(sessions),
    }


def _runs_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        metadata = _metadata(session)
        run_id = str(metadata.get("run_id") or f"run_{session['session_id']}")
        groups.setdefault(run_id, []).append(session)

    runs = [_sessions_to_run(run_id, grouped_sessions) for run_id, grouped_sessions in groups.items()]
    return sorted(runs, key=lambda run: str(run["started_at"]), reverse=True)


def _sessions_to_run(run_id: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    runtime_session = next((session for session in sessions if _metadata(session).get("trace_kind") == "runtime"), None)
    agent_sessions = [session for session in sessions if _metadata(session).get("trace_kind") != "runtime"]
    first = runtime_session or agent_sessions[0]
    metadata = _metadata(first)
    entities = _entities_from_sessions(agent_sessions)
    visible_sessions = agent_sessions
    run_events = runtime_session.get("events", []) if runtime_session else []

    return {
        "run_id": run_id,
        "scope": metadata.get("run_scope") or ("runtime" if metadata.get("world") else "agent"),
        "title": metadata.get("run_title") or metadata.get("title") or metadata.get("name") or _session_title(first),
        "status": _aggregate_status(session["status"] for session in sessions),
        "started_at": min(str(session["started_at"]) for session in sessions),
        "ended_at": _aggregate_ended_at(sessions),
        "event_count": sum(int(session.get("event_count") or 0) for session in visible_sessions) + len(run_events),
        "token_usage": _sum_token_usage(session.get("token_usage") for session in visible_sessions),
        "world": metadata.get("world"),
        "entities": entities,
        "tree": _tree_from_sessions(agent_sessions),
        "sessions": visible_sessions,
        "events": run_events,
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key not in {"entity", "world", "trace_kind"}
        },
    }


def _entities_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    entity_metadata: dict[str, dict[str, Any]] = {}

    for session in sessions:
        metadata = _metadata(session)
        entity = metadata.get("entity") if isinstance(metadata.get("entity"), dict) else {}
        entity_id = str(entity.get("entity_id") or metadata.get("entity_id") or session.get("agent_id") or session["session_id"])
        groups.setdefault(entity_id, []).append(session)
        entity_metadata.setdefault(entity_id, dict(entity))

    entities: list[dict[str, Any]] = []
    for entity_id, grouped_sessions in groups.items():
        entity = entity_metadata.get(entity_id, {})
        entities.append(
            {
                "entity_id": entity_id,
                "label": entity.get("label") or entity.get("name") or grouped_sessions[0].get("agent_id") or entity_id,
                "kind": entity.get("kind") or "agent",
                "status": _aggregate_status(session["status"] for session in grouped_sessions),
                "event_count": sum(int(session.get("event_count") or 0) for session in grouped_sessions),
                "token_usage": _sum_token_usage(session.get("token_usage") for session in grouped_sessions),
                "sessions": grouped_sessions,
                "metadata": {
                    key: value
                    for key, value in entity.items()
                    if key not in {"entity_id", "label", "name", "kind"}
                },
            }
        )

    return sorted(entities, key=lambda entity: str(entity["label"]))


def _tree_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    root_index: dict[str, dict[str, Any]] = {}

    for session in sessions:
        parent_children = roots
        parent_index = root_index

        for group in _dashboard_group_path(session):
            node_id = f"group:{group['id']}"
            node = parent_index.get(node_id)
            if node is None:
                node = _empty_tree_node(
                    node_id=node_id,
                    label=group["label"],
                    kind=group["kind"],
                )
                parent_index[node_id] = node
                parent_children.append(node)
            _add_session_totals(node, session)
            parent_children = node["children"]
            parent_index = node.setdefault("_child_index", {})

        entity = _session_entity(session)
        entity_id = f"entity:{entity['entity_id']}"
        entity_node = parent_index.get(entity_id)
        if entity_node is None:
            entity_node = _empty_tree_node(
                node_id=entity_id,
                label=entity["label"],
                kind=entity["kind"],
            )
            parent_index[entity_id] = entity_node
            parent_children.append(entity_node)
        _add_session_totals(entity_node, session)
        entity_node["sessions"].append(session)

    _finalize_tree_nodes(roots)
    return roots


def _dashboard_group_path(session: dict[str, Any]) -> list[dict[str, str]]:
    metadata = _metadata(session)
    raw_path = metadata.get("dashboard_group_path")
    if not isinstance(raw_path, list):
        return []

    path: list[dict[str, str]] = []
    for index, raw_group in enumerate(raw_path):
        if not isinstance(raw_group, dict):
            continue
        raw_id = raw_group.get("id") or raw_group.get("label") or raw_group.get("name")
        if raw_id is None:
            raw_id = f"group-{index}"
        label = raw_group.get("label") or raw_group.get("name") or raw_id
        kind = raw_group.get("kind") or "group"
        path.append(
            {
                "id": str(raw_id),
                "label": str(label),
                "kind": str(kind),
            }
        )
    return path


def _session_entity(session: dict[str, Any]) -> dict[str, str]:
    metadata = _metadata(session)
    entity = metadata.get("entity") if isinstance(metadata.get("entity"), dict) else {}
    entity_id = str(entity.get("entity_id") or metadata.get("entity_id") or session.get("agent_id") or session["session_id"])
    return {
        "entity_id": entity_id,
        "label": str(entity.get("label") or entity.get("name") or session.get("agent_id") or entity_id),
        "kind": str(entity.get("kind") or "agent"),
    }


def _empty_tree_node(*, node_id: str, label: str, kind: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "kind": kind,
        "status": "running",
        "event_count": 0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "children": [],
        "sessions": [],
        "_statuses": [],
        "_child_index": {},
    }


def _add_session_totals(node: dict[str, Any], session: dict[str, Any]) -> None:
    node["event_count"] += int(session.get("event_count") or 0)
    node["_statuses"].append(session.get("status", "running"))
    token_usage = node["token_usage"]
    session_usage = session.get("token_usage") if isinstance(session.get("token_usage"), dict) else {}
    token_usage["prompt_tokens"] += int(session_usage.get("prompt_tokens") or 0)
    token_usage["completion_tokens"] += int(session_usage.get("completion_tokens") or 0)
    token_usage["total_tokens"] += int(session_usage.get("total_tokens") or 0)


def _finalize_tree_nodes(nodes: list[dict[str, Any]]) -> None:
    nodes.sort(key=lambda node: (str(node["label"]), str(node["id"])))
    for node in nodes:
        node["status"] = _aggregate_status(node.pop("_statuses", []))
        node.pop("_child_index", None)
        _finalize_tree_nodes(node["children"])


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


def _metadata(session: dict[str, Any]) -> dict[str, Any]:
    metadata = session.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _aggregate_status(statuses: Any) -> str:
    values = list(statuses)
    if "running" in values:
        return "running"
    if "failed" in values:
        return "failed"
    return "completed" if values else "running"


def _aggregate_ended_at(sessions: list[dict[str, Any]]) -> str | None:
    ended_values = [str(session["ended_at"]) for session in sessions if session.get("ended_at")]
    if len(ended_values) != len(sessions):
        return None
    return max(ended_values) if ended_values else None


def _sum_token_usage(items: Any) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for usage in items:
        if not isinstance(usage, dict):
            continue
        totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        totals["total_tokens"] += int(usage.get("total_tokens") or 0)
    return totals


def _session_title(session: dict[str, Any]) -> str:
    events = session.get("events", [])
    if not isinstance(events, list):
        return str(session.get("session_id", "Agent session"))

    for event_type, payload_key, fallback in (
        ("AgentFailedEvent", "error", "Failed session"),
        ("ToolCalledEvent", "tool_name", "Tool call session"),
        ("AgentFinishedEvent", "output", "Completed session"),
        ("LLMRespondedEvent", "content", "LLM response"),
        ("LLMStreamChunkEvent", "content", "Streaming response"),
    ):
        for event in events:
            if not isinstance(event, dict) or event.get("event_type") != event_type:
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            value = payload.get(payload_key)
            if value:
                return _truncate(str(value), 72)
            return fallback

    return str(session.get("session_id", "Agent session"))


def _truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else f"{value[:max_length - 1]}..."


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
