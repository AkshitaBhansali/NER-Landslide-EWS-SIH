# Existing Landslide Warning Workflows in India and the NER

Review of the warning workflows operated by GSI, NDMA, IMD, ISRO and the state
disaster management authorities, and of the coverage gaps this platform is
designed to address.

## 1. GSI National Landslide Forecasting Centre (NLFC)

- Inaugurated in July 2024 at the GSI Dharitri Campus in Kolkata, sited
  specifically to serve the North Eastern Region.
- Public outputs are the Bhusanket web portal and the Bhooskhalan mobile
  application, which deliver short-range bulletins covering 24 to 48 hours and
  medium-range bulletins covering up to 10 days.
- The methodology is the Regional Landslide Early Warning System (LEWS)
  approach from the multi-country LANDSLIP project: empirical
  intensity-duration rainfall thresholds, combined with weather forecast models
  supplied by IMD and NCMRWF, over a static susceptibility base map from the
  National Landslide Susceptibility Mapping programme at 1:50,000 scale.
- Coverage as of the 2025 monsoon is 21 districts across 8 states, including
  Kohima in Nagaland, which places an operational GSI system inside the target
  region.
- Dissemination is hub and spoke: GSI computes the forecast centrally,
  transmits it to the state government, the state passes it to the district
  administration, and the district informs the public. The chain is one-way,
  with no field or citizen reporting path back and no live sensor ingestion at
  district level.
- GSI has publicly stated that it is researching an AI-based forecasting model,
  which places the machine learning approach used here in line with the
  direction of the national agency rather than in competition with a solved
  problem.

**Coverage gap**: The NLFC is driven by rainfall thresholds and a
susceptibility map at district granularity, with a one-way dissemination chain.
It does not ingest live in-situ sensor networks such as piezometers,
tiltmeters and soil moisture probes, and it provides no citizen or field
incident reporting path. Those are the areas the alert engine and the field
reporting module of this platform address.

## 2. National Disaster Management Authority (NDMA)

- Sets national guidelines and coordinates response capacity. It does not run
  the landslide forecasting model itself, which is the GSI remit.
- Operates the Aapda Mitra scheme, which trains community volunteers for
  disaster response. This is a relevant integration point for the citizen
  reporting module and defines part of the audience for platform alerts.
- Funds mitigation through the National Landslide Risk Mitigation Programme.
- NDMA guidelines define the standard alert severity vocabulary, the
  red, orange and yellow colour coding used across hazard types in India. The
  platform alert states of Critical, High, Moderate and Information should be
  aligned to this convention so that authorities recognise them without
  learning a new scheme.

## 3. India Meteorological Department (IMD)

- Supplies the rainfall forecast and observation layer that both the GSI NLFC
  and this platform depend on: gridded rainfall products, station data and
  short-range quantitative precipitation forecasts.
- IMD is a named data-integration partner in the GSI LEWS architecture,
  alongside NCMRWF and ISRO/NRSC. This confirms that 24-hour, 72-hour and
  7-day rainfall together with an antecedent precipitation index, the fields
  already defined in `data_pipeline/schema.py`, are the correct feature family
  to standardise on, because the national system is built around the same
  inputs.

## 4. ISRO and Bhuvan (NRSC)

- Provides satellite-derived terrain (CartoDEM), land cover and susceptibility
  layers, which serve as the GSI NLFC base map. It is also a named
  data-integration partner for the national LEWS.
- Directly useful to the DEM and GIS layer of this platform as a
  cross-reference, and as a fallback when a high-resolution local DEM is not
  available for a given NER site.

## 5. State Disaster Management Authorities in the NER

- Sit at the end of the GSI dissemination chain. They receive the forecast
  bulletin and are responsible for district-level dissemination and response
  coordination.
- There is no unified live sensor or citizen reporting layer at this tier. This
  is the operational gap the platform is best positioned to fill, by giving
  state and district authorities a live dashboard fed by the project sensor
  network and by citizen reports, rather than a scheduled bulletin alone.

## Platform differentiation

| Existing systems (GSI NLFC, NDMA, IMD, Bhuvan) | This platform |
|---|---|
| District-level rainfall thresholds over a static susceptibility map | Site-level physics-informed Factor of Safety model with live sensor machine learning, updated continuously |
| One-way bulletin broadcast from GSI through state and district to the public | Two-way: live dashboard, configurable alert thresholds, citizen and field incident reporting |
| No live in-situ sensor ingestion (piezometer, tiltmeter, soil moisture) | Sensor network with health scoring, so every prediction carries a confidence signal |
| 21 districts across 8 states covered so far, expanding towards 2030 | Deployable per site immediately, complementing rather than replacing the national rollout |

## Sources

- PIB press release on the GSI NLFC inauguration, July 2024.
- GSI Bhusanket portal, https://bhusanket.gsi.gov.in/about.html.
- Down To Earth explainer on the GSI LEWS methodology, August 2024.
- Press coverage of the completed NLSM programme and the 2025 monsoon
  operational bulletin rollout across 21 districts and 8 states, including
  Kohima.
- Press coverage of the GSI announcement on AI-based forecasting research.
