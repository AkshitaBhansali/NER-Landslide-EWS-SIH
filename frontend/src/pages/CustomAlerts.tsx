import { useEffect, useMemo, useState } from "react";
import { useApp, districtsInScope } from "@/state/AppContext";
import { useAsync } from "@/state/useAsync";
import * as alertService from "@/services/alertService";
import type { Alert, RiskLevel } from "@/types";
import type { CustomRule, RuleCondition } from "@/services/alertService";
import { PageHeader } from "@/components/layout/PageHeader";
import { AsyncSection, Card, EmptyState, RiskBadge } from "@/components/ui/primitives";
import { titleCase } from "@/utils";

/**
 * Custom alert rules.
 *
 * A district office knows things the model does not — that the cutting at Mahur
 * fails at 90 mm rather than the 150 mm regional threshold, that the slope above a
 * particular school has moved twice this decade. This page turns that knowledge
 * into a rule the engine evaluates on every cycle.
 *
 * Three properties this interface depends on, all enforced server-side:
 *
 *  - **Rules are evaluated by the backend, not here.** A threshold living in React
 *    state stops existing when the tab closes, and never fires at 03:00 when the
 *    duty officer is asleep.
 *  - **The parameter vocabulary comes from the engine.** The builder never
 *    hard-codes a parameter list; adding one server-side makes it appear here.
 *  - **Severity defaults to the tier table.** With severity AUTO the score is mapped
 *    through the NDMA/GSI bands, so no custom rule can trigger a public broadcast on
 *    a score the methodology calls a Green day.
 */

interface Catalogue {
  parameters: {
    key: string; label: string; unit: string; kind: string;
    group: string; hint: string; choices: string[];
  }[];
  operators: { key: string; label: string }[];
  severities: string[];
  scopes: string[];
  match_modes: string[];
  tier_table: { from: number; to: number; tier: string; severity: string; status: string; audience: string }[];
}

const BLANK: Partial<CustomRule> = {
  name: "",
  description: "",
  scopeType: "ALL",
  scopeId: "ALL",
  conditions: [{ parameter: "risk_score", operator: "GTE", value: 70 }],
  match: "ALL",
  severity: "AUTO",
  alertClass: "AUTO",
  enabled: true,
  notify: true,
  cooldownMinutes: 45,
  createdBy: "Duty officer",
};

