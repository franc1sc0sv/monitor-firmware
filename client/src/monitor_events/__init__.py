"""Client for the event log built into the patched LC34G55T firmware (VCP 0xEA-0xEF)."""

from .backends import open_displays  # noqa: F401
from .protocol import EVENT_NAMES, Event, EventLog, LiveState  # noqa: F401
