"""Local HTTP API + web UI for the patched monitor.

Every DDC transaction goes through one lock, so the UI, the event poller and API callers never interleave on the bus.

Endpoints (JSON):
  GET  /api/status                 live state, firmware info, picture controls
  GET  /api/events?since=SEQ       events after SEQ (default: last 64)
  GET  /api/stream                 Server-Sent Events: one "event" message per monitor event
  POST /api/input   {"target": "dp"|"hdmi"}           switch and wait for the firmware's verdict
  GET  /api/vcp/<hex>              read any VCP code
  POST /api/vcp/<hex> {"value": n}                     write any VCP code (read back when readable)
  GET  /api/settings               1 KB settings block (0x204000..0x2043ff) as hex + known names
  GET  /api/peek?addr=hex&len=n    read RAM (0x200000..0x7fffff)
  POST /api/poke  {"addr": hex, "value": n, "apply": item|null}   write a settings byte, optionally apply menu item
  POST /api/apply {"item": n}      apply menu item (0..0x6e)
  GET  /api/inventory              all known VCP codes with current/max
"""
from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .protocol import (EVENT_NAMES, PORT_NAMES, SETTING_ITEMS, SETTING_NAMES, EventLog, FullAccess,
                       ProtocolError)

PICTURE = {  # code: (name, item for apply, settings offset)
    0x10: ("brightness", 0x0d, 0x1d3), 0x12: ("contrast", 0x0e, 0x1da), 0x87: ("sharpness", 0x0f, 0x1df),
    0x16: ("red", 0x11, 0x1d7), 0x18: ("green", 0x12, 0x1d8), 0x1A: ("blue", 0x13, 0x1d9),
    0x14: ("color_preset", 0x14, None), 0xF7: ("energy_mode_f7", 0x31, 0x1d6),
}
INVENTORY = {0x10: "brightness", 0x12: "contrast", 0x14: "color preset", 0x16: "red gain", 0x18: "green gain",
             0x1A: "blue gain", 0x20: "h-position", 0x30: "v-position", 0x60: "input", 0x87: "sharpness",
             0xAA: "orientation", 0xB6: "panel type", 0xC6: "app enable key", 0xC8: "controller type",
             0xC9: "firmware level", 0xCC: "OSD language", 0xD6: "power mode", 0xDC: "picture mode",
             0xDF: "VCP version", 0xE0: "samsung E0", 0xF7: "samsung F7 (energy mode)"}


class Monitor:
    def __init__(self, log: EventLog):
        self.log = log
        self.fa = FullAccess(log)
        self.lock = threading.RLock()
        self.events = []          # newest last
        self.last_seq = None
        self.subscribers: list[queue.Queue] = []

    # ---- DDC helpers (all under the lock)
    def get(self, code):
        with self.lock:
            rc, mh, ml, ch, cl = self.log._get(code)
        return {"code": code, "supported": rc == 0, "max": (mh << 8) | ml, "current": (ch << 8) | cl}

    def set(self, code, value):
        with self.lock:
            for attempt in range(1, 6):
                self.log._set(code, value)
                time.sleep(0.12)
                try:
                    r = self.get(code)
                except ProtocolError:
                    continue
                if not r["supported"] or r["current"] == value or code in (0x60, 0xD6, 0x04, 0x05, 0x08, 0xF7):
                    r["attempts"] = attempt
                    return r
        raise ProtocolError(f"VCP 0x{code:02x} = {value} not confirmed")

    def status(self):
        with self.lock:
            st = self.log.live()
            info = self.log.info()
            pic = {}
            for code, (name, _, _) in PICTURE.items():
                try:
                    pic[name] = self.get(code)
                except ProtocolError:
                    pic[name] = None
        return {"input": PORT_NAMES.get(st.port, st.port), "input_port": st.port, "power_on": st.power_on,
                "power_flags": st.power_flags, "signal": bool(st.signal), "source_select": st.source_select,
                "clock_s": st.clock_10ms / 100, "events": info["seq"], "ring": info["ring"],
                "protocol": info["version"], "paths": len(self.log.paths), "picture": pic}

    # ---- events
    def _ev_json(self, e):
        return {"seq": e.seq, "id": e.id, "name": e.name, "old": e.old, "new": e.new, "t": e.seconds,
                "text": e.describe()}

    def poll_loop(self):
        while True:
            try:
                with self.lock:
                    seq = self.log.info()["seq"]
                    if self.last_seq is None:
                        hist = self.log.history(64)
                        self.events = [self._ev_json(e) for e in hist]
                        self.last_seq = seq
                    new = []
                    while self.last_seq != seq:
                        nxt = (self.last_seq + 1) & 0xFFFF
                        new.append(self._ev_json(self.log.event(nxt)))
                        self.last_seq = nxt
                for e in new:
                    self.events.append(e)
                    for q in list(self.subscribers):
                        q.put(e)
                self.events = self.events[-500:]
            except ProtocolError:
                pass
            except Exception as ex:  # keep the poller alive no matter what
                print("poller error:", ex)
            time.sleep(0.3)


