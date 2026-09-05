# NER Landslide Early Warning System

Data pipeline, physics-informed slope simulation and machine learning modules
for a rainfall-triggered landslide early warning system targeting the North
Eastern Region (NER) of India.

The repository covers two halves of the platform. The offline half handles
dataset assembly and validation, sensor stream quality control, sensor health
scoring, synthetic scenario generation from slope-stability physics, and risk
classification. The online half serves the resulting model as a real-time
sensor streaming API over REST, Server-Sent Events and WebSocket. The output
contract (`risk_score`, `risk_level`, `probability`, `contributing_factors`) is
identical on both paths, and is consumed by the backend prediction service and
the operator dashboard.

## Contents

1. [Architecture](#architecture)
2. [Repository layout](#repository-layout)
3. [Installation](#installation)
4. [Running the pipeline](#running-the-pipeline)
5. [Real-time sensor API](#real-time-sensor-api)
6. [Module reference](#module-reference)
7. [Generated artefacts](#generated-artefacts)
8. [Model results](#model-results)
9. [Data sources](#data-sources)
10. [Limitations](#limitations)
11. [Planned work](#planned-work)

## Architecture

The modules run in a fixed order. Each stage consumes the output of the
previous one, and the same order applies both to local reproduction and to
production execution.

```
Offline pipeline

schema.py                 canonical field definitions (contract for all modules)
        |
historical_ingestion.py   source registry, loaders, placeholder NER dataset
        |
data_quality.py           historical cleaning and sensor stream cleaning
        |
sensor_health.py          per-sensor 0-100 health score and status
        |
physics_slope_model.py    infinite-slope FoS simulation, labelled scenarios
        |
train_risk_model.py       Random Forest and XGBoost risk classification
        |
        v
   risk_model.joblib
        |
Online service

api/simulator.py          live sensor fleet, physically coupled readings
        |
api/runtime.py            single tick task: advance, publish, assess, score
        |                 (calls api/risk_engine.py and api/health_monitor.py)
api/stream_bus.py         per-subscriber queues, filtering, backpressure
        |
api/service.py            REST, Server-Sent Events, WebSocket
```

`schema.py` defines the field contract shared by every module, so a real data
export can replace the placeholder dataset without changes downstream, and a
real sensor gateway can replace the simulator without changes upstream of it.
The streaming service calls `risk_output_schema()` from
`ml/train_risk_model.py` directly, so the live and offline paths cannot drift
apart.

## Repository layout

```
NER_Landslide_EWS/
├── data_pipeline/
│   ├── schema.py                 HISTORICAL_EVENT_SCHEMA and SENSOR_READING_SCHEMA
│   ├── historical_ingestion.py   source registry, loaders, placeholder dataset generator
│   ├── data_quality.py           HistoricalDataCleaner and SensorStreamCleaner
│   └── sensor_health.py          SensorHealthScorer and fleet scoring
├── simulation/
│   └── physics_slope_model.py    infinite-slope stability model with pore pressure
├── ml/
│   └── train_risk_model.py       model training, evaluation and risk output contract
├── api/
│   ├── service.py                REST, Server-Sent Events and WebSocket endpoints
│   ├── runtime.py                background tick task driving the live stream
│   ├── simulator.py              live sensor fleet with physically coupled readings
│   ├── stream_bus.py             subscriber fan-out, filtering and backpressure
│   ├── risk_engine.py            live zone risk from the trained model and physics
│   ├── health_monitor.py         live sensor health scoring
│   ├── smoke_test.py             end to end verification of every endpoint
│   └── README.md                 endpoint reference and client examples
├── research/
│   ├── dataset_construction.md        provenance, assembly and preprocessing rationale
│   ├── historical_data_sources.md     source survey and variable mapping
│   └── existing_warning_workflows.md  operational systems in India and coverage gaps
├── data/                         generated datasets, trained model, metrics
└── requirements.txt
```

## Installation

Python 3.10 or later is required.

```bash
pip install -r requirements.txt
```

Dependencies for the offline pipeline: `numpy`, `pandas`, `scikit-learn`,
`xgboost`, `joblib`. The streaming API additionally requires `fastapi`,
`uvicorn`, `websockets` and `httpx`.

## Running the pipeline

Each script is runnable on its own and writes to `data/`. Paths are relative,
so run each script from its own directory.

```bash
cd data_pipeline && python historical_ingestion.py   # writes data/historical_events_placeholder.csv
cd data_pipeline && python data_quality.py           # cleans the dataset, demonstrates stream cleaning
cd data_pipeline && python sensor_health.py          # demonstrates fleet health scoring
cd simulation    && python physics_slope_model.py    # writes data/synthetic_slope_scenarios.csv
cd ml            && python train_risk_model.py       # writes data/risk_model.joblib and metrics
```

All generators use a fixed seed (`random_state=42`), so a rerun reproduces the
committed outputs exactly.

## Real-time sensor API

```bash
python -m api
```

The service starts on `http://127.0.0.1:8000` and streams live telemetry from a
simulated fleet of 42 sensors across six instrumented corridors in the region.

| Address | Purpose |
|---|---|
| `/docs` | Interactive OpenAPI documentation |
| `/dashboard` | Built-in stream viewer |
| `/api/v1/stream` | Server-Sent Events feed |
| `/api/v1/ws` | WebSocket feed |
| `/api/v1/snapshot` | Complete point-in-time state for a page load |

```bash
curl -N http://127.0.0.1:8000/api/v1/stream
```

Readings conform exactly to `SENSOR_READING_SCHEMA`, and the service also
publishes derived state: a 0 to 100 health score per sensor and a risk record
per zone carrying the platform output contract. Six event types are published:
`sensor_reading`, `zone_risk`, `zone_alert`, `sensor_health`, `sensor_fault`
and `tick`. Streams can be filtered by event type, zone, sensor and sensor
type.

Readings are physically coupled rather than random. Each zone carries a live
rainfall process, saturation state and Factor of Safety, and each sensor reads
off that state, so a rainfall burst propagates through soil moisture, then pore
pressure, then deformation, then risk score, in the correct order and with the
correct lags. Instrument faults, battery discharge and signal attenuation are
injected at low probability so that the quality-control and sensor-health path
is genuinely exercised.

By default the simulated clock runs 150 times faster than real time, delivering
a five-minute sensor cadence every two seconds, which makes a multi-day
rainfall event observable in minutes. Setting `NER_EWS_TICK_INTERVAL_S=300`
returns the service to real time.

Verify the whole surface end to end:

```bash
python -m api.smoke_test
```

`api/README.md` holds the endpoint reference, the event catalogue, client
examples for the browser and Python, the full configuration table, the
backpressure policy and the path for replacing the simulator with real
hardware.

## Module reference

### `data_pipeline/schema.py`

Defines two canonical schemas.

| Schema | Purpose | Key fields |
|---|---|---|
| `HISTORICAL_EVENT_SCHEMA` | One row per landslide event or control point | `latitude`, `longitude`, `state`, `date`, `slope_deg`, `elevation_m`, `rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm`, `antecedent_precip_index`, `soil_moisture_pct`, `landslide_occurred`, `data_confidence` |
| `SENSOR_READING_SCHEMA` | One row per sensor reading for live ingestion | `sensor_id`, `zone_id`, `sensor_type`, `timestamp`, `value`, `unit`, `battery_pct`, `rssi_dbm`, `expected_interval_s` |

`NERRegionBounds` holds the geographic bounding box and the eight NER states
used by the placeholder generator and by any regional filtering step.

### `data_pipeline/historical_ingestion.py`

| Component | Description |
|---|---|
| `REAL_SOURCES` | Registry of the four production data sources with URL, access method and confidence level |
| `load_generic_csv(path, column_mapping, source_name)` | Normalises an arbitrary CSV export into `HISTORICAL_EVENT_SCHEMA` |
| `load_nasa_coolr(path)` | Loader for a NASA COOLR / Global Landslide Catalog export |
| `load_gsi_bhukosh(path)` | Loader for a GSI Bhukosh WebGIS export |
| `generate_placeholder_ner_dataset(...)` | Generates a synthetic NER-scoped dataset with per-state rainfall and elevation priors |

The placeholder dataset is tagged `source='SYNTHETIC_NER'` and
`data_confidence='low'` in every row, so it cannot be mistaken for observed
data. Replacing it with a real export requires only a change of loader call,
because all loaders emit the same schema.

### `data_pipeline/data_quality.py`

| Class | Handles |
|---|---|
| `HistoricalDataCleaner` | Missing values, duplicates, implausible coordinates and values, rainfall outlier capping, timestamp normalisation |
| `SensorStreamCleaner` | Gap and communication-failure detection, resampling to a regular interval, rolling-median noise suppression, drift detection, bounded interpolation of short gaps |

Rainfall outliers are capped rather than dropped, because extreme rainfall is
the signal of interest rather than an error. Drift detection runs per sensor
stream, because drift characteristics are specific to a sensor and a site.

### `data_pipeline/sensor_health.py`

`SensorHealthScorer` produces a 0-100 score from five weighted sub-scores.

| Sub-score | Weight | Measures |
|---|---|---|
| Completeness | 0.25 | Fraction of expected readings received |
| Validity | 0.25 | Fraction of readings within physically plausible bounds |
| Stability | 0.20 | Inverse of drift severity |
| Noise | 0.15 | Signal noise against the sensor type's expected specification |
| Comms | 0.15 | Uptime, battery level and signal strength |

The score maps to a status of `Healthy`, `Degraded` or `Failed`, and the result
carries specific maintenance notes, such as a recalibration recommendation when
drift is detected. `score_fleet()` applies the scorer across all sensors and
returns a summary table. Every risk prediction can therefore be published with
a confidence signal describing the state of the sensors that produced it.

### `simulation/physics_slope_model.py`

An infinite-slope stability model, the standard formulation for the shallow
rainfall-triggered translational slides that dominate the NER. The Factor of
Safety is

```
FS = [c + (gamma * z * cos^2(beta) - u) * tan(phi)] / [gamma * z * sin(beta) * cos(beta)]
```

where `c` is effective cohesion, `phi` the effective friction angle, `gamma`
the soil unit weight, `z` the depth to the slip surface, `beta` the slope angle
and `u` the rainfall-driven pore-water pressure. Pore pressure is derived from
a saturation ratio built from antecedent rainfall memory against soil storage
capacity.

`LandslidePhysicsSimulator.generate()` samples 40,000 scenarios across slope
angles of 10 to 70 degrees and realistic geotechnical ranges for colluvial
soils, then labels them with a logistic function centred on FS = 1 rather than
a hard cutoff, which reflects the parameter uncertainty present in a real
slope. Each scenario also reports the cohesion, friction and pore-pressure
contributions to stability, which give physically interpretable contributing
factors alongside model feature importance.

### `ml/train_risk_model.py`

Trains and compares a Random Forest and an XGBoost classifier on five
observable features:

```
slope_deg, rainfall_24h_mm, rainfall_72h_mm, rainfall_7d_mm, antecedent_precip_index
```

Physics internals (`factor_of_safety`, `saturation_ratio`, `pore_pressure_kpa`
and the contribution columns) are excluded as inputs, because they are the
label generator's own state and using them would leak the target. Cohesion,
friction angle and depth to slip surface are also excluded, because a deployed
system obtains them from a one-time geotechnical survey rather than a live
sensor feed. The feature set matches `HISTORICAL_EVENT_SCHEMA`, so the trained
model can be pointed at real historical and live sensor data without feature
re-engineering.

`risk_output_schema(model, feat_imp, row)` returns the platform output
contract:

```json
{
  "risk_score": 60.4,
  "risk_level": "High",
  "probability": 0.6043,
  "contributing_factors": {
    "slope_deg": 0.651,
    "rainfall_7d_mm": 0.134,
    "antecedent_precip_index": 0.101,
    "rainfall_72h_mm": 0.084,
    "rainfall_24h_mm": 0.03
  }
}
```

## Generated artefacts

| File | Rows | Description |
|---|---|---|
| `data/historical_events_placeholder.csv` | 3,600 | Placeholder NER historical dataset, 33.3 percent positive |
| `data/historical_events_cleaned.csv` | 3,600 | The same dataset after `HistoricalDataCleaner` |
| `data/synthetic_slope_scenarios.csv` | 40,000 | Physics-labelled scenarios, 35.7 percent positive |
| `data/risk_model.joblib` | n/a | Best model by ROC-AUC, persisted with joblib |
| `data/model_metrics.json` | n/a | Full metrics for both candidate models |
| `data/feature_importance.csv` | 5 | Normalised feature importance of the selected model |

## Model results

Held-out test set of 8,000 scenarios (20 percent stratified split,
`random_state=42`).

| Model | ROC-AUC | Accuracy | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Random Forest | 0.786 | 0.697 | 0.549 | 0.850 | 0.667 |
| XGBoost | 0.780 | 0.709 | 0.582 | 0.658 | 0.617 |

Random Forest is selected on ROC-AUC. Its recall of 0.850 is the operationally
relevant property for an early warning system, where a missed event costs far
more than a false alarm. XGBoost is more precise but misses roughly a third of
events, which is the wrong trade-off for this application.

Feature importance is dominated by `slope_deg` (0.866), with the four rainfall
features contributing 0.032 to 0.036 each. This follows from the physics: slope
angle enters the Factor of Safety in both the driving and the resisting term,
while rainfall acts only through pore pressure.

## Data sources

Four production sources are documented with access method and field mapping in
`research/historical_data_sources.md`.

| Source | Content | Confidence |
|---|---|---|
| NASA COOLR / Global Landslide Catalog | Global rainfall-triggered event catalogue, 2007 onwards | Medium |
| GSI Bhukosh | National Landslide Susceptibility Mapping layers and district inventories | High |
| GSI Bhusanket / NLFC | Operational forecast bulletins and district event logs | High |
| Bhuvan (ISRO/NRSC) | CartoDEM terrain and land-cover thematic layers | High |

Rainfall features are joined from IMD gridded products.

`research/dataset_construction.md` documents field-level provenance, the
assembly procedure that merges these sources into a single record, how the
interim and physics datasets are generated, and the rationale behind every
cleaning and preprocessing decision.

`research/existing_warning_workflows.md` reviews the operational systems run by
GSI, NDMA, IMD and ISRO, and identifies the coverage gaps this platform
addresses.

## Limitations

1. The historical dataset in `data/` is synthetic. Real NASA COOLR and GSI
   Bhukosh exports must be produced manually through their web applications,
   because neither exposes a bulk download API. The loaders and field mappings
   are already written, so integrating a real export is a single function call.
2. Reported metrics are measured against physics-simulated scenarios, not
   observed events. They confirm that the pipeline recovers the physical
   relationship and provide a baseline, but they are not a field-validated
   accuracy figure.
3. The model is point-in-time and uses no temporal sequence model. Sequence
   models such as LSTM or GRU require multi-step rainfall time series that the
   current dataset does not contain.
4. `soil_moisture_pct` has no open historical source for the region. The schema
   reserves the field, and it can be populated only once the sensor network is
   deployed or a coarser satellite product such as SMAP or ESA CCI is
   integrated.
5. Confirmed non-events are structurally under-represented in every
   inventory-style source, because non-occurrences are not logged. The
   placeholder generator samples explicit negatives, but a real dataset will
   need negatives constructed from comparable non-failed slopes.

## Planned work

- Ingest real NASA COOLR and GSI Bhukosh exports through the existing loaders
  and retrain against observed events.
- Add a false-positive and false-negative breakdown by state, slope band and
  rainfall band, using the confusion matrices already produced by the training
  script.
- Replace the sensor fleet simulator with a gateway ingestion path once the
  sensor hardware specification is fixed. The streaming service is built
  against `SENSOR_READING_SCHEMA`, so the change is confined to one module.
- Add a time-series store behind the streaming service, so history requests can
  reach past the in-memory buffer window and state survives a restart.
- Add authentication and rate limiting in front of the streaming service.
- Evaluate temporal models against multi-step rainfall series once time-series
  data is available.
- Integrate satellite soil moisture as a proxy feature for `soil_moisture_pct`.
