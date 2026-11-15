import time

import pytest

from monitor_events.protocol import SERIAL_MASK, EventLog, FullAccess, ProtocolError, mask_serial
from monitor_events.simulate import SETTINGS_BASE, FakeMonitor


@pytest.fixture
def fm():
    return FakeMonitor(switch_delay=0.05)


def test_supported_and_info(fm):
    log = EventLog(fm)
    assert log.supported()
    assert log.info()["ring"] == 64 and log.info()["seq"] >= 1


def test_history_and_event_read(fm):
    log = EventLog(fm)
    evs = log.history(10)
    assert evs[0].name == "boot"


def test_switch_verdict_done(fm):
    e = EventLog(fm).switch_input(0, timeout=3)
    assert e.name == "switch-done" and fm.port == 0


def test_switch_verdict_failed():
    fm = FakeMonitor(switch_delay=0.05, lock_ok=False)
    e = EventLog(fm).switch_input(0, timeout=3)
    assert e.name == "switch-failed"


def test_set_vcp_confirms(fm):
    r = EventLog(fm).set_vcp(0x10, 70)
    assert r["confirmed"] and r["current"] == 70


def test_peek_poke_window(fm):
    fa = FullAccess(EventLog(fm))
    fa.poke(SETTINGS_BASE + 0x1D3, 55)
    assert fa.peek(SETTINGS_BASE + 0x1D3, 1) == bytes([55])
    with pytest.raises(ValueError):
        fa.poke(0x300000, 1)


def test_setting_event_logged(fm):
    log = EventLog(fm)
    FullAccess(log).poke(SETTINGS_BASE + 0x1D3, 33)
    e = log.history(1)[0]
    assert e.name == "setting-changed" and "0x2041d3" in e.describe()


def test_serial_is_masked_by_default(fm):
    fa = FullAccess(EventLog(fm))
    data = fa.settings()
    assert data[0x9A : 0x9A + 4] == b"****"
    assert fa.settings(raw=True)[0x9A : 0x9A + 4] == b"FAKE"
    assert mask_serial(SETTINGS_BASE + 0x9A, b"AB") == b"**" and len(SERIAL_MASK) == 32


def test_unsupported_code_reports_rc(fm):
    rc, *_ = EventLog(fm).get_vcp(0x99)
    assert rc == 1


def test_watch_yields_new_events(fm):
    log = EventLog(fm)
    gen = log.watch(interval=0.01, since=log.info()["seq"])
    fm.set_vcp(0x10, 12)
    e = next(gen)
    assert e.name == "setting-changed"


def test_no_reply_raises():
    class Dead:
        name = "dead"

        def get_vcp_raw(self, code):
            return None

        def set_vcp(self, code, value):
            raise OSError("bus")

    with pytest.raises(ProtocolError):
        EventLog(Dead(), retries=1).info()
    time.sleep(0)
