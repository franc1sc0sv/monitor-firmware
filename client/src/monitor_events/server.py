"""Local HTTP API + web UI for the patched monitor. See docs/protocol/http-api.md.

Security model (ADR-0013): the server binds to localhost and only answers requests whose Host header is the
loopback address it listens on, rejects cross-site Origins, and requires `Content-Type: application/json` on POST,
so a web page the user happens to visit cannot drive the monitor (no CORS, no DNS rebinding, no simple-form CSRF).

Every DDC transaction goes through one lock, so the UI, the event poller and API callers never interleave on the bus.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .protocol import (
    EVENT_NAMES,
    PORT_NAMES,
    SETTING_ITEMS,
    SETTING_NAMES,
    VCP_CODES,
    EventLog,
    FullAccess,
    ProtocolError,
)

PICTURE = {  # VCP code -> UI name
    0x10: "brightness",
    0x12: "contrast",
    0x87: "sharpness",
    0x16: "red",
    0x18: "green",
    0x1A: "blue",
    0x14: "color_preset",
    0xF7: "energy_mode_f7",
}


class Monitor:
    def __init__(self, log: EventLog):
        self.log = log
        self.fa = FullAccess(log)
        self.lock = threading.RLock()  # serialises the DDC bus
        self.state_lock = threading.Lock()  # protects events/subscribers
        self.events: deque[dict] = deque(maxlen=500)
        self.last_seq: int | None = None
        self.subscribers: list[queue.Queue] = []

    def get(self, code: int) -> dict:
        with self.lock:
            rc, mh, ml, ch, cl = self.log.get_vcp(code)
        return {
            "code": code,
            "name": VCP_CODES.get(code),
            "supported": rc == 0,
            "max": (mh << 8) | ml,
            "current": (ch << 8) | cl,
        }

    def set(self, code: int, value: int) -> dict:
        with self.lock:
            r = self.log.set_vcp(code, value)
        r["name"] = VCP_CODES.get(code)
        return r

    def status(self) -> dict:
        with self.lock:
            st = self.log.live()
            info = self.log.info()
            pic = {}
            for code, name in PICTURE.items():
                try:
                    pic[name] = self.get(code)
                except ProtocolError:
                    pic[name] = None
        return {
            "input": PORT_NAMES.get(st.port, st.port),
            "input_port": st.port,
            "power_on": st.power_on,
            "power_flags": st.power_flags,
            "signal": bool(st.signal),
            "source_select": st.source_select,
            "clock_s": st.clock_10ms / 100,
            "events": info["seq"],
            "ring": info["ring"],
            "protocol": info["version"],
            "paths": len(self.log.paths),
            "picture": pic,
        }

    @staticmethod
    def _ev_json(e) -> dict:
        return {
            "seq": e.seq,
            "id": e.id,
            "name": e.name,
            "old": e.old,
            "new": e.new,
            "t": e.seconds,
            "text": e.describe(),
        }

    def events_since(self, since: int) -> list[dict]:
        with self.state_lock:
            evs = list(self.events)
        if since < 0:
            return evs
        return [e for e in evs if 0 < ((e["seq"] - since) & 0xFFFF) < 0x8000]

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.state_lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self.state_lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def poll_loop(self, interval: float = 0.3):
        while True:
            try:
                new = []
                with self.lock:
                    seq = self.log.info()["seq"]
                    if self.last_seq is None:
                        hist = [self._ev_json(e) for e in self.log.history(64)]
                        with self.state_lock:
                            self.events.extend(hist)
                        self.last_seq = seq
                    cur: int = self.last_seq if self.last_seq is not None else seq
                    while cur != seq:
                        cur = (cur + 1) & 0xFFFF
                        new.append(self._ev_json(self.log.event(cur)))
                        self.last_seq = cur
                with self.state_lock:
                    self.events.extend(new)
                    subs = list(self.subscribers)
                for e in new:
                    for q in subs:
                        q.put(e)
            except ProtocolError:
                pass
            except Exception as ex:  # keep the poller alive no matter what
                print("poller error:", ex, flush=True)
            time.sleep(interval)


def _ui_html() -> bytes:
    return resources.files("monitor_events").joinpath("ui.html").read_bytes()


def make_handler(mon: Monitor, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - silence per-request logging
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _allowed(self, post: bool) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self._json({"error": "forbidden host"}, 403)
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                self._json({"error": "forbidden origin"}, 403)
                return False
            if post and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._json({"error": "Content-Type must be application/json"}, 415)
                return False
            return True

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            if not self._allowed(post=False):
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            raw = q.get("raw") == "1"
            try:
                if u.path in ("/", "/index.html"):
                    self._send(200, _ui_html(), "text/html; charset=utf-8")
                elif u.path == "/api/status":
                    self._json(mon.status())
                elif u.path == "/api/events":
                    self._json(mon.events_since(int(q.get("since", -1))))
                elif u.path == "/api/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    sub = mon.subscribe()
                    try:
                        while True:
                            try:
                                e = sub.get(timeout=15)
                                self.wfile.write(f"event: monitor\ndata: {json.dumps(e)}\n\n".encode())
                            except queue.Empty:
                                self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass
                    finally:
                        mon.unsubscribe(sub)
                elif u.path.startswith("/api/vcp/"):
                    self._json(mon.get(int(u.path.rsplit("/", 1)[1], 16)))
                elif u.path == "/api/settings":
                    with mon.lock:
                        data = mon.fa.settings(raw=raw)
                    self._json(
                        {
                            "base": 0x204000,
                            "hex": data.hex(),
                            "serial_masked": not raw,
                            "names": {f"{k:x}": v for k, v in SETTING_NAMES.items()},
                            "items": {f"{k:x}": v for k, v in SETTING_ITEMS.items()},
                        }
                    )
                elif u.path == "/api/peek":
                    with mon.lock:
                        data = mon.fa.peek_masked(int(q["addr"], 16), int(q.get("len", "16"), 0), raw=raw)
                    self._json({"addr": q["addr"], "hex": data.hex()})
                elif u.path == "/api/inventory":
                    out = []
                    for code, name in VCP_CODES.items():
                        try:
                            r = mon.get(code)
                        except ProtocolError:
                            r = {"code": code, "supported": None}
                        r["name"] = name
                        out.append(r)
                    self._json(out)
                elif u.path == "/api/meta":
                    self._json(
                        {
                            "events": {f"{k:x}": v for k, v in EVENT_NAMES.items()},
                            "vcp": {f"{k:x}": v for k, v in VCP_CODES.items()},
                        }
                    )
                else:
                    self._json({"error": "not found"}, 404)
            except ProtocolError as ex:
                self._json({"error": str(ex)}, 503)
            except (KeyError, ValueError) as ex:
                self._json({"error": f"bad request: {ex}"}, 400)
            except Exception as ex:
                self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

        def do_POST(self):
            if not self._allowed(post=True):
                return
            u = urlparse(self.path)
            try:
                b = self._body()
                if u.path == "/api/input":
                    port = {"dp": 0, "displayport": 0, "hdmi": 1}[str(b["target"]).lower()]
                    t0 = time.time()
                    with mon.lock:
                        e = mon.log.switch_input(port)
                    self._json(
                        {
                            "ok": e.id == 0x11,
                            "verdict": e.name,
                            "text": e.describe(),
                            "elapsed_s": round(time.time() - t0, 2),
                            "event": mon._ev_json(e),
                        }
                    )
                elif u.path.startswith("/api/vcp/"):
                    self._json(mon.set(int(u.path.rsplit("/", 1)[1], 16), int(b["value"])))
                elif u.path == "/api/poke":
                    addr = int(str(b["addr"]), 16)
                    with mon.lock:
                        mon.fa.poke(addr, int(b["value"]))
                        item = b.get("apply")
                        if item is None:
                            item = SETTING_ITEMS.get(addr - 0x204000)
                        if item is not None:
                            mon.fa.apply(int(item))
                    self._json({"ok": True, "applied_item": item})
                elif u.path == "/api/apply":
                    with mon.lock:
                        mon.fa.apply(int(b["item"]))
                    self._json({"ok": True})
                else:
                    self._json({"error": "not found"}, 404)
            except ProtocolError as ex:
                self._json({"error": str(ex)}, 503)
            except (KeyError, ValueError, json.JSONDecodeError) as ex:
                self._json({"error": f"bad request: {ex}"}, 400)
            except Exception as ex:
                self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

    return H


def make_server(log: EventLog, host: str = "127.0.0.1", port: int = 8765, poll: bool = True):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the API only listens on loopback (see ADR-0013)")
    mon = Monitor(log)
    if poll:
        threading.Thread(target=mon.poll_loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), make_handler(mon, port))
    return srv, mon


def serve(log: EventLog, host: str = "127.0.0.1", port: int = 8765):
    srv, _ = make_server(log, host, port)
    print(f"monitor API + UI on http://{host}:{port}/  ({len(log.paths)} path(s) to the monitor)", flush=True)
    srv.serve_forever()