export function CustomAlerts() {
  const app = useApp();
  const districts = districtsInScope("ALL");
  const catalogue = useAsync(() => alertService.getRuleCatalogue(), []);
  const rules = useAsync(() => alertService.getCustomRules(), []);

  const [draft, setDraft] = useState<Partial<CustomRule>>(BLANK);
  const [editing, setEditing] = useState<string | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const cat = catalogue.data as unknown as Catalogue | null;
  const params = cat?.parameters ?? [];
  const paramByKey = useMemo(
    () => Object.fromEntries(params.map((p) => [p.key, p])),
    [params],
  );

  const ruleAlerts = useAsync(
    () =>
      selected
        ? alertService.getRuleAlerts(selected)
        : Promise.resolve({ data: [], fetchedAt: new Date().toISOString() }),
    [selected],
  );

  // A draft change invalidates the previous preview: showing a match count that
  // belongs to an older threshold is worse than showing none.
  useEffect(() => setPreview(null), [draft]);

  const setCondition = (i: number, patch: Partial<RuleCondition>) =>
    setDraft((d) => ({
      ...d,
      conditions: (d.conditions ?? []).map((c, j) => (j === i ? { ...c, ...patch } : c)),
    }));

  const addCondition = () =>
    setDraft((d) => ({
      ...d,
      conditions: [...(d.conditions ?? []), { parameter: "rainfall_24h_mm", operator: "GTE", value: 100 }],
    }));

  const removeCondition = (i: number) =>
    setDraft((d) => ({ ...d, conditions: (d.conditions ?? []).filter((_, j) => j !== i) }));

  const runPreview = async () => {
    setBusy(true);
    try {
      const res = await alertService.previewCustomRule(draft);
      setPreview(res.data as Record<string, unknown>);
    } catch (err) {
      app.toast({
        tone: "error",
        title: "Could not test the rule",
        body: err instanceof Error ? err.message : "The rule engine did not respond.",
      });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      if (editing) {
        await alertService.updateCustomRule(editing, draft);
        app.toast({ tone: "success", title: "Rule updated" });
      } else {
        await alertService.createCustomRule(draft);
        app.toast({ tone: "success", title: "Rule created", body: "It will be evaluated on the next cycle." });
      }
      setDraft(BLANK);
      setEditing(null);
      setPreview(null);
      rules.reload();
    } catch (err) {
      app.toast({
        tone: "error",
        title: "Could not save the rule",
        body: err instanceof Error ? err.message : "The rule engine rejected it.",
      });
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = async (rule: CustomRule) => {
    try {
      await alertService.updateCustomRule(rule.id, { ...rule, enabled: !rule.enabled });
      rules.reload();
    } catch (err) {
      app.toast({
        tone: "error",
        title: "Could not change the rule",
        body: err instanceof Error ? err.message : "",
      });
    }
  };

  const remove = async (rule: CustomRule) => {
    if (!window.confirm(`Delete "${rule.name}"? Alerts it already raised are kept.`)) return;
    try {
      await alertService.deleteCustomRule(rule.id);
      if (selected === rule.id) setSelected(null);
      rules.reload();
      app.toast({ tone: "success", title: "Rule deleted", body: "Alerts it raised were retained." });
    } catch (err) {
      app.toast({ tone: "error", title: "Could not delete the rule", body: err instanceof Error ? err.message : "" });
    }
  };

  const evaluateNow = async () => {
    setBusy(true);
    try {
      const res = await alertService.evaluateRulesNow();
      const d = res.data as Record<string, unknown>;
      app.toast({
        tone: "success",
        title: "Rules evaluated",
        body: `${d.custom_rules_fired ?? 0} of ${d.custom_rules_evaluated ?? 0} rule(s) matched · ${d.alerts_created ?? 0} new alert(s).`,
      });
      rules.reload();
      ruleAlerts.reload();
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (rule: CustomRule) => {
    setDraft({ ...rule });
    setEditing(rule.id);
    setPreview(null);
  };

  return (
    <>
      <PageHeader
        title="Custom alert rules"
        subtitle="Local thresholds the engine evaluates alongside the built-in rules"
      />

      <div className="stack">
        {/* builder */}
        <Card
          title={editing ? "Edit rule" : "New rule"}
          subtitle="Conditions are checked against live zone state on every risk cycle"
          actions={
            editing ? (
              <button className="btn" type="button" onClick={() => { setDraft(BLANK); setEditing(null); }}>
                Cancel edit
              </button>
            ) : undefined
          }
        >
          <div className="stack" style={{ gap: 12 }}>
            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              <label className="field" style={{ flex: "2 1 260px" }}>
                <span>Rule name</span>
                <input
                  value={draft.name ?? ""}
                  placeholder="e.g. Mahur cutting — local 90 mm threshold"
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                />
              </label>
              <label className="field">
                <span>Applies to</span>
                <select
                  value={draft.scopeType ?? "ALL"}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, scopeType: e.target.value, scopeId: "ALL" }))
                  }
                >
                  <option value="ALL">Whole region</option>
                  <option value="DISTRICT">One district</option>
                </select>
              </label>
              {draft.scopeType === "DISTRICT" && (
                <label className="field">
                  <span>District</span>
                  <select
                    value={draft.scopeId ?? "ALL"}
                    onChange={(e) => setDraft((d) => ({ ...d, scopeId: e.target.value }))}
                  >
                    <option value="ALL">Select…</option>
                    {districts.map((d) => (
                      <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            <label className="field">
              <span>Why this rule exists (optional)</span>
              <input
                value={draft.description ?? ""}
                placeholder="Local knowledge the model does not have"
                onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
              />
            </label>

            {/* conditions */}
            <div>
              <div className="row between" style={{ marginBottom: 6 }}>
                <p className="eyebrow" style={{ margin: 0 }}>Conditions</p>
                <label className="row" style={{ gap: 6, fontSize: 12 }}>
                  <span className="muted">Match</span>
                  <select
                    value={draft.match ?? "ALL"}
                    onChange={(e) => setDraft((d) => ({ ...d, match: e.target.value }))}
                  >
                    <option value="ALL">All conditions</option>
                    <option value="ANY">Any condition</option>
                  </select>
                </label>
              </div>

              {(draft.conditions ?? []).map((c, i) => {
                const p = paramByKey[c.parameter];
                return (
                  <div className="row" key={i} style={{ gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                    <select
                      value={c.parameter}
                      onChange={(e) => setCondition(i, { parameter: e.target.value })}
                      style={{ flex: "2 1 200px" }}
                    >
                      <optgroup label="Hazard">
                        {params.filter((x) => x.group === "HAZARD").map((x) => (
                          <option key={x.key} value={x.key}>{x.label}</option>
                        ))}
                      </optgroup>
                      <optgroup label="Data quality">
                        {params.filter((x) => x.group === "OPERATIONAL").map((x) => (
                          <option key={x.key} value={x.key}>{x.label}</option>
                        ))}
                      </optgroup>
                    </select>
                    <select
                      value={c.operator}
                      onChange={(e) => setCondition(i, { operator: e.target.value })}
                    >
                      {(cat?.operators ?? []).map((o) => (
                        <option key={o.key} value={o.key}>{o.label}</option>
                      ))}
                    </select>
                    {p?.kind === "LEVEL" || p?.kind === "TEXT" ? (
                      <select
                        value={String(c.value)}
                        onChange={(e) => setCondition(i, { value: e.target.value })}
                      >
                        {(p.choices ?? []).map((ch) => (
                          <option key={ch} value={ch}>{ch}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="number"
                        value={String(c.value)}
                        style={{ width: 110 }}
                        onChange={(e) => setCondition(i, { value: Number(e.target.value) })}
                      />
                    )}
                    {c.operator === "BETWEEN" && (
                      <input
                        type="number"
                        value={String(c.value2 ?? "")}
                        style={{ width: 110 }}
                        placeholder="upper"
                        onChange={(e) => setCondition(i, { value2: Number(e.target.value) })}
                      />
                    )}
                    <span className="tiny muted" style={{ flex: "1 1 160px" }}>
                      {p?.unit} {p?.hint ? `· ${p.hint}` : ""}
                    </span>
                    {(draft.conditions ?? []).length > 1 && (
                      <button className="btn ghost" type="button" onClick={() => removeCondition(i)}>
                        Remove
                      </button>
                    )}
                  </div>
                );
              })}
              <button className="btn" type="button" onClick={addCondition}>
                Add condition
              </button>
            </div>

            <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
              <label className="field">
                <span>Severity</span>
                <select
                  value={draft.severity ?? "AUTO"}
                  onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value }))}
                >
                  <option value="AUTO">From the tier table (recommended)</option>
                  {["INFORMATION", "MODERATE", "HIGH", "CRITICAL"].map((s) => (
                    <option key={s} value={s}>{titleCase(s)}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Cooldown</span>
                <input
                  type="number"
                  min={0}
                  value={draft.cooldownMinutes ?? 45}
                  onChange={(e) => setDraft((d) => ({ ...d, cooldownMinutes: Number(e.target.value) }))}
                />
              </label>
              <label className="row" style={{ gap: 6, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={draft.notify ?? true}
                  onChange={(e) => setDraft((d) => ({ ...d, notify: e.target.checked }))}
                />
                <span className="tiny">Send messages (uncheck for dashboard-only)</span>
              </label>
              <label className="row" style={{ gap: 6, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={draft.enabled ?? true}
                  onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
                />
                <span className="tiny">Enabled</span>
              </label>
            </div>

            <div className="row" style={{ gap: 8 }}>
              <button className="btn" type="button" onClick={runPreview} disabled={busy}>
                Test against current conditions
              </button>
              <button className="btn primary" type="button" onClick={save} disabled={busy}>
                {editing ? "Save changes" : "Create rule"}
              </button>
            </div>

            {preview && (
              <div className="callout">
                <strong>
                  {String(preview.zones_matched)} of {String(preview.zones_in_scope)} zones match right now.
                </strong>{" "}
                This would raise a <span className="mono">{String(preview.alert_class)}</span> alert.
                {Array.isArray(preview.matches) && preview.matches.length > 0 && (
                  <ul className="clean-list" style={{ marginTop: 8 }}>
                    {(preview.matches as Record<string, unknown>[]).slice(0, 5).map((m) => (
                      <li key={String(m.zone_id)}>
                        <span>
                          {String(m.zone)}
                          <span className="tiny muted"> · {String(m.district)}</span>
                          <div className="tiny muted">{(m.evidence as string[])?.join("; ")}</div>
                        </span>
                        <span className="tiny mono">
                          {String(m.severity)} · {String(m.tier)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="tiny muted" style={{ marginTop: 6 }}>{String(preview.note ?? "")}</p>
              </div>
            )}
          </div>
        </Card>

        {/* active rules */}
        <Card
          title="Active rules"
          subtitle="Evaluated on every risk cycle alongside the seven built-in rules"
          actions={
            <button className="btn" type="button" onClick={evaluateNow} disabled={busy}>
              Evaluate now
            </button>
          }
        >
          <AsyncSection state={rules} loadingLabel="Loading rules…" rows={3}>
            {(list: CustomRule[]) =>
              list.length === 0 ? (
                <EmptyState
                  title="No custom rules yet"
                  hint="Create one above. Custom rules complement the built-in rules; they never replace them."
                />
              ) : (
                <div className="table-wrap">
                  <table className="data" style={{ minWidth: 760 }}>
                    <thead>
                      <tr>
                        <th scope="col">Rule</th>
                        <th scope="col">Scope</th>
                        <th scope="col">Conditions</th>
                        <th scope="col">Class</th>
                        <th scope="col">Fired</th>
                        <th scope="col">State</th>
                        <th scope="col" />
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((rule) => (
                        <tr
                          key={rule.id}
                          className={selected === rule.id ? "row-selected" : undefined}
                          onClick={() => setSelected(rule.id)}
                          style={{ cursor: "pointer" }}
                        >
                          <td>
                            <strong>{rule.name}</strong>
                            <div className="tiny muted">{rule.description}</div>
                          </td>
                          <td className="tiny">
                            {rule.scopeType === "ALL"
                              ? "Whole region"
                              : districts.find((d) => d.id === rule.scopeId)?.name ?? rule.scopeId}
                          </td>
                          <td className="tiny mono">
                            {rule.conditions
                              .map((c) => `${paramByKey[c.parameter]?.label ?? c.parameter} ${c.operator} ${c.value}`)
                              .join(rule.match === "ANY" ? " OR " : " AND ")}
                          </td>
                          <td className="tiny">
                            {rule.alertClass === "OPERATIONAL" ? "Operational" : "Hazard"}
                            {!rule.notify && <div className="tiny muted">dashboard only</div>}
                          </td>
                          <td className="mono">{rule.triggerCount}</td>
                          <td>
                            <button
                              className="btn ghost"
                              type="button"
                              onClick={(e) => { e.stopPropagation(); toggleEnabled(rule); }}
                            >
                              {rule.enabled ? "Enabled" : "Disabled"}
                            </button>
                          </td>
                          <td>
                            <div className="row" style={{ gap: 4 }}>
                              <button
                                className="btn ghost"
                                type="button"
                                onClick={(e) => { e.stopPropagation(); startEdit(rule); }}
                              >
                                Edit
                              </button>
                              <button
                                className="btn ghost"
                                type="button"
                                onClick={(e) => { e.stopPropagation(); remove(rule); }}
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </AsyncSection>
        </Card>

        {/* alerts from the selected rule */}
        <Card
          title="Alerts from this rule"
          subtitle={
            selected
              ? "Alerts it raised, plus open alerts it matched on the same slope"
              : "Select a rule above"
          }
        >
          {!selected ? (
            <EmptyState
              title="No rule selected"
              hint="Select a rule to see the alerts it has produced."
            />
          ) : (
            <AsyncSection state={ruleAlerts} loadingLabel="Loading alerts…" rows={2}>
              {(list: Alert[]) =>
                list.length === 0 ? (
                  <EmptyState
                    title="This rule has not fired yet"
                    hint="It is being evaluated on every cycle. Use 'Evaluate now' to test it against current conditions."
                  />
                ) : (
                  <ul className="clean-list">
                    {list.map((a) => (
                      <li key={a.id}>
                        <span>
                          <strong>{a.location}</strong>
                          <span className="tiny muted"> · {a.district}</span>
                          <div className="tiny muted">{a.triggerDetail}</div>
                        </span>
                        <span className="row" style={{ gap: 6 }}>
                          <RiskBadge level={a.severity as RiskLevel} />
                          <span className="tiny mono muted">
                            {a.customRuleId === selected ? "raised" : "matched"}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )
              }
            </AsyncSection>
          )}
        </Card>

        {/* tier reference */}
        {cat?.tier_table && (
          <Card
            title="Alert tiers"
            subtitle="How a score becomes a message, and who receives it"
          >
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Score</th>
                    <th scope="col">Tier</th>
                    <th scope="col">Status</th>
                    <th scope="col">Recipients</th>
                  </tr>
                </thead>
                <tbody>
                  {cat.tier_table.map((t) => (
                    <tr key={t.tier}>
                      <td className="mono">{t.from}–{t.to}</td>
                      <td>{titleCase(t.tier)}</td>
                      <td className="tiny">{t.status}</td>
                      <td className="tiny muted">{t.audience}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="tiny muted" style={{ marginTop: 8 }}>
              A rule set to automatic severity uses this table, so it cannot send a
              public broadcast on a score the methodology treats as a Green day.
            </p>
          </Card>
        )}
      </div>
    </>
  );
}
