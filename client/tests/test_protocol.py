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


# ---- protocol 3 (firmware v3.2)
def test_protocol3_capabilities(fm):
    log = EventLog(fm)
    assert log.info()["version"] == 3
    caps = log.capabilities()
    assert caps is not None and caps.bits == 0x01FF
    assert caps.has("power-wake") and caps.has("switch-guard") and caps.has("memory-access")
    assert caps.cable(0) and caps.cable(1) and not caps.soft_standby and not caps.source_detect_manual
    FullAccess(log).poke(SETTINGS_BASE + 0x14F, 1)
    assert log.capabilities().source_detect_manual


def test_protocol2_has_no_capabilities():
    log = EventLog(FakeMonitor(protocol=2))
    assert log.supported() and log.info()["version"] == 2
    assert log.capabilities() is None and log.power_mode() is None
    with pytest.raises(ProtocolError):
        log.set_power(4)


def test_boot_logs_power_state_and_cables(fm):
    evs = EventLog(fm).history(10)
    assert [e.name for e in evs] == ["boot", "power-state", "cable-mask"]
    assert (evs[1].old, evs[1].new) == (0, 1) and "cold boot" in evs[1].describe()
    assert (evs[2].old, evs[2].new) == (0xEE, 3) and "DisplayPort+HDMI" in evs[2].describe()


def test_soft_standby_and_wake_by_ddc(fm):
    log = EventLog(fm)
    assert log.power_mode() == 1
    assert log.set_power(4) == 4 and log.capabilities().soft_standby
    assert log.set_power(1) == 1 and not log.capabilities().soft_standby
    evs = [(e.id, e.old, e.new) for e in log.history(4)]
    assert evs == [(0x13, 1, 4), (0x14, 1, 4), (0x13, 1, 1), (0x14, 1, 1)]


def test_soft_standby_wake_by_key(fm):
    log = EventLog(fm)
    log.set_power(4)
    fm.press_key()
    e = log.history(1)[0]
    assert (e.id, e.old, e.new) == (0x14, 2, 1) and log.power_mode() == 1
    fm.press_key()  # not in soft standby: no event
    assert log.history(1)[0].seq == e.seq


def test_wake_without_soft_standby_logs_only_the_request(fm):
    log = EventLog(fm)
    fm.set_vcp(0xD6, 1)
    assert log.history(1)[0].name == "ddc-power-request" and log.power_mode() == 1


def test_real_power_off_leaves_the_bus(fm):
    log = EventLog(fm, retries=1)
    log.set_power(5)
    assert fm.ring[fm.seq % 64][1:4] == (0x14, 1, 5)
    with pytest.raises(ProtocolError):
        log.info()


def test_switch_guard_refuses_input_without_cable():
    fm = FakeMonitor(switch_delay=0.05, port=1, cables=0b10)
    log = EventLog(fm)
    assert not log.capabilities().cable(0)
    e = log.switch_input(0, timeout=3)
    assert e.name == "switch-failed" and (e.old, e.new) == (0, 1) and fm.port == 1
    first, second = log.history(2)
    assert (first.id, first.old, first.new) == (0x10, 1, 0x09) and second.id == 0x12


def test_cable_mask_event(fm):
    log = EventLog(fm)
    fm.set_cables(0b01)
    e = log.history(1)[0]
    assert (e.name, e.old, e.new) == ("cable-mask", 3, 1) and "DisplayPort" in e.describe()
    assert log.capabilities().cable_mask == 1
