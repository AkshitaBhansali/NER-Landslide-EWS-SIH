# Offline architecture and warning delivery

Krish Modi — backend, integration, alert engine, offline architecture.

This covers the two research items in my brief: **offline-first / low-network
support**, and **SMS / LoRaWAN / satellite / store-and-forward delivery**. Both are
implemented, not just designed; the code references are inline.

---

## 1. The problem, stated honestly

The deployment target is a district office and a field officer in Dima Hasao, Tawang
or Mangan **during a monsoon** — which is precisely when the data link is worst and
the platform matters most. Two failures follow from that:

- A warning system that requires connectivity fails at the moment it is needed.
- A field report that cannot be captured offline is a report that never exists,
  because nobody re-types it three hours later on a working link.

So the design assumption is inverted: **the network is assumed absent and treated as
an occasional bonus**, rather than assumed present and patched when it fails.

---

## 2. Existing approach → limitation → our improvement

The common research format for this project:

| Existing approach | Limitation | Ours |
|---|---|---|
| Cell broadcast (CAP/SACHET, NDMA) | Excellent reach, but authority-gated and one-way. No field capture, no acknowledgement, no proof of delivery | Keep it as the public-broadcast leg; add a two-way ledger so we know what was sent and whether it left the queue |
| App push notification | Requires data connectivity and an installed app — the two things missing in a remote hill village | SMS is the primary channel; push is additive. Templates fit one GSM-7 part |
| Online-only dashboards (most state DM portals) | Blank page when the link drops | `GET /api/sync/bundle` — the console works fully offline on cached data |
| `localStorage` queueing | Media blobs blow the ~5 MB quota; a single crack photo can exceed it | IndexedDB for metadata + attachments (frontend side); server accepts the replay idempotently |
| Naive "POST on reconnect" | Flaky uplinks retry and create duplicate reports, which fake corroboration | `client_id` idempotency ledger — replay returns the original record |
| Gateway-side dedup | Puts state in the least reliable, least maintained device on the network | Server-side dedup on `(sensor_id, timestamp)`; the gateway can be dumb and retry blindly |

The duplicate-report point is worth stating plainly in the pitch: **five copies of one
landslide report is worse than none**, because three independent-looking reports from
one village reads as corroboration and will move a response crew.

---

## 3. Offline architecture

### 3.1 Snapshot — `GET /api/sync/bundle?district=`

Everything the app needs to be *useful* with no network, sized to cache in IndexedDB:

- `zones` — current scores, levels, geometry
- `roads`, `villages` — connectivity status
- `active_alerts` — what is currently open
- `thresholds` — so the device can evaluate locally
- `escalation_contacts` — **authority phone numbers**

That last one is the item most designs forget. When the data link is gone but the
voice network is up — frequently the case, they are different infrastructure — a
field officer with a cached contact list can still escalate by phone. The platform
degrades to "a phone book that knows which slope is failing" rather than to nothing.

Returns an `ETag` and `Cache-Control: private, max-age=300`. A reconnecting device
sends `If-None-Match` and skips the download entirely when nothing moved.

### 3.2 Delta — `GET /api/sync/delta?since=`

Changed-since feed for zones and alerts. A device reconnecting after two hours pulls
a few kilobytes, not the whole bundle. On a metered rural link that is the difference
between syncing and not bothering.

### 3.3 Replay — `POST /api/sync/batch`

```json
{
  "device_id": "field-tablet-7",
  "operations": [
    { "op": "FIELD_REPORT", "client_id": "device7-0042",
      "payload": { "incident_type": "ROAD_BLOCKAGE", "district_id": "mz-aizawl",
                   "lat": 23.74, "lng": 92.69, "severity": "CRITICAL" } },
    { "op": "ALERT_ACK", "client_id": "device7-0043",
      "payload": { "alert_id": "ALT-1011", "actor": "PWD Unit 3" } }
  ]
}
```

Response is **per-operation**, never all-or-nothing:

```json
{ "received": 2, "accepted": 1, "duplicates": 1, "failed": 0,
  "results": [
    { "client_id": "device7-0042", "status": "ACCEPTED",  "server_id": "FR-7F82A2" },
    { "client_id": "device7-0043", "status": "DUPLICATE", "server_id": "ALT-1011" }
  ]}
```

One malformed report in a queue of twenty must not block the other nineteen — the
device would retry the whole batch forever and nothing would ever land. Tested:
`test_batch_isolates_a_bad_operation`.

### 3.4 Conflict policy

| State | Winner | Why |
|---|---|---|
| Report body, GPS, capture time | **Client** | The device observed the ground; the server did not |
| Alert status, verification | **Server** | If it was handled while the device was dark, the queued acknowledgement is stale, not newer |

Implemented in `routers/sync.py:batch` — an `ALERT_ACK` replay only applies when the
alert is still `NEW`.

### 3.5 What the frontend still needs to do

Server side is done. Remaining work is Akshita's, and the shapes are already fixed:

