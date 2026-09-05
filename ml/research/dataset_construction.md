# Dataset Construction and Preprocessing

How the training data for the NER landslide early warning system is put
together: which fields come from which source, how the parts are merged into a
single record, what interim data stands in while manual exports are pending,
and what each cleaning and preprocessing decision is intended to protect
against.

Every figure quoted here is measured from the committed artefacts in `data/`,
regenerated from an empty directory with `random_state=42`.

## Contents

1. [Why assembly is a merge and not a download](#1-why-assembly-is-a-merge-and-not-a-download)
2. [Field-level provenance](#2-field-level-provenance)
3. [Assembly procedure for real data](#3-assembly-procedure-for-real-data)
4. [Constructing negative examples](#4-constructing-negative-examples)
5. [The interim placeholder dataset](#5-the-interim-placeholder-dataset)
6. [The physics scenario dataset](#6-the-physics-scenario-dataset)
7. [Cleaning the historical dataset](#7-cleaning-the-historical-dataset)
8. [Cleaning live sensor streams](#8-cleaning-live-sensor-streams)
9. [Feature construction](#9-feature-construction)
10. [Train and test protocol](#10-train-and-test-protocol)
11. [Known artefacts and caveats](#11-known-artefacts-and-caveats)
12. [Reproducing the datasets](#12-reproducing-the-datasets)

## 1. Why assembly is a merge and not a download

No single source contains a usable training row. A model row needs a location,
a date, terrain, rainfall over three windows, soil properties and an outcome
label. The available sources each hold a different slice:

| Source | Holds | Does not hold |
|---|---|---|
| NASA COOLR / Global Landslide Catalog | Event location, date, type, fatalities | Terrain, rainfall, soil, non-events |
| GSI Bhukosh | Lithology, susceptibility class, slope category, district inventories | Per-event dates, rainfall, continuous slope |
| Bhuvan (ISRO/NRSC) CartoDEM | Elevation, slope, aspect, land cover | Events, rainfall, soil properties |
| IMD gridded rainfall | Rainfall by date and grid cell | Events, terrain, soil |
| State DMA records and DesInventar | Impact and fatality counts | Terrain, rainfall, soil |

A single row is therefore assembled from four or five sources joined on
location and date. The canonical target of that merge is
`HISTORICAL_EVENT_SCHEMA` in `data_pipeline/schema.py`, and every loader in
`data_pipeline/historical_ingestion.py` writes into it. This is the reason the
schema is fixed first: the merge has no meaning without a single agreed
definition of each column.

## 2. Field-level provenance

The intended origin of each schema field once real exports are in place. The
column "Join key" states how a value reaches the row when it does not come
from the event record itself.

| Schema field | Primary source | Join key | Fallback |
|---|---|---|---|
| `event_id` | Source record, prefixed by source name | direct | Generated on ingest |
| `source` | Set by the loader | direct | n/a |
| `date` | NASA COOLR `event_date` | direct | State DMA record date |
| `state`, `district` | NASA COOLR `admin_division_name`, GSI `STATE` / `DISTRICT` | direct | Reverse geocode from coordinates |
| `latitude`, `longitude` | NASA COOLR, GSI Bhukosh (WGS84 in both) | direct | n/a, a row without coordinates is unusable |
| `elevation_m` | Bhuvan CartoDEM | point sample at coordinates | SRTM |
| `slope_deg` | Bhuvan CartoDEM, derived | point sample at coordinates | GSI `SLOPE_CAT`, categorical, band midpoint |
| `aspect_deg` | Bhuvan CartoDEM, derived | point sample at coordinates | Left null, optional field |
| `landcover` | Bhuvan thematic layer | point sample at coordinates | Left as `unknown` |
| `soil_type` | GSI Bhukosh `LITHOLOGY` | spatial join to lithology polygon | Left as `unknown` |
| `rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm` | IMD gridded rainfall | grid cell containing the point, windows ending on `date` | Station data from the nearest gauge |
| `antecedent_precip_index` | Derived, see section 9 | computed from the three rainfall windows | n/a |
| `soil_moisture_pct` | No historical source | n/a | Satellite proxy (SMAP, ESA CCI) or left null |
| `landslide_occurred` | 1 from any event inventory, 0 from constructed controls | direct | n/a |
| `landslide_type` | NASA COOLR `landslide_category` | direct | `unknown` |
| `fatalities` | NASA COOLR `fatality_count`, State DMA, DesInventar | direct | 0 |
| `data_confidence` | Set by the loader per source | direct | `low` |

Confidence is assigned by source rather than per row: `high` for GSI Bhukosh
(field-mapped government survey), `medium` for NASA COOLR (media-reported and
citizen-reported, not individually field-verified), `low` for anything
inferred or synthetic. The field exists so that a later training run can weight
or filter rows by provenance instead of treating a news-derived point and a
surveyed inventory point as equally reliable.

## 3. Assembly procedure for real data

The loaders implement steps 1 and 2. Steps 3 to 6 are the remaining
integration work.

1. **Export event points.** NASA COOLR through the Landslide Viewer
   application, GSI Bhukosh through a WebGIS area-of-interest export. Both are
   manual: neither exposes a bulk download API, which is the single largest
   reason real data is not yet in the repository.
2. **Normalise to the canonical schema.** `load_nasa_coolr(path)` and
   `load_gsi_bhukosh(path)` rename native columns, insert nulls for fields the
   source does not carry, and stamp `source` and `data_confidence`.
   `load_generic_csv(path, mapping, name)` covers any further source with a
   mapping dictionary, so adding a source needs a dictionary rather than a new
   code path.
3. **Filter to the region.** Retain rows inside the `NERRegionBounds` box,
   latitude 21.5 to 29.5 and longitude 88.0 to 97.5. The Global Landslide
   Catalog is worldwide, so this step removes most of it.
4. **Attach terrain.** Sample CartoDEM at each point for elevation, then
   derive slope and aspect from the DEM rather than reading a categorical
   susceptibility class, because the model needs a continuous angle.
5. **Attach rainfall.** For each row, take the IMD grid cell containing the
   point and sum rainfall over the 24 hour, 72 hour and 7 day windows ending
   on the event date. This is the step that converts a point in space into a
   point in space and time, and it is what makes rainfall-triggered prediction
   possible at all.
6. **Attach soil and land cover.** Spatial join to the GSI lithology polygons
   and the Bhuvan land-cover layer.

Deduplication runs last, on `source` plus `event_id`, because the same physical
event frequently appears in more than one inventory.

## 4. Constructing negative examples

Inventories record occurrences. Nothing records the absence of a landslide, so
a dataset built from inventories alone contains only positives and cannot train
a classifier.

Negatives therefore have to be constructed, and the construction determines
what the model actually learns. The intended approach is to sample control
points from terrain comparable to the event points, with the same rainfall
extraction applied at dates when no failure was reported. Two failure modes
matter here:

- Sampling controls from flat, dry terrain produces a model that separates
  hills from plains rather than a model that predicts failure. Accuracy looks
  excellent and the system is useless.
- Sampling controls only from slopes that never failed removes the marginal
  cases, which is precisely the region where an early warning decision is
  difficult.

The placeholder generator reflects the first constraint deliberately: negatives
are drawn with slope centred at 22 degrees rather than at zero, and with
non-zero rainfall, so that the two classes overlap instead of separating
trivially.

## 5. The interim placeholder dataset

`data/historical_events_placeholder.csv`, 3,600 rows, produced by
`generate_placeholder_ner_dataset()`. This is synthetic. Every row carries
`source='SYNTHETIC_NER'` and `data_confidence='low'`, so it cannot be confused
with observed history at any point downstream. It exists so the schema,
cleaning, feature construction and model code can be built and tested while the
manual exports are still pending.

The generative priors are chosen to match published regional characteristics
rather than invented:

| Prior | Value | Basis |
|---|---|---|
| Annual rainfall, Meghalaya | 4,000 to 11,000 mm | Mawsynram and Cherrapunji are among the wettest recorded locations |
| Annual rainfall, Manipur | 1,200 to 2,200 mm | Rain-shadow interior, the dry end of the region |
| Annual rainfall, other NER states | 1,500 to 4,500 mm | Regional averages |
| Elevation range | 20 to 5,000 m | Brahmaputra floodplain to the Kangchenjunga massif |
| Slope, positive rows | Normal(34, 7), clipped to 12 to 65 degrees | 25 to 45 degrees is the typical failure band for shallow soil slides |
| Slope, negative rows | Normal(22, 10), clipped to 2 to 65 degrees | Gentler or stable terrain, overlapping the positive band |
| Monsoon weighting | 72 percent of dates forced into June to September | Rainfall-triggered failures concentrate in the monsoon |
| Date range | 2015 to 2025 | Matches the usable span of the real catalogues |
| Rainfall multiplier, positives | 1.3 to 2.6 times the daily average | Failures follow anomalously wet spells, not average days |
| Rainfall multiplier, negatives | 0.4 to 1.1 times the daily average | Ordinary conditions |
| Class balance | 1,200 positive, 2,400 negative | Two controls per event, a common ratio in susceptibility modelling |

Measured properties of the generated file:

| Property | Positives (1,200) | Negatives (2,400) |
|---|---|---|
| Mean slope (deg) | 34.1 | 21.7 |
| Mean 24h rainfall (mm) | 49.6 | 19.1 |
| Mean soil moisture (percent) | 38.6 | 23.8 |
| Mean elevation (m) | 1,479.5 | 1,494.1 |

Elevation is deliberately near-identical across classes. Elevation on its own
does not cause failure, and leaving a spurious elevation gap in the data would
let the model exploit it.

Other measured properties: 82.2 percent of dates fall in June to September;
state-level mean 24 hour rainfall ranges from 70.8 mm in Meghalaya down to
16.3 mm in Manipur, preserving the intended regional gradient; land cover is 50
percent forest, 20 percent cropland, 16 percent grassland, 10 percent bare, 5
percent built-up; soil type is 38 percent residual soil, 31 percent colluvium,
21 percent weathered rock, 10 percent unknown; 81 rows carry a non-zero
fatality count.

Replacing this dataset requires one change: call `load_nasa_coolr()` or
`load_gsi_bhukosh()` where `generate_placeholder_ner_dataset()` is currently
called. The schema is identical, so no cleaning, feature or model code changes.

## 6. The physics scenario dataset

`data/synthetic_slope_scenarios.csv`, 40,000 rows, produced by
`LandslidePhysicsSimulator.generate()`. This is the dataset the model is
currently trained on, and it is generated rather than sourced.

The distinction from the placeholder dataset matters. The placeholder dataset
imitates the statistical appearance of real records. The physics dataset
derives its labels from a mechanical model: each row is a slope with sampled
geotechnical properties under a sampled rainfall history, and its label comes
from the computed Factor of Safety. A model trained on it learns the physical
relationship between slope, rainfall and failure rather than the sampling
choices of whoever generated the file.

Sampled parameter ranges, chosen for shallow colluvial and residual soils:

| Parameter | Distribution | Bounds |
|---|---|---|
| Slope angle | Uniform | 10 to 70 degrees |
| Depth to slip surface | Uniform | 0.5 to 4.0 m |
| Effective cohesion | Normal(8, 4) kPa | 0.5 to 40 kPa |
| Friction angle | Normal(30, 5) degrees | 15 to 42 degrees |
| Unit weight | Normal(18, 2) kN/m3 | 14 to 22 kN/m3 |
| Porosity | Normal(0.42, 0.08) | 0.25 to 0.60 |
| 24 hour rainfall | Gamma(shape 1.4, scale 25) mm | Heavy right tail, max 319.7 mm generated |
| 72 hour rainfall | 1.6 to 3.0 times the 24 hour value | Enforces window consistency |
| 7 day rainfall | 1.3 to 2.4 times the 72 hour value | Enforces window consistency |

Rainfall windows are generated as multiples of each other rather than
independently, because independent sampling would produce physically
impossible rows such as a 7 day total below the 24 hour total inside it.

Labelling is stochastic rather than a hard `FS < 1` cut:

```
failure_probability = 1 / (1 + exp((FS - 1.0) * 4.0))
label = 1 with that probability
```

The reason is that FS = 1 is a theoretical boundary computed from point
estimates of parameters that vary across a real hillslope. Slopes at FS = 1.05
do fail and slopes at FS = 0.95 sometimes hold. A hard cut teaches the model a
threshold that does not exist in the field; the logistic form preserves the
uncertainty band around the boundary. The measured consequence is that the
label agrees with a strict `FS < 1` rule on 81.8 percent of rows, with the
disagreement concentrated near FS = 1, which is the intended behaviour.

Measured properties: 40,000 rows, 35.74 percent positive; Factor of Safety
median 1.23, mean 1.56, range 0.16 to 8.0 (bounded, values above 8 are
uninformatively stable); 36.8 percent of rows have FS below 1. Event rate rises
monotonically with slope, from 1.0 percent in the 10 to 20 degree band to 60.2
percent in the 60 to 70 degree band, which is the physically expected
behaviour and a direct check that the simulator is not producing noise.

## 7. Cleaning the historical dataset

`HistoricalDataCleaner.run()`. Each step below lists the observed effect on the
committed placeholder dataset.

### Missing values: median fill for numerics, never drop rows

Numeric fields are filled with the column median; `data_confidence` falls back
to `low`. Rows are never dropped for missingness.

A historical landslide record is irreplaceable ground truth. A confirmed event
missing its soil type is still evidence that a slope failed at that location on
that date, and dropping it discards the rarest data in the set. The cost is a
slightly compressed variance in the filled column, which is acceptable; the
cost of dropping is a smaller and biased positive class, which is not. Median
rather than mean is used because the rainfall columns are heavily right-skewed
and a mean fill would import that skew into the imputed values.

### Duplicates: dropped on source plus event ID

Removes the same record ingested twice. It does not remove the same physical
event reported by two different sources, because those rows carry different
`event_id` values and different confidence levels. Cross-source deduplication
needs a spatial and temporal tolerance join and is deliberately not attempted
here. Observed effect: 0 rows removed from the placeholder dataset, which is
expected since it is generated with unique identifiers.

### Physical plausibility: flagged, not removed

Bounds checked: slope within 0 to 90 degrees, elevation within 0 to 6,000 m,
rainfall not negative. Violations set `quality_flag_implausible` rather than
deleting the row.

These bounds cannot be violated by a real landslide, so a violation indicates a
data-entry or geocoding error rather than an unusual event. The row is retained
and flagged, because the correct response is to investigate the source record,
and a deleted row cannot be investigated. Observed effect: 0 rows flagged.

### Rainfall outliers: capped at Q3 plus 3.0 IQR, not dropped

| Column | Q1 | Q3 | IQR | Upper cap | Rows above cap | Raw max | Max after cleaning |
|---|---|---|---|---|---|---|---|
| `rainfall_24h_mm` | 12.8 | 36.4 | 23.6 | 107.2 | 104 | 238.2 | 107.2 |
| `rainfall_72h_mm` | 31.5 | 90.8 | 59.3 | 268.8 | 99 | 690.2 | 268.8 |
| `rainfall_7d_mm` | 55.4 | 163.0 | 107.6 | 485.8 | 102 | 1,295.9 | 485.8 |

Two decisions are embedded here, and both are deliberate.

**Capping instead of dropping.** In most datasets an extreme value is suspect.
In this one it is the signal: the heaviest rainfall rows are exactly the rows
where landslides occur. Dropping them would remove the positive class. Capping
limits the leverage a single extreme value has on a fitted model while keeping
the row and its label.

**A 3.0 multiplier instead of the conventional 1.5.** The standard 1.5 IQR rule
assumes a roughly symmetric distribution. NER monsoon rainfall is legitimately
heavy-tailed, and a 1.5 multiplier would flag ordinary Meghalaya monsoon days
as errors. At 3.0, roughly 3 percent of rows are capped rather than the much
larger share a 1.5 rule would take. The multiplier is a judgement call and is
the parameter most worth revisiting against real IMD data, where the true tail
shape is known rather than assumed.

Note that capping is applied to the observed distribution of the input file. On
a real dataset with a different rainfall distribution, the caps will land at
different absolute values by design, since they are defined relative to the
data rather than as fixed thresholds.

## 8. Cleaning live sensor streams

`SensorStreamCleaner`, applied per sensor. Pooling sensors before cleaning
would blend real per-sensor anomalies into normal cross-sensor variance, which
defeats the purpose.

| Step | Method | Rationale |
|---|---|---|
| Gap detection | Flag intervals longer than 2.5 times the expected cadence | Tolerates transmission jitter while catching genuine outages. Gaps become an input to the sensor health score, not just a cleaning artefact |
| Resampling | Mean onto a regular grid at the expected interval | Downstream windowing and drift detection require even spacing. NaN is left where data is genuinely absent |
| Noise suppression | Centred rolling median, window 5 | A median removes single-sample spikes from electrical noise and transmission glitches while preserving a genuine step change, which a rolling mean would smear across the window. Preserving steps matters because a real tilt event is a step |
| Drift detection | Rolling window mean against the first window baseline, flagged at absolute z above 3.0 | Separates a miscalibrating sensor from genuinely changing ground. A soil moisture reading climbing for weeks with no rainfall is drift, and treating it as signal would generate a slow false alarm |
| Gap filling | Linear interpolation, limited to 3 consecutive periods, interior only | Short gaps are safe to bridge. Long gaps stay NaN so that the health score and the operator both see missing data rather than a confident straight line |

The ordering is deliberate: gaps are detected before resampling so that a gap is
recorded as a communication event rather than silently absorbed into the grid;
smoothing precedes drift detection so that drift is measured on the signal
rather than on noise; interpolation is last so that no fabricated value is ever
used to compute a drift statistic.

The demonstration stream in `_demo()` injects a known outage and a known 15
unit linear drift over 300 samples. The cleaner recovers both: 1 communication
failure, longest gap 1.33 hours, 74.3 percent of samples drift-flagged. This is
a functional test rather than an illustration.

## 9. Feature construction

**Antecedent precipitation index.** A weighted sum of the three rainfall
windows, representing how wet the ground already was before the most recent
rain:

```
API = 0.5 * rainfall_7d + 0.35 * rainfall_72h + 0.15 * rainfall_24h
```

Weighting the longer window most heavily reflects the physical mechanism:
soil that is already near saturation from a week of rain fails under a burst
that dry soil would absorb. A single 24 hour figure cannot express this, which
is why rainfall enters the model as three windows plus their weighted memory
rather than as one number.

The physics simulator uses the same construction with weights 0.5, 0.35 and
0.15, and the historical schema carries the field under the same definition.
This parity is a requirement rather than a convenience: without it, the model
trained on simulated data could not be applied to real records, because the
same column name would mean two different quantities.

**Saturation ratio.** In the simulator, API is converted into an effective
saturated fraction of the failure plane by comparing it against the soil's own
storage capacity, `porosity * depth * 1000` in millimetres of equivalent water,
clipped to the range 0 to 1. This is what couples rainfall to pore pressure and
therefore to the Factor of Safety.

**Feature set for training.** Five observable features only: `slope_deg`,
`rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm`,
`antecedent_precip_index`.

Excluded, and why:

| Excluded | Reason |
|---|---|
| `factor_of_safety`, `saturation_ratio`, `pore_pressure_kpa`, contribution columns | Internal state of the label generator. Including them leaks the target and yields near-perfect metrics that collapse on real data |
| `cohesion_kpa`, `friction_angle_deg`, `depth_to_slip_surface_m` | Obtained from a one-time geotechnical survey per site, not from a live sensor. A model depending on them cannot run on a new site without a survey |
| `soil_moisture_pct` | No historical source exists. The schema reserves the field for when the sensor network supplies it |

The exclusions are the reason the reported ROC-AUC is 0.786 rather than a
figure above 0.95. The higher number is available by simply including
`factor_of_safety`, and it would be meaningless.

## 10. Train and test protocol

- Split: 80 / 20, stratified on the label, `random_state=42`. Training 32,000
  rows, test 8,000 rows, class balance preserved at 35.74 percent positive in
  both.
- Random Forest: 300 trees, max depth 10, minimum 5 samples per leaf,
  `class_weight='balanced'`.
- XGBoost: 400 estimators, max depth 5, learning rate 0.05, subsample 0.8,
  column subsample 0.8.
- Selection: highest ROC-AUC on the held-out set.

Depth limits and the leaf minimum are set low relative to the dataset size to
constrain a model that would otherwise memorise 40,000 rows. `class_weight`
and the stratified split address the 36 / 64 class imbalance without resampling,
which would distort the rainfall distribution that the physics generated.

The split is random rather than temporal, which is appropriate here because the
scenarios are independent samples with no time ordering. Once real event data
is used, the split must become temporal, holding out later monsoon seasons, so
that the evaluation reflects forecasting rather than interpolation within a
period.

## 11. Known artefacts and caveats

1. **Rainfall influence in the physics dataset is weaker than intended.**
   Measured correlation with the label is 0.470 for slope against 0.051 to
   0.053 for the four rainfall features, and the trained model puts importance
   0.866 on `slope_deg`. The cause is the saturation calculation: storage
   capacity, `porosity * depth * 1000`, averages around 950 mm, while API
   averages 108 mm, so the median saturation ratio is only 0.095 and pore
   pressure rarely becomes large enough to dominate the Factor of Safety. Only
   0.9 percent of rows reach full saturation. The physics is implemented
   correctly, but the storage term treats the entire soil column as available
   capacity, whereas rainfall-triggered shallow failure is driven by a wetting
   front in the upper part of the profile. Modelling infiltration depth rather
   than full-column storage would raise the rainfall contribution and is the
   most valuable single improvement available to this dataset.
2. **The `landslide_type` column reports 2,400 missing values that are not
   missing.** The generator writes the literal string `n/a` for negative rows,
   and pandas parses that string as NaN on read. The cleaning report therefore
   shows 2,400 missing values where the data is intentionally not applicable.
   This is cosmetic and does not affect training, since the column is not a
   feature, but the sentinel should be changed to a non-reserved token such as
   `not_applicable` before the column is used for anything.
3. **The historical dataset is synthetic.** Nothing in `data/` is observed
   data. All reported metrics measure whether the pipeline recovers the
   relationship that was generated into the data, not field accuracy.
4. **Class balance is a design choice, not an observation.** Two controls per
   event in the placeholder dataset, and 35.74 percent positive in the physics
   dataset from the sampled parameter ranges. Real landslide occurrence over a
   region and a season is far rarer, so a model deployed on real data will face
   a much more extreme imbalance than anything it has been trained against.
5. **Rainfall caps are computed from the input distribution.** They shift with
   the data. On real IMD data the caps should be reviewed against the observed
   tail rather than inherited from the placeholder values.
6. **Drift detection uses the first window as the baseline.** A sensor already
   drifting when first installed will have that drift treated as normal. Field
   calibration on commissioning is assumed.

## 12. Reproducing the datasets

```bash
pip install -r requirements.txt

cd data_pipeline && python historical_ingestion.py   # data/historical_events_placeholder.csv
cd data_pipeline && python data_quality.py           # data/historical_events_cleaned.csv
cd simulation    && python physics_slope_model.py    # data/synthetic_slope_scenarios.csv
cd ml            && python train_risk_model.py       # data/risk_model.joblib and metrics
```

Every stage is seeded with `random_state=42`. Deleting `data/` and rerunning
the four commands reproduces all six artefacts byte for byte, verified by
checksum.

## Related documents

- `research/historical_data_sources.md`: the source survey, access methods and
  the native-to-canonical field mapping table.
- `research/existing_warning_workflows.md`: operational systems run by GSI,
  NDMA, IMD and ISRO, and the gaps this platform addresses.
- `README.md`: module reference, model results and repository overview.
