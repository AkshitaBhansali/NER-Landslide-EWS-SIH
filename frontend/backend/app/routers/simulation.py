"""/api/simulation — the sensor scenario controls.

These exist so somebody can demonstrate, in under a minute, that the platform is a
pipeline and not a set of disconnected screens. Pressing "Heavy rainfall" does not
write an alert; it raises rainfall on the simulated gauges and lets the risk engine
and the alert engine reach their own conclusions. If the alert appears, the chain
works. If it does not, the chain is broken and the demonstration has told the truth
about that.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from ..core import telemetry
from ..deps import Session, get_case, get_db, require_role, respond

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("/scenarios")
def scenarios(response: Response, case: str | None = Depends(get_case)):
    return respond(telemetry.scenarios_payload(), case, response)


@router.get("/state")
def state(response: Response, db: Session = Depends(get_db),
          case: str | None = Depends(get_case)):
    return respond(telemetry.state_payload(db), case, response)


@router.post("/apply")
def apply(
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    scenario = payload.get("scenario") or payload.get("key")
    scope_id = payload.get("scope_id") or payload.get("district_id") or "ALL"
    try:
        return respond(telemetry.apply_scenario(db, scenario, scope_id), case, response)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tick")
def tick(
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    """Advance one step by hand — the same code path the background loop runs."""
    return respond(telemetry.tick(db), case, response)


@router.post("/reset")
def reset(
    response: Response,
    db: Session = Depends(get_db),
    case: str | None = Depends(get_case),
    _user: dict = Depends(require_role("DDMA")),
):
    return respond(telemetry.reset(db), case, response)
