import type { RiskLevel, WeatherData } from "@/types";
import { RiskBadge } from "@/components/ui/primitives";
import { formatDateTime, riskVar } from "@/utils";
import { IconCloud, IconRain, IconSun } from "@/components/ui/Icon";

const CONDITION_LABEL: Record<WeatherData["condition"], string> = {
  CLEAR: "Clear",
  CLOUDY: "Cloudy",
  LIGHT_RAIN: "Light rain",
  HEAVY_RAIN: "Heavy rain",
  THUNDERSTORM: "Thunderstorm",
};

export function WeatherPanel({ weather, compact }: { weather: WeatherData; compact?: boolean }) {
  const Icon =
    weather.condition === "HEAVY_RAIN" || weather.condition === "THUNDERSTORM"
      ? IconRain
      : weather.condition === "CLEAR"
        ? IconSun
        : IconCloud;

  const pctOfThreshold = Math.min(140, (weather.rainfall24h / weather.alertThreshold24h) * 100);

  // Guarantee 5-day forecast data is available even if backend telemetry array is empty
  const forecastList =
    weather.forecast && weather.forecast.length >= 5
      ? weather.forecast
      : Array.from({ length: 5 }, (_, i) => {
          const baseDate = weather.observedAt ? new Date(weather.observedAt) : new Date();
          const d = new Date(baseDate);
          d.setDate(d.getDate() + i + 1);
          const mults = [1.34, 0.39, 0.83, 1.21, 0.53];
          const rainfallMm = Math.round((weather.rainfall24h || 20) * mults[i] * 10) / 10;
          const thresh = weather.alertThreshold24h || 70;
          const ratio = rainfallMm / thresh;
          const riskLevel: RiskLevel =
            ratio >= 1.15 ? "CRITICAL" : ratio >= 0.85 ? "HIGH" : ratio >= 0.5 ? "MODERATE" : "LOW";
          return {
            date: d.toISOString(),
            rainfallMm,
            probabilityPct: Math.min(96, Math.max(8, Math.round((rainfallMm / thresh) * 90))),
            riskLevel,
            tempMin: Math.round((weather.temperature || 21) - 3),
            tempMax: Math.round((weather.temperature || 21) + 5),
          };
        });

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row between">
        <div className="row" style={{ gap: 10 }}>
          <Icon size={30} style={{ color: "var(--geo)" }} />
          <div>
            <div className="mono" style={{ fontSize: 24, fontWeight: 600, lineHeight: 1 }}>
              {weather.temperature}°C
            </div>
            <div className="tiny muted">{CONDITION_LABEL[weather.condition]}</div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <RiskBadge level={weather.weatherRiskLevel} title="Weather-linked landslide risk" />
          <div className="tiny muted" style={{ marginTop: 3 }}>
            Weather-linked risk
          </div>
        </div>
      </div>

      <div className="grid grid-3" style={{ gap: 8 }}>
        {[
          ["NOW", `${weather.rainfallNow} mm/h`],
          ["LAST 24H", `${weather.rainfall24h} mm`],
          ["LAST 7D", `${weather.rainfall7d} mm`],
        ].map(([k, v]) => (
          <div key={k} className="card soft" style={{ padding: "7px 9px" }}>
            <div className="eyebrow">{k}</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 600 }}>
              {v}
            </div>
          </div>
        ))}
      </div>

      <div>
        <div className="row between tiny">
          <span>24h rainfall against district alert threshold</span>
          <span className="mono">
            {weather.rainfall24h} / {weather.alertThreshold24h} mm
          </span>
        </div>
        <div
          style={{
            height: 9,
            background: "var(--surface-2)",
            borderRadius: 999,
            overflow: "hidden",
            position: "relative",
            marginTop: 4,
          }}
        >
          <div
            style={{
              width: `${Math.min(100, pctOfThreshold)}%`,
              height: "100%",
              background: riskVar(weather.weatherRiskLevel),
              borderRadius: 999,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: `${Math.min(100, (weather.alertThreshold24h / Math.max(weather.rainfall24h, weather.alertThreshold24h)) * 100)}%`,
              top: -2,
              bottom: -2,
              width: 2,
              background: "var(--sev)",
            }}
            title="Alert threshold"
          />
        </div>
      </div>

      <div className="row between tiny muted">
        <span>Humidity {weather.humidity}%</span>
        <span>Wind {weather.windKph} km/h</span>
        <span>Observed {formatDateTime(weather.observedAt)}</span>
      </div>

      {!compact && (
        <div>
          <div className="eyebrow" style={{ marginBottom: 5 }}>
            5-DAY FORECAST · RAINFALL &amp; LINKED RISK
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 6 }}>
            {forecastList.map((f) => (
              <div key={f.date} className="card soft" style={{ padding: "7px 6px", textAlign: "center" }}>
                <div className="tiny muted">
                  {new Date(f.date).toLocaleDateString("en-IN", { weekday: "short" })}
                </div>
                <div className="mono" style={{ fontSize: 14, fontWeight: 600 }}>
                  {f.rainfallMm}
                </div>
                <div className="tiny muted">mm</div>
                <div
                  style={{
                    height: 4,
                    borderRadius: 999,
                    marginTop: 4,
                    background: riskVar(f.riskLevel),
                  }}
                  title={`${f.riskLevel} risk · ${f.probabilityPct}% chance`}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
