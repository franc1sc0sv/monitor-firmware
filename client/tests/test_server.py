import http.client
import json
import socket
import threading

import pytest

from monitor_events.protocol import EventLog
from monitor_events.server import make_server
from monitor_events.simulate import FakeMonitor


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def api():
    port = free_port()
    srv, mon = make_server(EventLog(FakeMonitor(switch_delay=0.05)), port=port, poll=False)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield port
    srv.shutdown()


def req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null") if r.getheader("Content-Type", "").startswith(
        "application/json"
    ) else None


def test_status(api):
    code, s = req(api, "GET", "/api/status")
    assert code == 200 and s["input"] == "HDMI" and s["picture"]["brightness"]["current"] == 99


def test_switch_input(api):
    code, r = req(api, "POST", "/api/input", {"target": "dp"})
    assert code == 200 and r["ok"] and r["verdict"] == "switch-done"


def test_vcp_set_and_get(api):
    assert req(api, "POST", "/api/vcp/10", {"value": 70})[1]["confirmed"]
    assert req(api, "GET", "/api/vcp/10")[1]["current"] == 70


def test_settings_masked(api):
    code, s = req(api, "GET", "/api/settings")
    raw = bytes.fromhex(s["hex"])
    assert code == 200 and s["serial_masked"] and raw[0x9A:0x9E] == b"****"


def test_foreign_host_rejected(api):
    assert req(api, "GET", "/api/status", headers={"Host": "evil.example:80"})[0] == 403


def test_foreign_origin_rejected(api):
    assert req(api, "GET", "/api/status", headers={"Origin": "https://evil.example"})[0] == 403


def test_post_requires_json(api):
    c = http.client.HTTPConnection("127.0.0.1", api, timeout=10)
    c.request(
        "POST", "/api/vcp/10", body='{"value": 1}', headers={"Host": f"127.0.0.1:{api}", "Content-Type": "text/plain"}
    )
    assert c.getresponse().status == 415


def test_bad_request(api):
    assert req(api, "POST", "/api/input", {"target": "vga"})[0] == 400


def test_only_loopback():
    with pytest.raises(ValueError):
        make_server(EventLog(FakeMonitor()), host="0.0.0.0", port=free_port(), poll=False)
