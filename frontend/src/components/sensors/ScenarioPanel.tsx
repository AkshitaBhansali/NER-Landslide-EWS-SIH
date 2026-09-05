import { useState } from "react";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import { sensorService } from "@/services";
import { AsyncSection, Card } from "@/components/ui/primitives";
import type { Scenario } from "@/services/sensorService";

/**
 * Sensor scenarios.
 *
 * The point of this panel is to make the warning chain legible in under a minute:
 * a scenario perturbs the *inputs* to the simulated fleet and lets the risk engine
 * and the alert engine reach their own conclusions. It never writes an alert. If an
 * alert appears, the chain works; if it does not, the chain is broken and the
 * demonstration has told the truth about that.
 *
 * The numbers move for physical reasons, not randomly — rainfall raises soil
 * moisture, which raises pore pressure, which lowers the factor of safety, which
 * raises the risk score, in that order and with the right lags.
 */
export function ScenarioPanel({ onApplied }: { onApplied?: () => void }) {
  const app = useApp();
  const districts = districtsInScope(app.stateCode);
  const [busy, setBusy] = useState<string | null>(null);
  const [scope, setScope] = useState(app.districtId);

  const scenarios = useAsync(() => sensorService.getScenarios(), []);
  const state = useAsync(() => sensorService.getSimulationState(), [app.clockTick]);

  const apply = async (scenario: Scenario) => {
    setBusy(scenario.key);
    try {
      const res = await sensorService.applyScenario(scenario.key, scope);
      const cycle = (res.data.lastCycle ?? {}) as Record<string, number>;
      app.toast({
        tone: "success",
        title: `${scenario.label} applied`,
        body:
          cycle.alerts_created || cycle.alerts_escalated
            ? `${cycle.alerts_created ?? 0} new alert(s), ${cycle.alerts_escalated ?? 0} escalated across ${cycle.zones_scored ?? 0} zones.`
            : `${cycle.zones_scored ?? 0} zones rescored. No new alert crossed a dispatch threshold.`,
      });
      state.reload();
      scenarios.reload();
      onApplied?.();
    } catch (err) {
      app.toast({
        tone: "error",
        title: "Could not apply the scenario",
        body: err instanceof Error ? err.message : "The simulation service did not respond.",
      });
    } finally {
      setBusy(null);
    }
  };

  const step = async () => {
    setBusy("TICK");
    try {
      await sensorService.tickSimulation();
      state.reload();
      onApplied?.();
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("RESET");
    try {
      await sensorService.resetSimulation();
      app.toast({ tone: "info", title: "Fleet reset", body: "Back to baseline conditions." });
      state.reload();
      scenarios.reload();
      onApplied?.();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      title="Sensor scenarios"
      subtitle="Change the conditions the fleet is reporting and watch the chain respond"
      actions={
        <div className="row" style={{ gap: 6 }}>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="ALL">Whole region</option>
            {districts.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
          <button className="btn" type="button" onClick={step} disabled={busy !== null}>
            Advance
          </button>
          <button className="btn" type="button" onClick={reset} disabled={busy !== null}>
            Reset
          </button>
        </div>
      }
    >
      <AsyncSection state={scenarios} loadingLabel="Loading scenarios…" rows={2}>
        {(list) => (
          <>
            <div className="scenario-grid">
              {list.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  className={s.active ? "scenario active" : "scenario"}
                  onClick={() => apply(s)}
                  disabled={busy !== null}
                  title={s.expected}
                >
                  <div className="scenario-name">{s.label}</div>
                  <div className="scenario-summary">{s.summary}</div>
                  <ol className="scenario-chain">
                    {s.chain.map((step_, i) => (
                      <li key={i}>{step_}</li>
                    ))}
                  </ol>
                </button>
              ))}
            </div>

            {state.data && (
              <p className="tiny muted" style={{ marginTop: 10 }}>
                Active: <strong>{state.data.scenarioLabel}</strong> ·{" "}
                {state.data.scopeId === "ALL" ? "whole region" : state.data.scopeId} · tick{" "}
                {state.data.tick} · {state.data.minutesPerTick} simulated minutes per step
                {state.data.offlineSensors.length > 0 &&
                  ` · ${state.data.offlineSensors.length} sensor(s) silent`}
                . {state.data.expected}
              </p>
            )}
          </>
        )}
      </AsyncSection>
    </Card>
  );
}
