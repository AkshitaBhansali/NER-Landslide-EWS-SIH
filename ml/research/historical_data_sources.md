# Historical Landslide Dataset Sources for the NER

Survey of the sources available for assembling a historical landslide dataset
for the North Eastern Region, with the access method and native field mapping
for each. The loaders implementing these mappings live in
`data_pipeline/historical_ingestion.py` (the `REAL_SOURCES` registry plus one
`load_*` function per source), and all of them normalise into the shared
`HISTORICAL_EVENT_SCHEMA` defined in `data_pipeline/schema.py`.

## 1. NASA COOLR / Global Landslide Catalog (GLC)

- **Content**: More than 11,000 rainfall-triggered landslide events worldwide
  from 2007 onwards in the GLC core, plus citizen-science reports from the
  COOLR Landslide Reporter extension. Global coverage, so it requires
  filtering to the NER bounding box.
- **Access**: Landslide Viewer, an ArcGIS web application, through the
  "Download Landslide Catalog" action, which exports CSV, shapefile or file
  geodatabase. There is no bulk download API; the export is manual and
  area-of-interest based, and requires accepting NASA terms and conditions.
- **Relevant native fields**: `event_date`, `event_time`, `latitude`,
  `longitude`, `landslide_category`, `fatality_count`, `admin_division_name`.
- **Confidence**: Medium. Events are media-sourced or citizen-sourced and are
  not field-verified individually.
- **Links**: https://catalog.data.gov/dataset/global-landslide-catalog-export
  (landing page), https://landslides.nasa.gov (programme home).

## 2. GSI Bhukosh

- **Content**: The Geological Survey of India open geoscience portal. It
  includes the National Landslide Susceptibility Mapping (NLSM) layers at
  1:50,000 scale covering approximately 4.3 lakh square kilometres across the
  Himalaya, the North Eastern Tertiary belt and the Western Ghats, along with
  district-level landslide inventories and lithology layers.
- **Access**: WebGIS with area-of-interest export as shapefile or GeoJSON.
- **Relevant native fields**: latitude and longitude, state, district,
  lithology (mapped to `soil_type`), susceptibility class, slope category.
- **Confidence**: High. This is the authoritative government source.
- **Link**: https://bhukosh.gsi.gov.in

## 3. GSI Bhusanket portal and the National Landslide Forecasting Centre

- **Content**: Live forecast bulletins and per-district historical event logs
  from the GSI National Landslide Forecasting Centre. Kohima in Nagaland has
  been an active district since the 2025 monsoon, which places an operational
  GSI system inside the target region.
- **Access**: Web portal and the Bhooskhalan mobile application. No public
  bulk API is documented, so a direct data-sharing request to GSI is the
  practical route.
- **Link**: https://bhusanket.gsi.gov.in

## 4. Bhuvan (ISRO / NRSC)

- **Content**: Satellite-derived terrain products (CartoDEM) and land-cover
  and susceptibility thematic layers. Primarily useful for cross-referencing
  DEM-derived slope and land cover against event locations rather than as a
  source of event points.
- **Access**: WMS and WFS thematic services.
- **Link**: https://bhuvan.nrsc.gov.in

## 5. IMD gridded rainfall

- **Content**: Daily and hourly gridded rainfall products and station data.
  This is the source for `rainfall_24h_mm`, `rainfall_72h_mm`,
  `rainfall_7d_mm` and `antecedent_precip_index` wherever an event record does
  not carry its own rainfall figure.
- **Access**: IMD Pune data portal. Some products require registration.
- **Link**: https://imdpune.gov.in

## 6. State Disaster Management Authorities and DesInventar

- **Content**: State-level disaster-loss records from the Assam, Sikkim and
  other NER state authorities, and the UN-supported DesInventar database.
  Useful for the `fatalities` field and other impact attributes that feed the
  reporting layer.
- **Link**: https://www.desinventar.net (select India, then the state)

## Variable mapping

Native source field to canonical schema field.

| Canonical field (`schema.py`) | NASA COOLR / GLC | GSI Bhukosh | Notes |
|---|---|---|---|
| `latitude`, `longitude` | `latitude`, `longitude` | `LAT`, `LONG` | WGS84 in both sources |
| `date` | `event_date` | Inventory layers are not always dated | GLC carries a per-event date; Bhukosh inventories are often a static snapshot |
| `state`, `district` | `admin_division_name` | `STATE`, `DISTRICT` | |
| `slope_deg` | Not provided, derive from DEM | `SLOPE_CAT`, categorical | A continuous value requires the DEM layer in most cases |
| `elevation_m` | Not provided, derive from DEM | Not provided, derive from DEM | Same DEM dependency |
| `soil_type` | Not provided | `LITHOLOGY` | GSI is the authoritative source for this field |
| `rainfall_24h_mm`, `rainfall_72h_mm`, `rainfall_7d_mm` | Not provided per event | Not provided | Joined from IMD gridded rainfall by date and location |
| `soil_moisture_pct` | Not provided | Not provided | No open historical source identified; see gap 1 below |
| `landslide_occurred` | Implicitly 1, only confirmed events are reported | Varies by layer | Confirmed non-events must be constructed separately; see gap 3 below |
| `fatalities` | `fatality_count` | Not provided | |

## Known gaps

1. **No source provides `soil_moisture_pct` historically.** The field can be
   populated going forward from the project sensor deployment, or approximated
   from satellite soil-moisture products such as ESA CCI or SMAP at a coarser
   resolution.
2. **No portal exposes a bulk API.** Assembling the dataset means filing a data
   request or performing an area-of-interest export by hand, once per source,
   and then running the export through the `load_*` functions. This requires
   calendar time rather than additional code.
3. **Confirmed non-events are structurally under-represented** in every
   inventory-style source, because a non-occurrence is not logged anywhere.
   This is a standard problem in landslide susceptibility modelling. The
   placeholder generator in `historical_ingestion.py` samples explicit
   negatives; a real dataset will need negatives constructed from non-failed
   slopes with comparable terrain and rainfall exposure, and the resulting
   class balance will differ from the placeholder dataset.