1. **IndexedDB**, not `localStorage` — one store for report metadata, one for
   attachment blobs.
2. **Service worker** with a `sync` event, or the `online` listener `AppContext`
   already has, calling `POST /api/sync/batch`.
3. **Retry with backoff**, mark `FAILED` after N attempts, surface the Retry button
   that already exists on `/field-reports`.
4. **Generate `client_id` at capture time**, not at send time. This is the whole
   mechanism — an ID minted on send is a different ID on every retry, and idempotency
   silently stops working.
5. **GPS via `navigator.geolocation`** with a district-centroid fallback, so a report
   is never lost to a denied permission.

---

## 4. Warning delivery

### 4.1 Channel comparison

| Channel | Reach | Latency | Cost | Works when data is down | Role here |
|---|---|---|---|---|---|
| **SMS (P2P gateway)** | Any handset | Seconds–minutes | Per message | Yes | **Primary** |
| Cell broadcast (CAP) | Every handset in a cell | Seconds | Flat | Yes | Public tier, needs NDMA integration |
| App push | Smartphone + data | Seconds | Free | No | Additive, authority console |
| **LoRaWAN** | ~2–15 km, sensor-class payloads | Seconds | Gateway capex | Yes (own network) | **Sensor uplink**, not warnings |
| **Satellite (IoT/BGAN)** | Anywhere | Seconds–minutes | High | Yes | Fallback for isolated gateways |
| Siren / PA | Village-scale | Instant | Capex | Yes | Last-mile, out of software scope |

LoRaWAN carries sensors *to* us; SMS carries warnings *out*. Conflating them is a
common error — LoRa payloads are tens of bytes and the network is uplink-biased, so
it is the wrong pipe for a warning message.

### 4.2 Tier → audience routing

`core/notify.py:TIER_AUDIENCES`, from the NDMA/GSI table:

| Tier | Score | Recipients |
|---|---|---|
| 🟢 GREEN | < 41 | nobody |
| 🟡 YELLOW | 41–65 | District Magistrate, SDRF |
| 🟠 ORANGE | 66–85 | + ward members |
| 🔴 RED | ≥ 86 | + geo-fenced public broadcast |

**Sending every alert to everyone is how a warning system trains an entire district
to ignore it**, and that failure mode has cost lives in real deployments. The tier
table is the single most important safeguard in this module.

Second safeguard: a `low_confidence` alert is stripped of its `PUBLIC` audience
before dispatch. The instruments we would be asking people to trust are exactly the
ones already known to be unreliable — so it goes to a human for verification instead.

### 4.3 Message design

Templates lead with the **action**, not the risk score. Nobody evacuates because of
"risk score 87".

```
URGENT: Landslide danger at Sairang approach, Aizawl.
Move away from slopes and avoid NH-6 now. Helpline 1077.
```

- Kept under 160 GSM-7 characters where possible. A three-part SMS arrives out of
  order on a congested rural cell and reads as gibberish.
- Per-language: `en`, `hi`, `as`, `bn`, `ne` implemented; `mni`, `kha`, `lus`
  registered and reported as incomplete by `GET /api/settings/languages`, so the gap
  is visible rather than silent.
- Missing translation falls back to English rather than sending nothing. A warning in
  the wrong language still beats silence; an untranslated template is a bug to file,
  not a reason to drop the message.

### 4.4 Store-and-forward

`StoreForwardProvider` marks a dispatch `DEFERRED` rather than `FAILED`. The retry
worker (`POST /api/alerts/delivery/retry`, also called after every risk cycle) drains
the queue when the link returns, preserving order.

Order matters more than it looks: a district must not receive a stand-down before the
warning it stands down from.

Every attempt is a row in `dispatches` with `attempts`, `last_error`, `queued_at`,
`sent_at`. After `SMS_MAX_ATTEMPTS` a message becomes `ABANDONED` — visible, not
silently dropped. `GET /api/alerts/{id}/timeline` shows the full delivery picture per
alert.

### 4.5 Integrating a real gateway

Set `SMS_PROVIDER=http`, `SMS_ENDPOINT`, `SMS_API_KEY`. The payload is the common
denominator of the state gateway and commercial aggregators:

```json
{ "to": "+919012345678", "message": "…", "sender": "NERLEW" }
```

Anything more exotic is a ~20-line class in `core/notify.py` implementing
`send(msisdn, body) -> SendResult`. Nothing else changes.

---

## 5. What is not built

Stated so nobody is surprised in a demo:

1. **No CAP/SACHET integration.** Public broadcast currently goes through the same
   SMS path. Real cell broadcast is authority-gated and needs NDMA onboarding.
2. **No real LoRaWAN gateway.** `/api/ingest/readings` accepts what a gateway would
   POST and handles replay correctly, but no gateway is attached.
3. **No rate limiting** on the public field-report endpoint.
4. **Media is on local disk**, not object storage.
5. **Service worker is frontend work and not written yet** — the server contract it
   needs is complete and tested.
