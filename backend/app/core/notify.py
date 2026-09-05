"""Warning delivery.

Two things this module gets right that a naive "send SMS on alert" does not:

1. AUDIENCE IS A FUNCTION OF TIER, NOT SEVERITY ALONE. The NDMA/GSI tier table
   decides who hears about it. A Yellow goes to the DM and SDRF only. Red goes to
   the public. Sending every alert to everyone is how a warning system trains an
   entire district to ignore it, and that failure mode has killed people.

2. THE MESSAGE IS THE PRODUCT. A villager receiving an SMS in a language they do
   not read has not been warned. Templates are per-language and lead with the
   action, not the risk score — nobody evacuates because of "risk score 87".

Providers are pluggable. `console` logs (demo), `http` posts to a gateway, and
`store_forward` queues for a satellite/LoRa uplink that may not be up right now.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, Dispatch, Recipient, utcnow

log = logging.getLogger("ner.notify")

# --------------------------------------------------------------------------- #
# Tier -> audience routing (from the NDMA/GSI table in the methodology note)
# --------------------------------------------------------------------------- #
TIER_AUDIENCES: dict[str, list[str]] = {
    "GREEN": [],                                    # no message sent
    "YELLOW": ["AUTHORITY"],                        # DM, SDRF
    "ORANGE": ["AUTHORITY", "LOCAL"],               # + ward members
    "RED": ["AUTHORITY", "LOCAL", "PUBLIC"],        # + geo-fenced public broadcast
}

TIER_STATUS = {
    "GREEN": "No warning \u2014 normal conditions.",
    "YELLOW": "Watch \u2014 soil is saturated; landslides possible if rain continues.",
    "ORANGE": "Alert \u2014 threshold crossed; high probability of slope failure.",
    "RED": "Action \u2014 critical danger; imminent slope failure risk.",
}

# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
# Kept under 160 GSM-7 characters where possible so a warning is one SMS, not three.
# Three parts arrive out of order on a congested rural cell and read as gibberish.
TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "AUTHORITY": ("[{tier}] Landslide {severity} - {location}, {district}. "
                      "Risk {score}/100, window {window}h. {action} Ref {alert_id}"),
        "LOCAL": ("[{tier}] Landslide warning: {location}, {district}. "
                  "Slope failure likely within {window}h. Alert residents. Ref {alert_id}"),
        "PUBLIC": ("URGENT: Landslide danger at {location}, {district}. "
                   "Move away from slopes and avoid {roads} now. Helpline 1077."),
    },
    "hi": {
        "AUTHORITY": ("[{tier}] \u092d\u0942\u0938\u094d\u0916\u0932\u0928 {severity} - {location}, {district}\u0964 "
                      "\u091c\u094b\u0916\u093f\u092e {score}/100, {window} \u0918\u0902\u091f\u0947\u0964 \u0938\u0902\u0926\u0930\u094d\u092d {alert_id}"),
        "LOCAL": ("[{tier}] \u092d\u0942\u0938\u094d\u0916\u0932\u0928 \u091a\u0947\u0924\u093e\u0935\u0928\u0940: {location}, {district}\u0964 "
                  "{window} \u0918\u0902\u091f\u0947 \u092e\u0947\u0902 \u0916\u0924\u0930\u093e\u0964 \u0932\u094b\u0917\u094b\u0902 \u0915\u094b \u0938\u0942\u091a\u093f\u0924 \u0915\u0930\u0947\u0902\u0964"),
        "PUBLIC": ("\u0924\u0924\u094d\u0915\u093e\u0932: {location}, {district} \u092e\u0947\u0902 \u092d\u0942\u0938\u094d\u0916\u0932\u0928 \u0915\u093e \u0916\u0924\u0930\u093e\u0964 "
                   "\u0922\u0932\u093e\u0928 \u0938\u0947 \u0926\u0942\u0930 \u0930\u0939\u0947\u0902\u0964 \u0939\u0947\u0932\u094d\u092a\u0932\u093e\u0907\u0928 1077\u0964"),
    },
    "as": {
        "AUTHORITY": ("[{tier}] \u09ad\u09c2\u09ae\u09bf\u09b8\u09cd\u0996\u09b2\u09a8 {severity} - {location}, {district}\u0964 "
                      "\u09dd\u09c1\u0981\u0995\u09bf {score}/100, {window} \u0998\u09a3\u09cd\u099f\u09be\u0964 {alert_id}"),
        "LOCAL": ("[{tier}] \u09ad\u09c2\u09ae\u09bf\u09b8\u09cd\u0996\u09b2\u09a8 \u09b8\u09a4\u09b0\u09cd\u0995\u09ac\u09be\u09a3\u09c0: {location}, {district}\u0964 "
                  "{window} \u0998\u09a3\u09cd\u099f\u09be\u09a4 \u09ac\u09bf\u09aa\u09a6\u0964"),
        "PUBLIC": ("\u099c\u09b0\u09c1\u09b0\u09c0: {location}, {district}\u09a4 \u09ad\u09c2\u09ae\u09bf\u09b8\u09cd\u0996\u09b2\u09a8\u09b0 \u0986\u09b6\u0999\u09cd\u0995\u09be\u0964 "
                   "\u09aa\u09be\u09b9\u09be\u09b0\u09b0 \u09aa\u09b0\u09be \u0986\u0981\u09a4\u09b0\u09bf \u09a5\u0995\u0995\u0964 1077\u0964"),
    },
    "bn": {
        "PUBLIC": ("\u099c\u09b0\u09c1\u09b0\u09bf: {location}, {district}-\u098f \u09ad\u09c2\u09ae\u09bf\u09a7\u09b8\u09c7\u09b0 \u0986\u09b6\u0999\u09cd\u0995\u09be\u0964 "
                   "\u09aa\u09be\u09b9\u09be\u09dc \u098f\u09dc\u09bf\u09df\u09c7 \u099a\u09b2\u09c1\u09a8\u0964 \u09b9\u09c7\u09b2\u09aa\u09b2\u09be\u0987\u09a8 1077\u0964"),
    },
    "ne": {
        "PUBLIC": ("\u0924\u0941\u0930\u0928\u094d\u0924: {location}, {district} \u092e\u093e \u092a\u0939\u093f\u0930\u094b \u091c\u093e\u0928\u0947 \u0916\u0924\u0930\u093e\u0964 "
                   "\u092d\u093f\u0930\u093e\u0932\u094b \u0920\u093e\u0909\u0901\u092c\u093e\u091f \u091f\u093e\u0922\u093e \u0930\u0939\u0928\u0941\u0939\u094b\u0938\u094d\u0964 1077\u0964"),
    },
}

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "as": "Assamese", "bn": "Bengali",
    "ne": "Nepali", "mni": "Meiteilon", "kha": "Khasi", "lus": "Mizo",
}


def render(alert: Alert, audience: str, language: str) -> str:
    """Fall back to English rather than sending nothing. A warning in the wrong
    language still beats silence; an untranslated template is a bug to file, not a
    reason to drop the message."""
    bank = TEMPLATES.get(language) or {}
    tpl = bank.get(audience) or TEMPLATES["en"].get(audience) or TEMPLATES["en"]["AUTHORITY"]
    roads = ", ".join(alert.affected_roads[:2]) or "affected roads"
    return tpl.format(
        tier=alert.tier,
        severity=alert.severity,
        location=alert.location,
        district=alert.district,
        score=int(alert.risk_score),
        window=alert.expected_window_hours,
        action=alert.recommended_action.split(".")[0] + "." if alert.recommended_action else "",
        alert_id=alert.id,
        roads=roads,
    )


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
@dataclass
class SendResult:
    ok: bool
    error: str | None = None
    deferred: bool = False


class ConsoleProvider:
    name = "console"

    def send(self, msisdn: str, body: str) -> SendResult:
        log.info("SMS -> %s : %s", msisdn, body)
        return SendResult(ok=True)


class HttpProvider:
    """Generic HTTP SMS gateway. Point SMS_ENDPOINT at the state gateway or a
    commercial aggregator; the payload shape is the common denominator of both."""

    name = "http"

    def send(self, msisdn: str, body: str) -> SendResult:
        if not settings.sms_endpoint:
            return SendResult(ok=False, error="SMS_ENDPOINT not configured")
        try:
            r = httpx.post(
                settings.sms_endpoint,
                json={"to": msisdn, "message": body, "sender": "NERLEW"},
                headers={"Authorization": f"Bearer {settings.sms_api_key}"},
                timeout=10.0,
            )
            if r.status_code >= 400:
                return SendResult(ok=False, error=f"HTTP {r.status_code}: {r.text[:180]}")
            return SendResult(ok=True)
        except Exception as exc:  # noqa: BLE001 - provider errors must not crash a run
            return SendResult(ok=False, error=str(exc)[:180])


class StoreForwardProvider:
    """For sites behind a satellite or LoRa backhaul that is not always up.

    Marks the dispatch deferred instead of failed. The retry worker drains the queue
    when the link returns, and the ledger preserves ordering so a district does not
    receive a stand-down before the warning it stands down from.
    """

    name = "store_forward"

    def send(self, msisdn: str, body: str) -> SendResult:
        log.info("QUEUED (store-and-forward) -> %s : %s", msisdn, body)
        return SendResult(ok=True, deferred=True)


PROVIDERS = {
    "console": ConsoleProvider(),
    "http": HttpProvider(),
    "store_forward": StoreForwardProvider(),
}


def provider():
    return PROVIDERS.get(settings.sms_provider, PROVIDERS["console"])


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def queue_for_alert(db: Session, alert: Alert) -> list[Dispatch]:
    """Build the dispatch rows for an alert. Does not send — sending is a separate
    step so a database failure can never leave messages sent but unrecorded."""
    audiences = TIER_AUDIENCES.get(alert.tier, [])
    if not audiences:
        return []

    # A low-confidence alert never reaches the public unverified. The instruments we
    # would be asking people to trust are the ones we already know are unreliable.
    if alert.low_confidence and "PUBLIC" in audiences:
        audiences = [a for a in audiences if a != "PUBLIC"]

    recips = db.scalars(
        select(Recipient).where(
            Recipient.district_id == alert.district_id,
            Recipient.audience.in_(audiences),
            Recipient.active.is_(True),
        )
    ).all()

    rows: list[Dispatch] = []
    for r in recips:
        body = render(alert, r.audience, r.language)
        for channel in r.channels or ["SMS"]:
            rows.append(
                Dispatch(
                    alert_id=alert.id,
                    recipient_id=r.id,
                    channel=channel,
                    audience=r.audience,
                    msisdn=r.msisdn,
                    language=r.language,
                    body=body,
                    status="QUEUED",
                )
            )
    db.add_all(rows)
    return rows


def flush_queue(db: Session, limit: int = 200) -> dict[str, int]:
    """Attempt every queued/deferred dispatch. Called after a risk run and by the
    retry worker."""
    p = provider()
    pending = db.scalars(
        select(Dispatch)
        .where(Dispatch.status.in_(("QUEUED", "DEFERRED", "FAILED")))
        .limit(limit)
    ).all()

    counts = {"sent": 0, "deferred": 0, "failed": 0, "abandoned": 0}
    for d in pending:
        if d.attempts >= settings.sms_max_attempts:
            d.status = "ABANDONED"
            counts["abandoned"] += 1
            continue
        d.attempts += 1
        if d.channel == "SMS":
            res = p.send(d.msisdn, d.body)
        else:
            res = SendResult(ok=True)  # in-app push handled by the WS broadcast
        if res.deferred:
            d.status = "DEFERRED"
            counts["deferred"] += 1
        elif res.ok:
            d.status = "SENT"
            d.sent_at = utcnow()
            counts["sent"] += 1
        else:
            d.status = "FAILED"
            d.last_error = res.error
            counts["failed"] += 1
    return counts


def delivery_summary(db: Session, alert_id: str | None = None) -> dict:
    q = select(Dispatch)
    if alert_id:
        q = q.where(Dispatch.alert_id == alert_id)
    rows = db.scalars(q).all()
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_audience": {
            a: sum(1 for r in rows if r.audience == a) for a in {r.audience for r in rows}
        },
        "provider": settings.sms_provider,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
