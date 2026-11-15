"""Client for the event log built into the patched LC34G55T firmware (VCP 0xEA-0xEF)."""
from .protocol import EventLog, Event, LiveState, EVENT_NAMES  # noqa: F401
from .backends import open_displays  # noqa: F401