def _ui_html() -> bytes:
    return resources.files("monitor_events").joinpath("ui.html").read_bytes()


def make_handler(mon: Monitor):
    class H(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - silence per-request logging
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    body = _ui_html()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path == "/api/status":
                    self._json(mon.status())
                elif u.path == "/api/events":
                    since = int(q.get("since", -1))
                    self._json([e for e in mon.events if since < 0 or ((e["seq"] - since) & 0xFFFF) < 0x8000 and e["seq"] != since])
                elif u.path == "/api/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    sub = queue.Queue()
                    mon.subscribers.append(sub)
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
                        mon.subscribers.remove(sub)
                elif u.path.startswith("/api/vcp/"):
                    self._json(mon.get(int(u.path.rsplit("/", 1)[1], 16)))
                elif u.path == "/api/settings":
                    with mon.lock:
                        data = mon.fa.settings()
                    self._json({"base": 0x204000, "hex": data.hex(),
                                "names": {f"{k:x}": v for k, v in SETTING_NAMES.items()},
                                "items": {f"{k:x}": v for k, v in SETTING_ITEMS.items()}})
                elif u.path == "/api/peek":
                    with mon.lock:
                        data = mon.fa.peek(int(q["addr"], 16), int(q.get("len", "16"), 0))
                    self._json({"addr": q["addr"], "hex": data.hex()})
                elif u.path == "/api/inventory":
                    out = []
                    for code, name in INVENTORY.items():
                        try:
                            r = mon.get(code)
                        except ProtocolError:
                            r = {"code": code, "supported": None}
                        r["name"] = name
                        out.append(r)
                    self._json(out)
                elif u.path == "/api/meta":
                    self._json({"events": {f"{k:x}": v for k, v in EVENT_NAMES.items()},
                                "picture": {f"{k:x}": v[0] for k, v in PICTURE.items()}})
                else:
                    self._json({"error": "not found"}, 404)
            except ProtocolError as ex:
                self._json({"error": str(ex)}, 503)
            except Exception as ex:
                self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                b = self._body()
                if u.path == "/api/input":
                    port = {"dp": 0, "displayport": 0, "hdmi": 1}[str(b["target"]).lower()]
                    t0 = time.time()
                    with mon.lock:
                        e = mon.log.switch_input(port)
                    self._json({"ok": e.id == 0x11, "verdict": e.name, "text": e.describe(),
                                "elapsed_s": round(time.time() - t0, 2), "event": mon._ev_json(e)})
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
            except (KeyError, ValueError) as ex:
                self._json({"error": f"bad request: {ex}"}, 400)
            except Exception as ex:
                self._json({"error": f"{type(ex).__name__}: {ex}"}, 500)

    return H


def serve(log: EventLog, host: str = "127.0.0.1", port: int = 8765):
    mon = Monitor(log)
    threading.Thread(target=mon.poll_loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), make_handler(mon))
    print(f"monitor API + UI on http://{host}:{port}/  ({len(log.paths)} path(s) to the monitor)", flush=True)
    srv.serve_forever()
