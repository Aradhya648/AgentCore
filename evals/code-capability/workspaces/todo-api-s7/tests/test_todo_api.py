"""pytest suite for the in-memory Todo API.

Starts a real HTTPServer on an ephemeral port in a daemon thread,
then drives it with urllib so no external process is required.
"""
import json
import threading
import time
import urllib.request
import urllib.error

import pytest

from todo_api.server import create_server, store


@pytest.fixture(autouse=True)
def _reset_store():
    """Each test starts from a clean, empty store."""
    store.reset()
    yield
    store.reset()


@pytest.fixture
def base_url():
    """Spin up a real server on a random free port."""
    server = create_server("127.0.0.1", 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    time.sleep(0.1)  # let the accept loop start
    yield url
    server.shutdown()
    server.server_close()


def _get(url):
    with urllib.request.urlopen(url) as resp:
        return resp.status, json.loads(resp.read())


def _post(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


# ---- GET /todos (list) ---------------------------------------------------

def test_get_todos_initial_empty(base_url):
    status, data = _get(f"{base_url}/todos")
    assert status == 200
    assert data == []


def test_get_todos_returns_array_after_create(base_url):
    _post(f"{base_url}/todos", {"title": "buy milk"})
    _post(f"{base_url}/todos", {"title": "read book"})

    status, data = _get(f"{base_url}/todos")
    assert status == 200
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["title"] == "buy milk"
    assert data[1]["title"] == "read book"


def test_get_todos_trailing_slash(base_url):
    _post(f"{base_url}/todos", {"title": "x"})
    status, data = _get(f"{base_url}/todos/")
    assert status == 200
    assert len(data) == 1


# ---- POST /todos (create) ------------------------------------------------

def test_post_todo_creates_with_id_and_title(base_url):
    status, data = _post(f"{base_url}/todos", {"title": "buy milk"})
    assert status == 201
    assert data["title"] == "buy milk"
    assert "id" in data
    assert isinstance(data["id"], int)


def test_post_todo_stable_incrementing_ids(base_url):
    _, first = _post(f"{base_url}/todos", {"title": "a"})
    _, second = _post(f"{base_url}/todos", {"title": "b"})
    _, third = _post(f"{base_url}/todos", {"title": "c"})

    assert first["id"] == 1
    assert second["id"] == 2
    assert third["id"] == 3

    # Confirm they are persisted in the store
    _, all_todos = _get(f"{base_url}/todos")
    assert [t["id"] for t in all_todos] == [1, 2, 3]


def test_post_todo_missing_title_returns_400(base_url):
    req = urllib.request.Request(
        f"{base_url}/todos",
        data=json.dumps({}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_post_todo_invalid_json_returns_400(base_url):
    req = urllib.request.Request(
        f"{base_url}/todos",
        data=b"not-json",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
