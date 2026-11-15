"""monitor-events: read and watch the patched monitor's event log, and act on events.

  monitor-events list                     displays and whether they carry the event log
  monitor-events status                   live state + clock
  monitor-events history [-n 30]          recent events
  monitor-events watch [--exec CMD]       stream events; CMD runs per event with MON_* env vars
  monitor-events switch dp|hdmi           switch input and report the firmware's verdict
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time

from .backends import open_displays
from .protocol import PORT_NAMES, SETTING_NAMES, EventLog, FullAccess, ProtocolError


def find_logs():
    """Group every display path that carries the event log by monitor (same clock within 1 s = same monitor)."""
    groups = []
    for d in open_displays():
        log = EventLog(d)
        if not log.supported():
            continue
        clk = log.clock()
        for g in groups:
            if abs(g[1] - clk) < 100:
                g[2].append(d)
                break
        else:
            groups.append([d, clk, []])
    return [(d, EventLog(d, extra_paths=extra)) for d, clk, extra in groups]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="monitor-events")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("status")
    h = sub.add_parser("history"); h.add_argument("-n", type=int, default=30)
    w = sub.add_parser("watch"); w.add_argument("--exec", dest="exec_cmd"); w.add_argument("--json", action="store_true")
    s = sub.add_parser("switch"); s.add_argument("target", choices=["dp", "hdmi"])
    v = sub.add_parser("vcp"); v.add_argument("op", choices=["get", "set"]); v.add_argument("code"); v.add_argument("value", nargs="?")
    sub.add_parser("inventory")
    pk = sub.add_parser("peek"); pk.add_argument("addr"); pk.add_argument("length", nargs="?", default="16")
    po = sub.add_parser("poke"); po.add_argument("addr"); po.add_argument("value")
    apl = sub.add_parser("apply"); apl.add_argument("item")
    ds = sub.add_parser("dump-settings"); ds.add_argument("-o", "--out")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for d in open_displays():
            print(f"{d.name}: event log {'YES' if EventLog(d).supported() else 'no'}")
        for i, (d, log) in enumerate(find_logs()):
            print(f"monitor {i}: {len(log.paths)} path(s) to the same event log")
        return 0
    logs = find_logs()
    if not logs:
        print("no display with the event log answered (patched firmware not present or not reachable)", file=sys.stderr)
        return 2
    d, log = logs[0]
    try:
        if a.cmd == "serve":
            from .server import serve
            serve(log, a.host, a.port)
        elif a.cmd == "status":
            st = log.live(); inf = log.info()
            print(json.dumps({"display": d.name, "input": PORT_NAMES.get(st.port, st.port), "power_on": st.power_on,
                              "signal": bool(st.signal), "source_select": st.source_select, "events": inf["seq"],
                              "monitor_clock_s": st.clock_10ms / 100}, indent=2))
        elif a.cmd == "history":
            for e in log.history(a.n):
                print(f"#{e.seq:<5} {e.seconds:9.2f}s  {e.describe()}")
        elif a.cmd == "watch":
            for e in log.watch():
                if a.json:
                    print(json.dumps({"seq": e.seq, "id": e.id, "name": e.name, "old": e.old, "new": e.new, "t": e.seconds, "text": e.describe()}), flush=True)
                else:
                    print(f"#{e.seq:<5} {e.seconds:9.2f}s  {e.describe()}", flush=True)
                if a.exec_cmd:
                    env = dict(os.environ, MON_SEQ=str(e.seq), MON_EVENT=e.name, MON_OLD=str(e.old), MON_NEW=str(e.new), MON_TEXT=e.describe())
                    subprocess.Popen(a.exec_cmd, shell=True, env=env)
        elif a.cmd == "vcp":
            code = int(a.code, 16)
            if a.op == "get":
                rc, mh, ml, ch, cl = log._get(code)
                print(json.dumps({"code": f"0x{code:02x}", "supported": rc == 0, "max": (mh << 8) | ml, "current": (ch << 8) | cl}))
            else:
                val = int(a.value, 0)
                for attempt in range(1, 6):
                    log._set(code, val)
                    time.sleep(0.15)
                    try:
                        rc, mh, ml, ch, cl = log._get(code)
                    except ProtocolError:
                        continue
                    cur = (ch << 8) | cl
                    if rc != 0 or cur == val or code in (0x60, 0xD6, 0x04, 0x05, 0x08):
                        print(f"ok (read back {cur}, attempt {attempt})" if rc == 0 else "sent (code has no readable value)")
                        break
                else:
                    print(f"error: value not confirmed after 5 attempts", file=sys.stderr)
                    return 1
        elif a.cmd == "inventory":
            names = {0x10: "brightness", 0x12: "contrast", 0x14: "color preset", 0x16: "red gain", 0x18: "green gain",
                     0x1A: "blue gain", 0x20: "h-position", 0x30: "v-position", 0x52: "active control", 0x60: "input",
                     0x62: "volume", 0x87: "sharpness", 0x8D: "mute", 0xAA: "orientation", 0xAC: "h-frequency",
                     0xAE: "v-frequency", 0xB2: "subpixel layout", 0xB6: "panel type", 0xC6: "app enable key",
                     0xC8: "controller type", 0xC9: "firmware level", 0xCC: "OSD language", 0xD6: "power mode",
                     0xDB: "image mode?", 0xDC: "picture mode", 0xDF: "VCP version", 0xE0: "samsung E0",
                     0xE7: "samsung E7", 0xF7: "samsung F7", 0xFD: "samsung FD"}
            for code, name in names.items():
                try:
                    rc, mh, ml, ch, cl = log._get(code)
                    print(f"0x{code:02X} {name:16s} " + (f"current={(ch << 8) | cl:<6} max={(mh << 8) | ml}" if rc == 0 else "unsupported"))
                except ProtocolError:
                    print(f"0x{code:02X} {name:16s} no reply")
        elif a.cmd == "peek":
            fa = FullAccess(log); addr = int(a.addr, 16); data = fa.peek(addr, int(a.length, 0))
            for i in range(0, len(data), 16):
                print(f"{addr + i:06x}: " + " ".join(f"{b:02x}" for b in data[i:i + 16]))
        elif a.cmd == "poke":
            FullAccess(log).poke(int(a.addr, 16), int(a.value, 0)); print("ok (verified by read-back)")
        elif a.cmd == "apply":
            FullAccess(log).apply(int(a.item, 0)); print("ok")
        elif a.cmd == "dump-settings":
            data = FullAccess(log).settings()
            if a.out:
                open(a.out, "wb").write(data)
            for i in range(0, len(data), 16):
                row = data[i:i + 16]
                tags = [SETTING_NAMES[i + j] for j in range(16) if i + j in SETTING_NAMES]
                print(f"{0x204000 + i:06x}: " + " ".join(f"{b:02x}" for b in row) + ("   # " + "; ".join(tags) if tags else ""))
        elif a.cmd == "switch":
            e = log.switch_input(0 if a.target == "dp" else 1)
            print(e.describe())
            return 0 if e.id == 0x11 else 1
    except ProtocolError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
