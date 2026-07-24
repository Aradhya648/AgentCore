"""HTTP request handler and server for the in-memory Todo API."""
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class TodoStore:
    """Thread-safe in-memory store for todo items."""

    def __init__(self):
        self._todos = []
        self._next_id = 1
        self._lock = threading.Lock()

    def list_all(self):
        with self._lock:
            return list(self._todos)

    def create(self, title):
        with self._lock:
            todo = {"id": self._next_id, "title": title}
            self._todos.append(todo)
            self._next_id += 1
            return dict(todo)

    def reset(self):
        with self._lock:
            self._todos.clear()
            self._next_id = 1


# Module-level default store (shared across handler instances)
store = TodoStore()


class TodoHandler(BaseHTTPRequestHandler):
    """Handles GET /todos and POST /todos (trailing slash tolerant)."""

    def _normalize_path(self):
        return self.path.rstrip("/") or "/"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._normalize_path() == "/todos":
            self._send_json(200, store.list_all())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self._normalize_path() == "/todos":
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid JSON"})
                return

            title = data.get("title")
            if not title or not isinstance(title, str):
                self._send_json(400, {"error": "title (non-empty string) required"})
                return

            todo = store.create(title)
            self._send_json(201, todo)
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass  # suppress default stderr logging


def create_server(host="127.0.0.1", port=8765):
    """Create an HTTPServer instance with the TodoHandler."""
    return HTTPServer((host, port), TodoHandler)
