"""
Streaming API Smoke Test
========================

Purpose
-------
Starts the service on a spare port and exercises every endpoint, including
both streaming transports, then prints a pass or fail line for each check.
This is the verification step for the API in the same way that running each
pipeline script is the verification step for the offline modules.

Run from the repository root:

    python -m api.smoke_test

The test runs against a real server process rather than an in-process ASGI
transport, because the properties worth checking here are the ones an ASGI
transport hides: that the SSE response streams incrementally instead of
buffering to completion, and that the WebSocket upgrade and subscription
protocol work over a real socket.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parents[1]

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))
    return condition


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "NER_EWS_HOST": "127.0.0.1",
        "NER_EWS_PORT": str(port),
        # A fast tick keeps the test short. Simulated cadence stays at five
        # minutes so gap detection and health scoring behave as in production.
        "NER_EWS_TICK_INTERVAL_S": "0.25",
        "NER_EWS_SIM_STEP_S": "300",
        "NER_EWS_HEALTH_REFRESH_TICKS": "8",
        "NER_EWS_HEARTBEAT_S": "5",
        "PYTHONIOENCODING": "utf-8",
    })
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.service:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def wait_for_ready(base: str, process: subprocess.Popen, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            print(process.stdout.read() if process.stdout else "")
            return False
        try:
            response = httpx.get(f"{base}/health", timeout=2.0)
            if response.status_code == 200 and response.json().get("status") == "running":
                return True
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------
def test_rest(base: str) -> dict:
    print("\nREST endpoints")
    client = httpx.Client(base_url=base, timeout=15.0)

    status = client.get("/health").json()
    check("GET /health reports running", status["status"] == "running",
          f"tick {status['tick']}, {status['sensors']} sensors")
    check("Risk model loaded from artefacts",
          status["model"]["source"] == "trained_model", status["model"]["model_name"])
    check("Warm-up populated the simulated history",
          status["warmup_steps"] > 0, f"{status['warmup_steps']} steps")

    schema = client.get("/api/v1/schema").json()
    check("GET /api/v1/schema returns the canonical contract",
          "sensor_id" in schema["sensor_reading_schema"]
          and "expected_interval_s" in schema["sensor_reading_schema"])

    zones = client.get("/api/v1/zones").json()
    check("GET /api/v1/zones lists the fleet", zones["count"] == 6,
          f"{zones['count']} zones")
    zone_id = zones["zones"][0]["zone_id"]

    zone = client.get(f"/api/v1/zones/{zone_id}").json()
    check("GET /api/v1/zones/{id} includes conditions and sensors",
          "conditions" in zone and len(zone["sensors"]) == 7,
          f"{len(zone['sensors'])} sensors in {zone_id}")

    sensors = client.get("/api/v1/sensors").json()
    check("GET /api/v1/sensors lists every unit", sensors["count"] == 42,
          f"{sensors['count']} sensors")
    sensor_id = sensors["sensors"][0]["sensor_id"]

    filtered = client.get("/api/v1/sensors", params={"sensor_type": "piezometer"}).json()
    check("Sensor filtering by type works", filtered["count"] == 6,
          f"{filtered['count']} piezometers")

    readings = client.get(f"/api/v1/sensors/{sensor_id}/readings",
                          params={"limit": 50}).json()
    schema_fields = set(schema["sensor_reading_schema"])
    first = readings["readings"][0] if readings["readings"] else {}
    check("Readings are buffered from the warm-up", readings["count"] > 0,
          f"{readings['count']} readings")
    check("Readings match SENSOR_READING_SCHEMA exactly",
          set(first) == schema_fields,
          f"missing {sorted(schema_fields - set(first))}" if set(first) != schema_fields else "")

    health = client.get(f"/api/v1/sensors/{sensor_id}/health").json()
    check("Sensor health is scored", health.get("health_score") is not None,
          f"{health.get('health_score')} ({health.get('status')})")

    fleet = client.get("/api/v1/fleet/health").json()
    check("Fleet health covers every sensor", len(fleet["sensors"]) == 42,
          f"mean {fleet['summary']['mean_health_score']}")

    risk = client.get("/api/v1/risk").json()
    levels = {z["zone_id"]: z["alert_level"] for z in risk["zones"]}
    check("Risk is assessed for every zone", len(risk["zones"]) == 6, str(levels))
    check("Risk records carry the output contract",
          all(k in risk["zones"][0] for k in
              ("risk_score", "risk_level", "probability", "contributing_factors")))

    snapshot = client.get("/api/v1/snapshot").json()
    check("Snapshot returns zones, sensors and alerts",
          len(snapshot["zones"]) == 6 and len(snapshot["sensors"]) == 42)

    check("Unknown zone returns 404",
          client.get("/api/v1/zones/NER-ZXX").status_code == 404)
    check("Unknown event filter returns 400",
          client.get("/api/v1/stream", params={"events": "not_an_event"}).status_code == 400)

    client.close()
    return {"zone_id": zone_id, "sensor_id": sensor_id}


# ---------------------------------------------------------------------------
# Server-Sent Events
# ---------------------------------------------------------------------------
def test_sse(base: str, zone_id: str) -> None:
    print("\nServer-Sent Events")
    events = []
    started = time.time()
    first_at = None

    with httpx.Client(timeout=45.0) as client:
        with client.stream("GET", f"{base}/api/v1/stream",
                           params={"zones": zone_id, "snapshot": "true"}) as response:
            check("Stream responds with text/event-stream",
                  response.headers.get("content-type", "").startswith("text/event-stream"),
                  response.headers.get("content-type", ""))
            buffer = []
            for line in response.iter_lines():
                if line:
                    buffer.append(line)
                    continue
                packet = _parse_sse("\n".join(buffer))
                buffer = []
                if packet:
                    if first_at is None:
                        first_at = time.time()
                    events.append(packet)
                if len(events) >= 40:
                    break

    kinds = {}
    for event_name, _ in events:
        kinds[event_name] = kinds.get(event_name, 0) + 1

    check("Stream opens with a handshake event",
          events and events[0][0] == "stream_open")
    check("Snapshot is delivered before live events",
          any(name == "snapshot" for name, _ in events[:3]))
    check("Live readings arrive on the stream",
          kinds.get("sensor_reading", 0) > 0, f"{kinds.get('sensor_reading', 0)} readings")
    check("Zone risk is published", kinds.get("zone_risk", 0) > 0,
          f"{kinds.get('zone_risk', 0)} risk events")
    check("Response streams incrementally rather than buffering",
          first_at is not None and (first_at - started) < 5.0,
          f"first event after {round((first_at or started) - started, 3)}s")

    readings = [payload for name, payload in events if name == "sensor_reading"]
    check("Zone filter is honoured",
          all(r["data"]["zone_id"] == zone_id for r in readings),
          f"{len(readings)} readings, all from {zone_id}")
    seqs = [r["seq"] for r in readings]
    check("Sequence numbers are monotonic", seqs == sorted(seqs))
    print(f"  event mix: {kinds}")


def _parse_sse(block: str):
    if not block or block.startswith(":"):
        return None
    event_name, data = None, None
    for line in block.split("\n"):
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
    if event_name is None or data is None:
        return None
    try:
        return event_name, json.loads(data)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def _websocket_session(base: str, zone_id: str) -> dict:
    url = base.replace("http://", "ws://") + "/api/v1/ws"
    collected = {"open": None, "pong": False, "resubscribed": False,
                 "readings_before": 0, "readings_after": 0, "other_zone_after": 0}

    async with websockets.connect(url, open_timeout=20) as socket_conn:
        first = json.loads(await asyncio.wait_for(socket_conn.recv(), timeout=20))
        collected["open"] = first.get("event")

        await socket_conn.send(json.dumps({"action": "ping"}))
        deadline = time.time() + 20
        while time.time() < deadline:
            message = json.loads(await asyncio.wait_for(socket_conn.recv(), timeout=20))
            if message.get("event") == "pong":
                collected["pong"] = True
                break
            if message.get("event") == "sensor_reading":
                collected["readings_before"] += 1

        await socket_conn.send(json.dumps({
            "action": "subscribe", "events": ["sensor_reading"], "zones": [zone_id]}))
        deadline = time.time() + 20
        while time.time() < deadline:
            message = json.loads(await asyncio.wait_for(socket_conn.recv(), timeout=20))
            if message.get("event") == "subscription_updated":
                collected["resubscribed"] = True
                break

        deadline = time.time() + 20
        while time.time() < deadline and collected["readings_after"] < 12:
            message = json.loads(await asyncio.wait_for(socket_conn.recv(), timeout=20))
            if message.get("event") != "sensor_reading":
                continue
            collected["readings_after"] += 1
            if message["data"]["zone_id"] != zone_id:
                collected["other_zone_after"] += 1

    return collected


def test_websocket(base: str, zone_id: str) -> None:
    print("\nWebSocket")
    result = asyncio.run(_websocket_session(base, zone_id))
    check("Connection opens with a handshake", result["open"] == "stream_open")
    check("Ping is answered with pong", result["pong"])
    check("Subscription can be changed while connected", result["resubscribed"])
    check("Readings arrive after resubscription", result["readings_after"] >= 12,
          f"{result['readings_after']} readings")
    check("Updated filter is applied", result["other_zone_after"] == 0,
          f"{result['other_zone_after']} readings from other zones")


# ---------------------------------------------------------------------------
# Simulation controls and the alerting path
# ---------------------------------------------------------------------------
def test_simulation_controls(base: str, zone_id: str, sensor_id: str) -> None:
    print("\nSimulation controls and alerting")
    client = httpx.Client(base_url=base, timeout=30.0)

    before = client.get(f"/api/v1/risk/{zone_id}").json()
    response = client.post("/api/v1/simulation/rainfall-surge",
                           json={"zone_id": zone_id, "rate_mm_hr": 90,
                                 "duration_minutes": 2880})
    check("Rainfall surge is accepted", response.status_code == 200)

    # Let the surge accumulate through the rainfall window and the risk refresh.
    deadline = time.time() + 45
    after = before
    while time.time() < deadline:
        after = client.get(f"/api/v1/risk/{zone_id}").json()
        if after["physics"]["saturation_ratio"] > before["physics"]["saturation_ratio"] + 0.2:
            break
        time.sleep(1.0)

    check("Surge raises saturation",
          after["physics"]["saturation_ratio"] > before["physics"]["saturation_ratio"],
          f"{before['physics']['saturation_ratio']} to {after['physics']['saturation_ratio']}")
    check("Surge lowers the Factor of Safety",
          after["physics"]["factor_of_safety"] < before["physics"]["factor_of_safety"],
          f"{before['physics']['factor_of_safety']} to {after['physics']['factor_of_safety']}")
    check("Surge raises the risk score",
          after["risk_score"] >= before["risk_score"],
          f"{before['risk_score']} to {after['risk_score']}")

    alerts = client.get("/api/v1/alerts").json()
    check("An alert was raised for the surged zone",
          any(a["zone_id"] == zone_id for a in alerts["alerts"]),
          f"{alerts['count']} alerts total")

    fault = client.post("/api/v1/simulation/sensor-fault",
                        json={"sensor_id": sensor_id, "fault": "comms_dropout",
                              "duration_ticks": 20})
    check("Sensor fault injection is accepted", fault.status_code == 200)
    check("Invalid fault name is rejected",
          client.post("/api/v1/simulation/sensor-fault",
                      json={"sensor_id": sensor_id, "fault": "nonsense"}).status_code == 400)

    time.sleep(4)
    sensor = client.get(f"/api/v1/sensors/{sensor_id}").json()
    check("Injected fault is visible on the sensor",
          sensor["fault_state"] == "comms_dropout", sensor["fault_state"])

    cleared = client.post("/api/v1/simulation/clear").json()
    check("Faults can be cleared", cleared["accepted"], f"{cleared['faults_cleared']} cleared")

    stats = client.get("/api/v1/stream/stats").json()
    check("Stream statistics are reported", stats["published"] > 0,
          f"{stats['published']} events published")

    client.close()


# ---------------------------------------------------------------------------
def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"Starting service on {base}")
    process = start_server(port)

    try:
        if not wait_for_ready(base, process):
            print("Service failed to start")
            return 1
        print("Service ready\n" + "=" * 66)

        context = test_rest(base)
        test_sse(base, context["zone_id"])
        test_websocket(base, context["zone_id"])
        test_simulation_controls(base, context["zone_id"], context["sensor_id"])
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    print("=" * 66)
    print(f"{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for name in FAILED:
            print(f"  failed: {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
