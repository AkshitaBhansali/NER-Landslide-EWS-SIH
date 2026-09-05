"""
In-Process Stream Bus
=====================

Purpose
-------
Fan-out layer between the single sensor simulator loop and an arbitrary number
of connected clients. The simulator publishes once per event; every matching
subscriber receives its own copy on its own queue, so one slow client cannot
stall the simulator or any other client.

Backpressure policy
-------------------
Each subscriber holds a bounded queue. When a client reads more slowly than
the simulator publishes, the oldest event in that client's queue is discarded
to make room for the newest, and the subscriber's `dropped` counter is
incremented. For an early warning stream the newest reading is always the more
useful one, so dropping the oldest is preferred to blocking the producer or
disconnecting the client. Clients can detect loss through the monotonic `seq`
field on every event, and can recover missed readings from the REST history
endpoints.

Filtering
---------
Subscribers declare the event types, zones, sensors and sensor types they care
about at subscription time. Filtering happens at publish time, so a client
subscribed to one zone never pays the deserialisation cost of the rest of the
fleet.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from typing import Iterable, Optional


# Event types published on the bus.
EVENT_SENSOR_READING = "sensor_reading"
EVENT_ZONE_RISK = "zone_risk"
EVENT_ZONE_ALERT = "zone_alert"
EVENT_SENSOR_HEALTH = "sensor_health"
EVENT_SENSOR_FAULT = "sensor_fault"
EVENT_TICK = "tick"

ALL_EVENT_TYPES = (
    EVENT_SENSOR_READING,
    EVENT_ZONE_RISK,
    EVENT_ZONE_ALERT,
    EVENT_SENSOR_HEALTH,
    EVENT_SENSOR_FAULT,
    EVENT_TICK,
)


@dataclass(frozen=True)
class StreamEvent:
    """A single published event with the routing keys used for filtering."""

    seq: int
    event: str
    emitted_at: str
    data: dict
    zone_id: Optional[str] = None
    sensor_id: Optional[str] = None
    sensor_type: Optional[str] = None

    def envelope(self) -> dict:
        return {
            "seq": self.seq,
            "event": self.event,
            "emitted_at": self.emitted_at,
            "data": self.data,
        }


def _as_set(values: Optional[Iterable[str]]) -> Optional[set]:
    if not values:
        return None
    cleaned = {str(v).strip() for v in values if str(v).strip()}
    return cleaned or None


@dataclass
class Subscription:
    """One connected client. Owns a bounded queue and a set of filters."""

    subscriber_id: str
    queue: asyncio.Queue
    events: Optional[set] = None
    zones: Optional[set] = None
    sensors: Optional[set] = None
    sensor_types: Optional[set] = None
    delivered: int = 0
    dropped: int = 0
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def set_filters(self, events=None, zones=None, sensors=None, sensor_types=None) -> None:
        self.events = _as_set(events)
        self.zones = _as_set(zones)
        self.sensors = _as_set(sensors)
        self.sensor_types = _as_set(sensor_types)

    def matches(self, ev: StreamEvent) -> bool:
        if self.events is not None and ev.event not in self.events:
            return False
        if self.zones is not None and (ev.zone_id is None or ev.zone_id not in self.zones):
            return False
        if self.sensors is not None and (ev.sensor_id is None or ev.sensor_id not in self.sensors):
            return False
        if self.sensor_types is not None and (
            ev.sensor_type is None or ev.sensor_type not in self.sensor_types
        ):
            return False
        return True

    def describe(self) -> dict:
        return {
            "subscriber_id": self.subscriber_id,
            "connected_at": self.connected_at,
            "queued": self.queue.qsize(),
            "delivered": self.delivered,
            "dropped": self.dropped,
            "filters": {
                "events": sorted(self.events) if self.events else None,
                "zones": sorted(self.zones) if self.zones else None,
                "sensors": sorted(self.sensors) if self.sensors else None,
                "sensor_types": sorted(self.sensor_types) if self.sensor_types else None,
            },
        }


class StreamBus:
    """Publish and subscribe hub for the live sensor stream."""

    def __init__(self, queue_size: int = 512, max_subscribers: int = 64):
        self.queue_size = queue_size
        self.max_subscribers = max_subscribers
        self._subscribers: dict = {}
        self._seq = count(1)
        self.published = 0
        self.last_event_at: Optional[str] = None

    # --- subscriber management ---
    def subscribe(self, subscriber_id: str, events=None, zones=None,
                  sensors=None, sensor_types=None) -> Subscription:
        if len(self._subscribers) >= self.max_subscribers:
            raise RuntimeError(
                f"Subscriber limit reached ({self.max_subscribers}). "
                "Close an existing stream or raise NER_EWS_MAX_SUBSCRIBERS."
            )
        sub = Subscription(subscriber_id=subscriber_id, queue=asyncio.Queue(maxsize=self.queue_size))
        sub.set_filters(events=events, zones=zones, sensors=sensors, sensor_types=sensor_types)
        self._subscribers[subscriber_id] = sub
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscribers.pop(sub.subscriber_id, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # --- publishing ---
    def publish(self, event: str, data: dict, *, zone_id: str = None,
                sensor_id: str = None, sensor_type: str = None,
                emitted_at: str = None) -> StreamEvent:
        ev = StreamEvent(
            seq=next(self._seq),
            event=event,
            emitted_at=emitted_at or datetime.now(timezone.utc).isoformat(),
            data=data,
            zone_id=zone_id,
            sensor_id=sensor_id,
            sensor_type=sensor_type,
        )
        self.published += 1
        self.last_event_at = ev.emitted_at

        for sub in list(self._subscribers.values()):
            if not sub.matches(ev):
                continue
            try:
                sub.queue.put_nowait(ev)
            except asyncio.QueueFull:
                # Drop the oldest event for this subscriber only. The newest
                # reading is the operationally relevant one, and the client can
                # detect the loss through the seq gap.
                try:
                    sub.queue.get_nowait()
                    sub.queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                sub.dropped += 1
                try:
                    sub.queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass
        return ev

    def publish_many(self, events: Iterable[tuple]) -> None:
        """Publishes a batch of (event, data, routing_kwargs) tuples."""
        for event, data, routing in events:
            self.publish(event, data, **routing)

    def stats(self) -> dict:
        return {
            "published": self.published,
            "subscribers": self.subscriber_count,
            "queue_size": self.queue_size,
            "max_subscribers": self.max_subscribers,
            "last_event_at": self.last_event_at,
            "total_dropped": sum(s.dropped for s in self._subscribers.values()),
            "connections": [s.describe() for s in self._subscribers.values()],
        }
