"""
Web Visualizer Builder (Enhanced V1.1)
======================================
Generates a standalone, production-grade 2D/3D Digital Twin Early Warning Dashboard (dist/index.html)
with robust event handling, 3D raycasting, 2D raster heatmap overlays, smooth camera transitions,
and zero-error button controls.
"""

import json
import os

def build_standalone_dashboard(payload_path="data/export/dashboard_payload.json", output_html="dist/index.html"):
    with open(payload_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_str = json.dumps(data)

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NER Landslide Early Warning — 2D/3D Digital Twin GIS Platform</title>
  
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  
  <!-- Leaflet 2D Map CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  
  <!-- Three.js 3D WebGL Library & OrbitControls -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>

  <!-- Lucide Icons -->
  <script src="https://unpkg.com/lucide@latest"></script>

  <style>
    :root {{
      --bg-base: #070a13;
      --bg-panel: rgba(13, 20, 36, 0.88);
      --bg-panel-hover: rgba(22, 34, 58, 0.95);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-active: rgba(56, 189, 248, 0.45);
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --accent-cyan: #06b6d4;
      --accent-blue: #3b82f6;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-orange: #f97316;
      --accent-rose: #f43f5e;
      --glow-red: 0 0 24px rgba(244, 63, 94, 0.45);
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-heading: 'Outfit', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}

    * {{
      margin: 0;
      padding: 0;
      box-sizing: border-box;
      user-select: none;
    }}

    body {{
      font-family: var(--font-sans);
      background-color: var(--bg-base);
      color: var(--text-primary);
      overflow: hidden;
      height: 100vh;
      width: 100vw;
      display: flex;
      flex-direction: column;
    }}

    /* Glassmorphism scrollbars */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.15); border-radius: 4px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: rgba(255,255,255,0.25); }}

    /* Top Navigation Header */
    header {{
      height: 64px;
      background: linear-gradient(180deg, rgba(13, 20, 36, 0.98) 0%, rgba(10, 14, 23, 0.92) 100%);
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      z-index: 1000;
      backdrop-filter: blur(16px);
    }}

    .brand-section {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}

    .logo-badge {{
      width: 40px;
      height: 40px;
      background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 50%, #6366f1 100%);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 14px rgba(14, 165, 233, 0.4);
    }}

    .brand-titles h1 {{
      font-family: var(--font-heading);
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: linear-gradient(90deg, #ffffff 0%, #93c5fd 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .brand-titles .subtitle {{
      font-size: 0.75rem;
      color: var(--text-secondary);
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 8px;
      border-radius: 9999px;
      font-size: 0.7rem;
      font-weight: 600;
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }}

    .status-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 8px #10b981;
      animation: pulse-dot 2s infinite;
    }}

    @keyframes pulse-dot {{
      0%, 100% {{ opacity: 1; transform: scale(1); }}
      50% {{ opacity: 0.4; transform: scale(0.8); }}
    }}

    .header-metrics {{
      display: flex;
      align-items: center;
      gap: 20px;
    }}

    .metric-chip {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
    }}

    .metric-chip .label {{
      font-size: 0.65rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .metric-chip .value {{
      font-family: var(--font-mono);
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-primary);
    }}

    .alert-banner-badge {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      border-radius: 8px;
      font-family: var(--font-heading);
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      transition: all 0.3s ease;
    }}

    .alert-red {{
      background: rgba(244, 63, 94, 0.2);
      color: #fda4af;
      border: 1px solid rgba(244, 63, 94, 0.4);
      box-shadow: var(--glow-red);
    }}

    .alert-orange {{
      background: rgba(249, 115, 22, 0.2);
      color: #fdba74;
      border: 1px solid rgba(249, 115, 22, 0.4);
    }}

    .alert-yellow {{
      background: rgba(245, 158, 11, 0.2);
      color: #fde68a;
      border: 1px solid rgba(245, 158, 11, 0.4);
    }}

    /* Main Container Layout */
    .app-body {{
      display: flex;
      flex: 1;
      height: calc(100vh - 64px - 68px);
      position: relative;
      overflow: hidden;
    }}

    /* Left Control Sidebar */
    .sidebar-left {{
      width: 310px;
      background: var(--bg-panel);
      backdrop-filter: blur(20px);
      border-right: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      z-index: 500;
      overflow-y: auto;
    }}

    .panel-section {{
      padding: 16px;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .section-title {{
      font-family: var(--font-heading);
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    /* Layer Toggle Item */
    .layer-toggle-group {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .layer-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 9px 12px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s ease;
    }}

    .layer-item:hover {{
      background: var(--bg-panel-hover);
      border-color: var(--border-active);
    }}

    .layer-item.active {{
      background: rgba(14, 165, 233, 0.14);
      border-color: rgba(14, 165, 233, 0.45);
      box-shadow: inset 0 0 12px rgba(14, 165, 233, 0.1);
    }}

    .layer-info {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .layer-icon {{
      width: 28px;
      height: 28px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.85rem;
    }}

    .layer-name {{
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--text-primary);
    }}

    .layer-count {{
      font-family: var(--font-mono);
      font-size: 0.7rem;
      color: var(--text-muted);
    }}

    .toggle-checkbox {{
      appearance: none;
      -webkit-appearance: none;
      width: 18px;
      height: 18px;
      border: 1.5px solid var(--text-muted);
      border-radius: 4px;
      outline: none;
      cursor: pointer;
      position: relative;
      transition: all 0.2s;
      background: rgba(255, 255, 255, 0.05);
    }}

    .toggle-checkbox:checked {{
      background: var(--accent-cyan);
      border-color: var(--accent-cyan);
    }}

    .toggle-checkbox:checked::after {{
      content: '✓';
      position: absolute;
      color: #000;
      font-size: 12px;
      font-weight: 800;
      top: -1px;
      left: 3px;
    }}

    /* Heatmap Color Legend */
    .legend-bar {{
      height: 10px;
      border-radius: 5px;
      background: linear-gradient(90deg, #3b82f6 0%, #10b981 30%, #f59e0b 60%, #ef4444 100%);
      margin: 10px 0 6px 0;
    }}

    .legend-labels {{
      display: flex;
      justify-content: space-between;
      font-size: 0.65rem;
      color: var(--text-secondary);
      font-family: var(--font-mono);
    }}

    /* Central Viewport */
    .viewport-container {{
      flex: 1;
      position: relative;
      height: 100%;
      background: #000;
    }}

    .view-canvas {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
    }}

    #map2d {{
      z-index: 10;
      background: #0b111e;
    }}

    #canvas3d {{
      z-index: 20;
      width: 100%;
      height: 100%;
      cursor: grab;
    }}

    #canvas3d:active {{
      cursor: grabbing;
    }}

    /* Floating View Mode Switcher */
    .view-mode-bar {{
      position: absolute;
      top: 16px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 600;
      background: rgba(15, 23, 42, 0.9);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-active);
      border-radius: 12px;
      padding: 4px;
      display: flex;
      gap: 4px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
    }}

    .mode-btn {{
      padding: 8px 18px;
      border: none;
      border-radius: 8px;
      font-family: var(--font-heading);
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--text-secondary);
      background: transparent;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s ease;
    }}

    .mode-btn:hover {{
      color: #ffffff;
      background: rgba(255, 255, 255, 0.05);
    }}

    .mode-btn:active {{
      transform: scale(0.96);
    }}

    .mode-btn.active {{
      background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
      color: #ffffff;
      box-shadow: 0 2px 12px rgba(37, 99, 235, 0.45);
    }}

    /* 3D Camera Preset Overlay */
    .camera-presets {{
      position: absolute;
      top: 76px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 600;
      display: flex;
      gap: 8px;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 4px 8px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }}

    .preset-btn {{
      padding: 5px 12px;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      font-size: 0.72rem;
      font-weight: 500;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }}

    .preset-btn:hover {{
      background: rgba(255, 255, 255, 0.12);
      color: var(--text-primary);
    }}

    .preset-btn:active {{
      transform: scale(0.95);
      background: rgba(14, 165, 233, 0.2);
    }}

    /* Right Prioritization Panel */
    .sidebar-right {{
      width: 380px;
      background: var(--bg-panel);
      backdrop-filter: blur(20px);
      border-left: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      z-index: 500;
      overflow-y: auto;
    }}

    .priority-stat-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 14px;
    }}

    .stat-card {{
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      padding: 10px;
    }}

    .stat-card .stat-label {{
      font-size: 0.65rem;
      color: var(--text-muted);
      text-transform: uppercase;
    }}

    .stat-card .stat-val {{
      font-family: var(--font-mono);
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text-primary);
      margin-top: 2px;
    }}

    .asset-list {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}

    .asset-card {{
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      padding: 12px;
      transition: all 0.2s ease;
      cursor: pointer;
      position: relative;
    }}

    .asset-card:hover {{
      border-color: var(--border-active);
      background: var(--bg-panel-hover);
      transform: translateY(-2px);
      box-shadow: 0 6px 18px rgba(0,0,0,0.3);
    }}

    .asset-card:active {{
      transform: scale(0.98);
    }}

    .asset-card.critical {{
      border-left: 4px solid var(--accent-rose);
    }}

    .asset-card.warning {{
      border-left: 4px solid var(--accent-amber);
    }}

    .asset-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }}

    .asset-title {{
      font-family: var(--font-heading);
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--text-primary);
    }}

    .priority-badge {{
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 6px;
      background: rgba(244, 63, 94, 0.2);
      color: #fda4af;
      border: 1px solid rgba(244, 63, 94, 0.4);
    }}

    .asset-desc {{
      font-size: 0.72rem;
      color: var(--text-secondary);
      line-height: 1.35;
      margin-bottom: 8px;
    }}

    .action-box {{
      background: rgba(0, 0, 0, 0.3);
      border-radius: 6px;
      padding: 6px 8px;
      font-size: 0.7rem;
      color: #38bdf8;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    /* Bottom Simulation Controller */
    footer {{
      height: 68px;
      background: linear-gradient(0deg, rgba(13, 20, 36, 0.98) 0%, rgba(10, 14, 23, 0.92) 100%);
      border-top: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      padding: 0 24px;
      gap: 24px;
      z-index: 1000;
      backdrop-filter: blur(16px);
    }}

    .play-controls {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .ctrl-btn {{
      width: 40px;
      height: 40px;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
      background: rgba(255, 255, 255, 0.05);
      color: var(--text-primary);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .ctrl-btn:hover {{
      background: rgba(255, 255, 255, 0.15);
      border-color: var(--accent-cyan);
    }}

    .ctrl-btn:active {{
      transform: scale(0.92);
    }}

    .play-main {{
      background: linear-gradient(135deg, #0284c7 0%, #2563eb 100%);
      border: none;
      box-shadow: 0 2px 12px rgba(37, 99, 235, 0.45);
    }}

    .play-main:hover {{
      background: linear-gradient(135deg, #0369a1 0%, #1d4ed8 100%);
    }}

    .timeline-container {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}

    .timeline-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.75rem;
    }}

    .time-current {{
      font-family: var(--font-heading);
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--accent-cyan);
    }}

    .time-rainfall {{
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: var(--text-secondary);
    }}

    .timeline-slider {{
      -webkit-appearance: none;
      width: 100%;
      height: 6px;
      border-radius: 3px;
      background: rgba(255, 255, 255, 0.12);
      outline: none;
      cursor: pointer;
    }}

    .timeline-slider::-webkit-slider-thumb {{
      -webkit-appearance: none;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--accent-cyan);
      box-shadow: 0 0 12px var(--accent-cyan);
      cursor: pointer;
      transition: transform 0.1s;
    }}

    .timeline-slider::-webkit-slider-thumb:hover {{
      transform: scale(1.2);
    }}

    /* Interactive Popup / Tooltip Modal */
    .inspector-modal {{
      position: absolute;
      bottom: 24px;
      left: 334px;
      width: 330px;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(24px);
      border: 1px solid var(--border-active);
      border-radius: 12px;
      padding: 18px;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.7);
      z-index: 700;
      display: none;
      animation: fadeIn 0.2s ease;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .modal-close {{
      position: absolute;
      top: 10px;
      right: 12px;
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 1.2rem;
      padding: 4px;
    }}

    .modal-close:hover {{
      color: #ffffff;
    }}

    /* Responsive adjustments */
    @media (max-width: 1100px) {{
      .sidebar-right {{ display: none; }}
    }}
  </style>
</head>
<body>

  <!-- Top Header -->
  <header>
    <div class="brand-section">
      <div class="logo-badge">
        <i data-lucide="mountain-snow" style="color: #fff; width: 22px; height: 22px;"></i>
      </div>
      <div class="brand-titles">
        <h1>NER LANDSLIDE EARLY WARNING PLATFORM</h1>
        <div class="subtitle">
          <span>GIS + 3D Terrain Digital Twin</span>
          <span>&bull;</span>
          <span class="status-pill"><span class="status-dot"></span> NH-29 Kohima Corridor Live Twin</span>
        </div>
      </div>
    </div>

    <div class="header-metrics">
      <div class="metric-chip">
        <span class="label">Elevation Span</span>
        <span class="value" id="hdr-elevation">720m - 2312m</span>
      </div>
      <div class="metric-chip">
        <span class="label">Total Threat Pop</span>
        <span class="value" id="hdr-pop" style="color: #fda4af;">7,510 Res</span>
      </div>
      <div class="metric-chip">
        <span class="label">Critical Road Cut</span>
        <span class="value" id="hdr-road" style="color: #fdba74;">3.4 km</span>
      </div>
      <div class="alert-banner-badge alert-red" id="hdr-alert">
        <i data-lucide="alert-triangle" style="width: 18px; height: 18px;"></i>
        <span id="hdr-alert-text">RED (Severe Emergency)</span>
      </div>
    </div>
  </header>

  <!-- App Body Layout -->
  <div class="app-body">
    
    <!-- Left Layer Controls -->
    <aside class="sidebar-left">
      
      <div class="panel-section">
        <div class="section-title">
          <span>Terrain Derivatives (DEM)</span>
          <i data-lucide="layers" style="width: 14px; height: 14px;"></i>
        </div>
        <div class="layer-toggle-group" id="raster-layer-group">
          
          <div class="layer-item active" onclick="selectRaster('elevation')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(14, 165, 233, 0.2); color: #38bdf8;">🏔️</div>
              <div>
                <div class="layer-name">DEM Elevation Grid</div>
                <div class="layer-count">10m Resolution (10,000 Cells)</div>
              </div>
            </div>
            <input type="radio" name="raster-layer" value="elevation" checked class="toggle-checkbox" onclick="event.stopPropagation(); selectRaster('elevation')">
          </div>

          <div class="layer-item" onclick="selectRaster('slope')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(249, 115, 22, 0.2); color: #fb923c;">📐</div>
              <div>
                <div class="layer-name">Slope Angle (Horn's)</div>
                <div class="layer-count">Range: 0° - 85° (Mean: 61.7°)</div>
              </div>
            </div>
            <input type="radio" name="raster-layer" value="slope" class="toggle-checkbox" onclick="event.stopPropagation(); selectRaster('slope')">
          </div>

          <div class="layer-item" onclick="selectRaster('twi')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">💧</div>
              <div>
                <div class="layer-name">Topographic Wetness (TWI)</div>
                <div class="layer-count">Hollows & Moisture Sinks</div>
              </div>
            </div>
            <input type="radio" name="raster-layer" value="twi" class="toggle-checkbox" onclick="event.stopPropagation(); selectRaster('twi')">
          </div>

          <div class="layer-item" onclick="selectRaster('tri')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(168, 85, 247, 0.2); color: #c084fc;">⛰️</div>
              <div>
                <div class="layer-name">Terrain Ruggedness (TRI)</div>
                <div class="layer-count">Riley Heterogeneity Index</div>
              </div>
            </div>
            <input type="radio" name="raster-layer" value="tri" class="toggle-checkbox" onclick="event.stopPropagation(); selectRaster('tri')">
          </div>

        </div>
      </div>

      <div class="panel-section">
        <div class="section-title">
          <span>Infrastructure Vectors</span>
          <i data-lucide="map-pin" style="width: 14px; height: 14px;"></i>
        </div>
        <div class="layer-toggle-group">
          
          <div class="layer-item active" id="item-roads" onclick="toggleVector('roads')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">🛣️</div>
              <div>
                <div class="layer-name">NH-29 National Lifeline</div>
                <div class="layer-count">15 Segmented Sectors</div>
              </div>
            </div>
            <input type="checkbox" checked class="toggle-checkbox" id="chk-roads" onclick="event.stopPropagation(); toggleVector('roads', this.checked)">
          </div>

          <div class="layer-item active" id="item-settlements" onclick="toggleVector('settlements')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(245, 158, 11, 0.2); color: #fbbf24;">🏘️</div>
              <div>
                <div class="layer-name">Human Settlements</div>
                <div class="layer-count">5 Villages (11,360 Pop)</div>
              </div>
            </div>
            <input type="checkbox" checked class="toggle-checkbox" id="chk-settlements" onclick="event.stopPropagation(); toggleVector('settlements', this.checked)">
          </div>

          <div class="layer-item active" id="item-rivers" onclick="toggleVector('rivers')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">🌊</div>
              <div>
                <div class="layer-name">Dzüdza River & Torrents</div>
                <div class="layer-count">Canyon Channel & Scour Zones</div>
              </div>
            </div>
            <input type="checkbox" checked class="toggle-checkbox" id="chk-rivers" onclick="event.stopPropagation(); toggleVector('rivers', this.checked)">
          </div>

          <div class="layer-item active" id="item-critical_assets" onclick="toggleVector('critical_assets')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(168, 85, 247, 0.2); color: #e879f9;">⚡</div>
              <div>
                <div class="layer-name">Critical Infrastructure</div>
                <div class="layer-count">Bridges, 132kV Towers, CHC</div>
              </div>
            </div>
            <input type="checkbox" checked class="toggle-checkbox" id="chk-critical_assets" onclick="event.stopPropagation(); toggleVector('critical_assets', this.checked)">
          </div>

          <div class="layer-item active" id="item-sensors" onclick="toggleVector('sensors')">
            <div class="layer-info">
              <div class="layer-icon" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">📡</div>
              <div>
                <div class="layer-name">IoT Sensor Network</div>
                <div class="layer-count">10 Piezometer/Inclinometers</div>
              </div>
            </div>
            <input type="checkbox" checked class="toggle-checkbox" id="chk-sensors" onclick="event.stopPropagation(); toggleVector('sensors', this.checked)">
          </div>

        </div>
      </div>

      <div class="panel-section">
        <div class="section-title">
          <span>Spatial Risk Scale</span>
          <span style="font-family: var(--font-mono); font-size: 0.65rem; color: var(--accent-cyan);">P(Failure)</span>
        </div>
        <div class="legend-bar"></div>
        <div class="legend-labels">
          <span>Low (&lt;35%)</span>
          <span>Moderate</span>
          <span>High</span>
          <span>Severe (&gt;80%)</span>
        </div>
      </div>

    </aside>

    <!-- Center Interactive Viewport -->
    <main class="viewport-container">
      
      <!-- View Mode Selector Bar -->
      <div class="view-mode-bar">
        <button class="mode-btn active" id="btn-mode-3d" onclick="setViewMode('3d')">
          <i data-lucide="box" style="width: 16px; height: 16px;"></i>
          <span>3D Terrain Digital Twin</span>
        </button>
        <button class="mode-btn" id="btn-mode-2d" onclick="setViewMode('2d')">
          <i data-lucide="map" style="width: 16px; height: 16px;"></i>
          <span>2D GIS Multi-Layer Map</span>
        </button>
      </div>

      <!-- 3D Camera Controls Preset Overlay -->
      <div class="camera-presets" id="camera-presets-bar">
        <button class="preset-btn" onclick="setCameraPreset('perspective')">Perspective View</button>
        <button class="preset-btn" onclick="setCameraPreset('gorge')">Dzüdza Gorge Flank</button>
        <button class="preset-btn" onclick="setCameraPreset('topdown')">Top-Down Bird's Eye</button>
        <button class="preset-btn" onclick="setCameraPreset('highway')">NH-29 Road Alignment</button>
      </div>

      <!-- 2D Leaflet Container -->
      <div id="map2d" class="view-canvas" style="display: none;"></div>

      <!-- 3D WebGL Canvas Container -->
      <div id="canvas3d" class="view-canvas"></div>

      <!-- Click Inspection Modal -->
      <div class="inspector-modal" id="inspector-modal">
        <button class="modal-close" onclick="closeInspector()">&times;</button>
        <div id="inspector-content"></div>
      </div>

    </main>

    <!-- Right Prioritization & Action Dispatch Sidebar -->
    <aside class="sidebar-right">
      
      <div class="panel-section">
        <div class="section-title">
          <span>Exposure Summary (R &times; I)</span>
          <i data-lucide="shield-alert" style="width: 14px; height: 14px;"></i>
        </div>
        
        <div class="priority-stat-grid">
          <div class="stat-card">
            <div class="stat-label">Exposed Highway</div>
            <div class="stat-val" id="stat-road-km">3.4 km</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Threatened Pop</div>
            <div class="stat-val" id="stat-pop">7,510</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Critical Assets</div>
            <div class="stat-val" id="stat-assets">4 Units</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Max Risk Factor</div>
            <div class="stat-val" id="stat-max-risk" style="color: #f87171;">80.2%</div>
          </div>
        </div>
      </div>

      <div class="panel-section" style="flex: 1; display: flex; flex-direction: column;">
        <div class="section-title">
          <span>Ranked Action Priorities</span>
          <button style="background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.4); color: var(--accent-cyan); font-size: 0.7rem; font-weight: 600; border-radius: 6px; padding: 4px 10px; cursor: pointer; transition: all 0.2s;" onclick="exportPriorityReport()" onmouseover="this.style.background='rgba(14, 165, 233, 0.3)'" onmouseout="this.style.background='rgba(14, 165, 233, 0.15)'">Export JSON</button>
        </div>
        
        <div class="asset-list" id="ranked-asset-container">
          <!-- Dynamically populated -->
        </div>
      </div>

    </aside>

  </div>

  <!-- Bottom Timeline & Scenario Player -->
  <footer>
    <div class="play-controls">
      <button class="ctrl-btn play-main" id="btn-play" onclick="togglePlaySimulation()" title="Play / Pause Simulation">
        <svg id="play-svg" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>
      </button>
      <button class="ctrl-btn" onclick="stepSimulation(-1)" title="Previous Timestep">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="19 20 9 12 19 4 19 20"></polygon><line x1="5" y1="19" x2="5" y2="5"></line></svg>
      </button>
      <button class="ctrl-btn" onclick="stepSimulation(1)" title="Next Timestep">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"></polygon><line x1="19" y1="5" x2="19" y2="19"></line></svg>
      </button>
    </div>

    <div class="timeline-container">
      <div class="timeline-header">
        <span class="time-current" id="time-current-label">T+24h (Monsoon Peak Torrent)</span>
        <span class="time-rainfall" id="time-rainfall-label">24h Rain: 140mm | 7d Rain: 240mm | Saturation: 85%</span>
      </div>
      <input type="range" min="0" max="5" value="3" step="1" class="timeline-slider" id="timeline-slider" oninput="onTimelineChange(this.value)">
    </div>
  </footer>

  <!-- Inline Dashboard Payload Data -->
  <script>
    const DASHBOARD_DATA = {json_str};
  </script>

  <!-- Core Visualizer Application Logic -->
  <script>
    let currentTimestepIndex = 3; // default T+24h
    let currentRasterLayer = 'elevation';
    let currentViewMode = '3d';
    let isPlaying = false;
    let playInterval = null;

    // Vector layer visibility states
    const vectorVisibility = {{
      roads: true,
      settlements: true,
      rivers: true,
      critical_assets: true,
      sensors: true
    }};

    // Three.js Globals
    let scene, camera, renderer, controls;
    let terrainMesh = null;
    let vector3DObjects = [];
    let interactiveMeshes = [];
    let raycaster = new THREE.Raycaster();
    let mouse = new THREE.Vector2();

    // Leaflet 2D Globals
    let map2d = null;
    let leafletRasterOverlay = null;
    let leafletVectorLayers = {{}};

    // Initialize on DOM Loaded
    document.addEventListener('DOMContentLoaded', () => {{
      lucide.createIcons();
      initThreeJS();
      initLeaflet();
      updateDashboardData(currentTimestepIndex);
    }});

    // Switch between 2D Map and 3D Digital Twin
    function setViewMode(mode) {{
      currentViewMode = mode;
      document.getElementById('btn-mode-2d').classList.toggle('active', mode === '2d');
      document.getElementById('btn-mode-3d').classList.toggle('active', mode === '3d');
      document.getElementById('camera-presets-bar').style.display = (mode === '3d') ? 'flex' : 'none';

      if (mode === '2d') {{
        document.getElementById('map2d').style.display = 'block';
        document.getElementById('canvas3d').style.display = 'none';
        setTimeout(() => {{
          if (map2d) {{
            map2d.invalidateSize();
            updateLeafletRasterOverlay();
          }}
        }}, 50);
      }} else {{
        document.getElementById('map2d').style.display = 'none';
        document.getElementById('canvas3d').style.display = 'block';
        onWindowResize();
      }}
    }}

    // ==========================================
    // THREE.JS 3D TERRAIN DIGITAL TWIN
    // ==========================================
    function initThreeJS() {{
      const container = document.getElementById('canvas3d');
      const width = container.clientWidth || (window.innerWidth - 690);
      const height = container.clientHeight || (window.innerHeight - 132);

      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x060911);
      scene.fog = new THREE.FogExp2(0x060911, 0.0018);

      camera = new THREE.PerspectiveCamera(45, width / height, 1, 5000);
      camera.position.set(0, -320, 260);

      renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.06;
      controls.maxPolarAngle = Math.PI / 2.05; // don't go below ground
      controls.minDistance = 40;
      controls.maxDistance = 1200;

      // Lights
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
      scene.add(ambientLight);

      const dirLight = new THREE.DirectionalLight(0xfff5e6, 1.15);
      dirLight.position.set(200, -300, 400);
      dirLight.castShadow = true;
      scene.add(dirLight);

      const hemiLight = new THREE.HemisphereLight(0x38bdf8, 0x0f172a, 0.4);
      scene.add(hemiLight);

      // Build 3D Terrain Plane
      build3DTerrainMesh();

      // Build 3D Infrastructure Vectors
      build3DVectorLayers();

      // Setup 3D Raycasting click listener
      container.addEventListener('click', onCanvas3DClick);

      // Start Render Loop
      animate3D();

      window.addEventListener('resize', onWindowResize);
    }}

    function build3DTerrainMesh() {{
      const rows = DASHBOARD_DATA.metadata.rows;
      const cols = DASHBOARD_DATA.metadata.cols;
      const elev = DASHBOARD_DATA.rasters.elevation;

      const geom = new THREE.PlaneGeometry(300, 300, cols - 1, rows - 1);
      const pos = geom.attributes.position;

      // Extrude vertices using elevation values
      for (let r = 0; r < rows; r++) {{
        for (let c = 0; c < cols; c++) {{
          const idx = r * cols + c;
          const z_val = (elev[r][c] - 720.0) * 0.12; // vertical scale
          pos.setZ(idx, z_val);
        }}
      }}
      geom.computeVertexNormals();

      // Create Dynamic Canvas Texture for draped risk heatmap
      const texture = createTerrainTexture();
      const material = new THREE.MeshStandardMaterial({{
        map: texture,
        roughness: 0.8,
        metalness: 0.1,
        flatShading: false
      }});

      terrainMesh = new THREE.Mesh(geom, material);
      terrainMesh.receiveShadow = true;
      terrainMesh.castShadow = true;
      scene.add(terrainMesh);
    }}

    function generateRasterImageData() {{
      const rows = DASHBOARD_DATA.metadata.rows;
      const cols = DASHBOARD_DATA.metadata.cols;
      const riskGrid = DASHBOARD_DATA.risk_simulation.timesteps[currentTimestepIndex].grid;
      const elev = DASHBOARD_DATA.rasters.elevation;

      const canvas = document.createElement('canvas');
      canvas.width = cols;
      canvas.height = rows;
      const ctx = canvas.getContext('2d');
      const imgData = ctx.createImageData(cols, rows);

      for (let r = 0; r < rows; r++) {{
        for (let c = 0; c < cols; c++) {{
          const idx = (r * cols + c) * 4;
          const risk = riskGrid[r][c];
          const eNorm = (elev[r][c] - 720.0) / (2312.0 - 720.0);

          let red = 0, green = 0, blue = 0;

          if (currentRasterLayer === 'elevation') {{
            // Hypsometric tint + draped risk overlay
            if (risk > 60.0) {{
              // High risk highlight (Crimson)
              red = 239; green = 68; blue = 68;
            }} else if (risk > 40.0) {{
              // Moderate risk highlight (Amber)
              red = 245; green = 158; blue = 11;
            }} else {{
              // Base green-brown mountain terrain
              red = Math.floor(30 + eNorm * 120);
              green = Math.floor(60 + eNorm * 110);
              blue = Math.floor(40 + eNorm * 80);
            }}
          }} else if (currentRasterLayer === 'slope') {{
            const slope = DASHBOARD_DATA.rasters.slope[r][c];
            red = Math.floor((slope / 85.0) * 245);
            green = Math.floor((1.0 - slope / 85.0) * 180);
            blue = 50;
          }} else if (currentRasterLayer === 'twi') {{
            const twi = DASHBOARD_DATA.rasters.twi[r][c];
            red = 20;
            green = Math.floor(60 + (twi / 10.0) * 150);
            blue = Math.floor(120 + (twi / 10.0) * 135);
          }} else if (currentRasterLayer === 'tri') {{
            const tri = DASHBOARD_DATA.rasters.tri[r][c];
            red = Math.floor((tri / 100.0) * 220);
            green = Math.floor((tri / 100.0) * 120);
            blue = 200;
          }}

          imgData.data[idx] = red;
          imgData.data[idx + 1] = green;
          imgData.data[idx + 2] = blue;
          imgData.data[idx + 3] = 255;
        }}
      }}

      ctx.putImageData(imgData, 0, 0);
      return canvas;
    }}

    function createTerrainTexture() {{
      const baseCanvas = generateRasterImageData();
      
      // Upscale smoothly to 512x512
      const canvas512 = document.createElement('canvas');
      canvas512.width = 512;
      canvas512.height = 512;
      const ctx = canvas512.getContext('2d');
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(baseCanvas, 0, 0, 512, 512);

      const texture = new THREE.CanvasTexture(canvas512);
      texture.needsUpdate = true;
      return texture;
    }}

    function updateTerrainTexture() {{
      if (!terrainMesh) return;
      const newTex = createTerrainTexture();
      terrainMesh.material.map = newTex;
      terrainMesh.material.needsUpdate = true;
      updateLeafletRasterOverlay();
    }}

    function build3DVectorLayers() {{
      // Clear existing 3D vector objects
      vector3DObjects.forEach(obj => scene.remove(obj));
      vector3DObjects = [];
      interactiveMeshes = [];

      const bounds = DASHBOARD_DATA.metadata.bounds; // [min_lon, min_lat, max_lon, max_lat]
      const rows = DASHBOARD_DATA.metadata.rows;
      const cols = DASHBOARD_DATA.metadata.cols;
      const elev = DASHBOARD_DATA.rasters.elevation;

      function geoTo3D(lon, lat, zOffset = 2.0) {{
        const normX = (lon - bounds[0]) / (bounds[2] - bounds[0]);
        const normY = (lat - bounds[1]) / (bounds[3] - bounds[1]);
        
        const x3d = (normX - 0.5) * 300.0;
        const y3d = (normY - 0.5) * 300.0;

        const r = Math.min(rows - 1, Math.max(0, Math.floor((1.0 - normY) * rows)));
        const c = Math.min(cols - 1, Math.max(0, Math.floor(normX * cols)));
        const z3d = ((elev[r][c] - 720.0) * 0.12) + zOffset;

        return new THREE.Vector3(x3d, y3d, z3d);
      }}

      // 1. NH-29 Highway 3D Extrusion Ribbon
      if (vectorVisibility.roads) {{
        DASHBOARD_DATA.vectors.roads.features.forEach(f => {{
          const coords = f.geometry.coordinates;
          const points = coords.map(pt => geoTo3D(pt[0], pt[1], 1.8));
          
          const curve = new THREE.CatmullRomCurve3(points);
          const tubeGeom = new THREE.TubeGeometry(curve, 32, 1.4, 8, false);
          const tubeMat = new THREE.MeshStandardMaterial({{ color: 0xf87171, emissive: 0x7f1d1d, roughness: 0.4 }});
          const roadMesh = new THREE.Mesh(tubeGeom, tubeMat);
          roadMesh.userData = {{ feature: f }};
          scene.add(roadMesh);
          vector3DObjects.push(roadMesh);
          interactiveMeshes.push(roadMesh);
        }});
      }}

      // 2. Dzüdza River 3D Channel
      if (vectorVisibility.rivers) {{
        DASHBOARD_DATA.vectors.rivers.features.forEach(f => {{
          const coords = f.geometry.coordinates;
          const points = coords.map(pt => geoTo3D(pt[0], pt[1], 1.2));
          
          const curve = new THREE.CatmullRomCurve3(points);
          const tubeGeom = new THREE.TubeGeometry(curve, 32, 1.8, 8, false);
          const tubeMat = new THREE.MeshStandardMaterial({{ color: 0x38bdf8, emissive: 0x0369a1, roughness: 0.1 }});
          const riverMesh = new THREE.Mesh(tubeGeom, tubeMat);
          riverMesh.userData = {{ feature: f }};
          scene.add(riverMesh);
          vector3DObjects.push(riverMesh);
          interactiveMeshes.push(riverMesh);
        }});
      }}

      // 3. IoT Sensor Array with Pulsing Glowing Pins
      if (vectorVisibility.sensors) {{
        DASHBOARD_DATA.vectors.sensors.features.forEach(f => {{
          const [lon, lat] = f.geometry.coordinates;
          const pos3d = geoTo3D(lon, lat, 0.0);

          // Sensor Pin Cylinder
          const pinGeom = new THREE.CylinderGeometry(0.8, 0.8, 14, 16);
          const pinMat = new THREE.MeshStandardMaterial({{ color: 0x10b981, emissive: 0x059669 }});
          const pin = new THREE.Mesh(pinGeom, pinMat);
          pin.rotation.x = Math.PI / 2;
          pin.position.set(pos3d.x, pos3d.y, pos3d.z + 7);
          pin.userData = {{ feature: f }};
          scene.add(pin);
          vector3DObjects.push(pin);
          interactiveMeshes.push(pin);

          // Sensor Status Glowing Sphere Head
          const headGeom = new THREE.SphereGeometry(2.4, 16, 16);
          const headMat = new THREE.MeshStandardMaterial({{ 
            color: f.properties.status === 'Healthy' ? 0x34d399 : 0xf59e0b, 
            emissive: f.properties.status === 'Healthy' ? 0x059669 : 0xb45309 
          }});
          const head = new THREE.Mesh(headGeom, headMat);
          head.position.set(pos3d.x, pos3d.y, pos3d.z + 14);
          head.userData = {{ feature: f }};
          scene.add(head);
          vector3DObjects.push(head);
          interactiveMeshes.push(head);
        }});
      }}

      // 4. Critical Infrastructure Models (Bridges & Power Towers)
      if (vectorVisibility.critical_assets) {{
        DASHBOARD_DATA.vectors.critical_assets.features.forEach(f => {{
          const [lon, lat] = f.geometry.coordinates;
          const pos3d = geoTo3D(lon, lat, 0.0);

          const boxGeom = new THREE.BoxGeometry(5, 5, 12);
          const boxMat = new THREE.MeshStandardMaterial({{ color: 0xc084fc, emissive: 0x581c87 }});
          const box = new THREE.Mesh(boxGeom, boxMat);
          box.position.set(pos3d.x, pos3d.y, pos3d.z + 6);
          box.userData = {{ feature: f }};
          scene.add(box);
          vector3DObjects.push(box);
          interactiveMeshes.push(box);
        }});
      }}

      // 5. Settlements (Village Clusters)
      if (vectorVisibility.settlements) {{
        DASHBOARD_DATA.vectors.settlements.features.forEach(f => {{
          const [lon, lat] = f.geometry.coordinates;
          const pos3d = geoTo3D(lon, lat, 0.0);

          const coneGeom = new THREE.ConeGeometry(5, 10, 6);
          const coneMat = new THREE.MeshStandardMaterial({{ color: 0xfbbf24, emissive: 0xb45309 }});
          const cone = new THREE.Mesh(coneGeom, coneMat);
          cone.rotation.x = Math.PI / 2;
          cone.position.set(pos3d.x, pos3d.y, pos3d.z + 5);
          cone.userData = {{ feature: f }};
          scene.add(cone);
          vector3DObjects.push(cone);
          interactiveMeshes.push(cone);
        }});
      }}
    }}

    function onCanvas3DClick(event) {{
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(interactiveMeshes);

      if (intersects.length > 0) {{
        const clickedObj = intersects[0].object;
        if (clickedObj.userData && clickedObj.userData.feature) {{
          inspectAsset(clickedObj.userData.feature);
        }}
      }}
    }}

    function animate3D() {{
      animationFrameId = requestAnimationFrame(animate3D);
      controls.update();
      renderer.render(scene, camera);
    }}

    function onWindowResize() {{
      const container = document.getElementById('canvas3d');
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (camera && renderer && width && height) {{
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
      }}
    }}

    function setCameraPreset(preset) {{
      if (!camera || !controls) return;
      if (preset === 'perspective') {{
        camera.position.set(0, -320, 260);
        controls.target.set(0, 0, 40);
      }} else if (preset === 'gorge') {{
        camera.position.set(-120, -100, 90);
        controls.target.set(-40, 20, 30);
      }} else if (preset === 'topdown') {{
        camera.position.set(0, 0, 450);
        controls.target.set(0, 0, 0);
      }} else if (preset === 'highway') {{
        camera.position.set(40, -180, 110);
        controls.target.set(10, 0, 50);
      }}
      controls.update();
    }}

    // ==========================================
    // LEAFLET 2D GIS MAP
    // ==========================================
    function initLeaflet() {{
      const bounds = DASHBOARD_DATA.metadata.bounds; // [min_lon, min_lat, max_lon, max_lat]
      const center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2];

      map2d = L.map('map2d', {{
        zoomControl: true,
        attributionControl: false
      }}).setView(center, 13);

      // Dark Basemap Tiles
      L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        maxZoom: 18
      }}).addTo(map2d);

      updateLeafletRasterOverlay();
      renderLeafletLayers();
    }}

    function updateLeafletRasterOverlay() {{
      if (!map2d) return;
      const bounds = DASHBOARD_DATA.metadata.bounds; // [min_lon, min_lat, max_lon, max_lat]
      const latLngBounds = L.latLngBounds([bounds[1], bounds[0]], [bounds[3], bounds[2]]);

      const canvas = generateRasterImageData();
      const imgUrl = canvas.toDataURL();

      if (leafletRasterOverlay) {{
        leafletRasterOverlay.setUrl(imgUrl);
      }} else {{
        leafletRasterOverlay = L.imageOverlay(imgUrl, latLngBounds, {{
          opacity: 0.75,
          interactive: false
        }}).addTo(map2d);
      }}
    }}

    function renderLeafletLayers() {{
      if (!map2d) return;

      // Remove existing vector layers
      Object.values(leafletVectorLayers).forEach(layer => map2d.removeLayer(layer));
      leafletVectorLayers = {{}};

      // 1. Roads
      if (vectorVisibility.roads) {{
        leafletVectorLayers.roads = L.geoJSON(DASHBOARD_DATA.vectors.roads, {{
          style: {{ color: '#f87171', weight: 4.5, opacity: 0.95 }},
          onEachFeature: (f, layer) => {{
            layer.on('click', () => inspectAsset(f));
          }}
        }}).addTo(map2d);
      }}

      // 2. Rivers
      if (vectorVisibility.rivers) {{
        leafletVectorLayers.rivers = L.geoJSON(DASHBOARD_DATA.vectors.rivers, {{
          style: {{ color: '#38bdf8', weight: 4, opacity: 0.85 }},
          onEachFeature: (f, layer) => {{
            layer.on('click', () => inspectAsset(f));
          }}
        }}).addTo(map2d);
      }}

      // 3. Settlements
      if (vectorVisibility.settlements) {{
        leafletVectorLayers.settlements = L.geoJSON(DASHBOARD_DATA.vectors.settlements, {{
          pointToLayer: (f, latlng) => {{
            return L.circleMarker(latlng, {{
              radius: 9,
              fillColor: '#fbbf24',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95
            }});
          }},
          onEachFeature: (f, layer) => {{
            layer.on('click', () => inspectAsset(f));
          }}
        }}).addTo(map2d);
      }}

      // 4. Critical Assets
      if (vectorVisibility.critical_assets) {{
        leafletVectorLayers.critical_assets = L.geoJSON(DASHBOARD_DATA.vectors.critical_assets, {{
          pointToLayer: (f, latlng) => {{
            return L.circleMarker(latlng, {{
              radius: 8,
              fillColor: '#c084fc',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95
            }});
          }},
          onEachFeature: (f, layer) => {{
            layer.on('click', () => inspectAsset(f));
          }}
        }}).addTo(map2d);
      }}

      // 5. Sensors
      if (vectorVisibility.sensors) {{
        leafletVectorLayers.sensors = L.geoJSON(DASHBOARD_DATA.vectors.sensors, {{
          pointToLayer: (f, latlng) => {{
            const isHealthy = f.properties.status === 'Healthy';
            return L.circleMarker(latlng, {{
              radius: 7,
              fillColor: isHealthy ? '#10b981' : '#f59e0b',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 0.95
            }});
          }},
          onEachFeature: (f, layer) => {{
            layer.on('click', () => inspectAsset(f));
          }}
        }}).addTo(map2d);
      }}
    }}

    // ==========================================
    // DATA BINDING & INTERACTIVITY
    // ==========================================
    function updateDashboardData(idx) {{
      currentTimestepIndex = idx;
      const ts = DASHBOARD_DATA.risk_simulation.timesteps[idx];
      const rep = DASHBOARD_DATA.risk_simulation.exposure_reports[idx];

      // Update Header & Stats
      document.getElementById('hdr-pop').textContent = rep.threatened_population.toLocaleString() + ' Res';
      document.getElementById('hdr-road').textContent = rep.total_exposed_road_km.toFixed(1) + ' km';
      document.getElementById('hdr-alert-text').textContent = rep.evacuation_alert_level;

      const alertBanner = document.getElementById('hdr-alert');
      alertBanner.className = 'alert-banner-badge ' + (ts.max_risk >= 80.0 ? 'alert-red' : (ts.max_risk >= 60.0 ? 'alert-orange' : 'alert-yellow'));

      // Update Right Sidebar
      document.getElementById('stat-road-km').textContent = rep.total_exposed_road_km.toFixed(1) + ' km';
      document.getElementById('stat-pop').textContent = rep.threatened_population.toLocaleString();
      document.getElementById('stat-assets').textContent = rep.critical_assets_at_risk_count + ' Units';
      document.getElementById('stat-max-risk').textContent = ts.max_risk.toFixed(1) + '%';

      // Update Ranked Action Priorities List
      const container = document.getElementById('ranked-asset-container');
      container.innerHTML = '';

      rep.ranked_priority_list.forEach((item, rIdx) => {{
        const card = document.createElement('div');
        const isCrit = item.priority_score >= 75.0;
        card.className = `asset-card ${{isCrit ? 'critical' : 'warning'}}`;
        card.onclick = () => showActionDetails(item);

        card.innerHTML = `
          <div class="asset-header">
            <span class="asset-title">#${{rIdx + 1}} ${{item.asset_name}}</span>
            <span class="priority-badge">R&times;I: ${{item.priority_score}}</span>
          </div>
          <div class="asset-desc">${{item.threat_description}}</div>
          <div class="action-box">
            <i data-lucide="shield" style="width: 14px; height: 14px; flex-shrink: 0;"></i>
            <span>${{item.recommended_action}}</span>
          </div>
        `;
        container.appendChild(card);
      }});

      lucide.createIcons();

      // Update Bottom Timeline Controls
      document.getElementById('time-current-label').textContent = ts.label;
      document.getElementById('time-rainfall-label').textContent = `24h Rain: ${{ts.rainfall_24h_mm}}mm | 7d Rain: ${{ts.rainfall_7d_mm}}mm | Saturation: ${{Math.min(100, Math.round(ts.rainfall_7d_mm / 3.4))}}%`;
      document.getElementById('timeline-slider').value = idx;

      // Update Draped Heatmap Textures on 3D & 2D
      updateTerrainTexture();
    }}

    function selectRaster(layer) {{
      currentRasterLayer = layer;
      
      // Update radio inputs and active styling
      document.querySelectorAll('#raster-layer-group .layer-item').forEach(item => {{
        const radio = item.querySelector('input[type="radio"]');
        const isMatch = (radio.value === layer);
        radio.checked = isMatch;
        item.classList.toggle('active', isMatch);
      }});

      updateTerrainTexture();
    }}

    function toggleVector(layerName, explicitVal) {{
      const chk = document.getElementById(`chk-${{layerName}}`);
      const item = document.getElementById(`item-${{layerName}}`);
      
      const newVal = (explicitVal !== undefined) ? explicitVal : !chk.checked;
      chk.checked = newVal;
      vectorVisibility[layerName] = newVal;
      item.classList.toggle('active', newVal);

      build3DVectorLayers();
      renderLeafletLayers();
    }}

    function onTimelineChange(val) {{
      updateDashboardData(parseInt(val));
    }}

    function stepSimulation(delta) {{
      let next = currentTimestepIndex + delta;
      if (next < 0) next = 0;
      if (next > 5) next = 5;
      updateDashboardData(next);
    }}

    function togglePlaySimulation() {{
      isPlaying = !isPlaying;
      const btn = document.getElementById('btn-play');

      if (isPlaying) {{
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect width="4" height="16" x="6" y="4"></rect><rect width="4" height="16" x="14" y="4"></rect></svg>`;
        playInterval = setInterval(() => {{
          let next = (currentTimestepIndex + 1) % 6;
          updateDashboardData(next);
        }}, 2200);
      }} else {{
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"></polygon></svg>`;
        clearInterval(playInterval);
      }}
    }}

    function inspectAsset(f) {{
      const props = f.properties;
      const modal = document.getElementById('inspector-modal');
      const content = document.getElementById('inspector-content');

      let html = `<h3 style="font-family: var(--font-heading); color: #38bdf8; margin-bottom: 8px;">${{props.name || props.asset_id}}</h3>`;
      html += `<div style="font-size: 0.75rem; color: #94a3b8; display: flex; flex-direction: column; gap: 4px;">`;
      
      for (const [k, v] of Object.entries(props)) {{
        html += `<div><strong style="color: #f8fafc;">${{k}}:</strong> ${{v}}</div>`;
      }}
      html += `</div>`;

      content.innerHTML = html;
      modal.style.display = 'block';
    }}

    function showActionDetails(item) {{
      const modal = document.getElementById('inspector-modal');
      const content = document.getElementById('inspector-content');

      content.innerHTML = `
        <h3 style="font-family: var(--font-heading); color: #f87171; margin-bottom: 6px;">${{item.asset_name}}</h3>
        <div style="font-size: 0.75rem; color: #cbd5e1; margin-bottom: 10px;">
          <div><strong>Asset Class:</strong> ${{item.asset_type}}</div>
          <div><strong>Max Hazard Risk:</strong> ${{item.max_hazard_risk}}%</div>
          <div><strong>Priority Score (R&times;I):</strong> ${{item.priority_score}}</div>
          <div><strong>Emergency Status:</strong> ${{item.status}}</div>
        </div>
        <div style="background: rgba(244,63,94,0.15); border: 1px solid rgba(244,63,94,0.3); border-radius: 6px; padding: 8px; font-size: 0.72rem; color: #fda4af;">
          <strong>Action Directive:</strong><br>${{item.recommended_action}}
        </div>
      `;
      modal.style.display = 'block';
    }}

    function closeInspector() {{
      document.getElementById('inspector-modal').style.display = 'none';
    }}

    function exportPriorityReport() {{
      const rep = DASHBOARD_DATA.risk_simulation.exposure_reports[currentTimestepIndex];
      const blob = new Blob([JSON.stringify(rep, null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `NER_Landslide_Exposure_Report_${{rep.time_label.replace(/[^a-zA-Z0-9]/g, '_')}}.json`;
      a.click();
    }}
  </script>
</body>
</html>
"""

    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_template)

    print(f"[OK] Standalone 2D/3D Dashboard built: {output_html} ({os.path.getsize(output_html) / 1024:.1f} KB)")


if __name__ == "__main__":
    build_standalone_dashboard()
