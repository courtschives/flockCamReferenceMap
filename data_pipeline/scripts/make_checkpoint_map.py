"""Create a local HTML map showing cameras and census county population.

This uses folium to create `data/output/checkpoint_map.html` combining the
camera snapshot (or fallback sample) and the census county GeoJSON.
"""
import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import folium
import pandas as pd
from folium import Element
import geopandas as gpd


def _sanitize_geojson_frame(df):
    """Convert non-JSON-serializable values such as pandas Timestamp/NaT to JSON-safe strings."""
    df = df.copy()
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            df[col] = s.map(lambda v: None if pd.isna(v) else v.isoformat())
        elif s.dtype == object:
            df[col] = s.map(lambda v: None if pd.isna(v) else (v.isoformat() if hasattr(v, 'isoformat') and not isinstance(v, (str, bytes)) else v))
    return df


def main():
    repo_root = Path(__file__).resolve().parents[2]
    out_html = repo_root / 'data' / 'output' / 'checkpoint_map.html'
    out_html.parent.mkdir(parents=True, exist_ok=True)

    # Prefer the newest real camera snapshot (by manifest created_at, falling back
    # to filename sort), else use the tiny synthetic sample. Snapshots can be large
    # (100K+ points nationwide); rather than rejecting a big snapshot outright and
    # silently falling back to 3 demo points, we load it and subsample below so the
    # checkpoint map always shows real data.
    snapshot_dir = repo_root / 'data' / 'snapshots'
    cameras = repo_root / 'data' / 'output' / 'cameras_sample.geojson'
    if snapshot_dir.exists():
        manifests = sorted(snapshot_dir.glob('cameras_snapshot_*.manifest.json'))
        candidate = None
        if manifests:
            try:
                latest_manifest = max(manifests, key=lambda p: json.loads(p.read_text()).get('created_at', ''))
                mf = json.loads(latest_manifest.read_text())
                mf_file = Path(mf.get('file', ''))
                if mf_file.exists():
                    candidate = mf_file
            except Exception:
                candidate = None
        if candidate is None:
            snaps = sorted(list(snapshot_dir.glob('cameras_snapshot_*.geojson')))
            if snaps:
                candidate = snaps[-1]
        if candidate is not None:
            cameras = candidate

    census_geo = repo_root / 'data' / 'output' / 'census_counties_population.geojson'
    if not census_geo.exists():
        print('Census geojson not found, aborting map creation')
        return

    religion_geo = repo_root / 'data' / 'output' / 'religion_counties.geojson'
    religion = None
    if religion_geo.exists():
        religion = _sanitize_geojson_frame(gpd.read_file(str(religion_geo)).to_crs(epsg=4326))

    crime_geo = repo_root / 'data' / 'output' / 'crime_counties.geojson'
    crime = None
    if crime_geo.exists():
        crime = _sanitize_geojson_frame(gpd.read_file(str(crime_geo)).to_crs(epsg=4326))

    # load census counties (for choropleth)
    counties = _sanitize_geojson_frame(gpd.read_file(str(census_geo)).to_crs(epsg=4326))
    # choose a numeric population column if present
    pop_col = None
    for c in ['B01003_001E', 'population', 'POPULATION', 'B01003_001']:
        if c in counties.columns:
            pop_col = c
            break
    if pop_col is None:
        # attempt to find first numeric column
        for c in counties.columns:
            if c in ['county_fips', 'GEOID', 'geometry']:
                continue
            try:
                counties[c] = counties[c].astype(float)
                pop_col = c
                break
            except Exception:
                continue

    # Population group options: Total Population plus whichever race/ethnicity
    # pct_* columns census_acs.py computed (share of county total population).
    # "Total Population" uses raw counts; every race/ethnicity group uses %
    # share, so counties are compared by concentration, not just raw size.
    RACE_GROUP_LABELS = {
        'pct_white': '% White',
        'pct_black': '% Black',
        'pct_hispanic': '% Hispanic or Latino',
        'pct_asian': '% Asian',
        'pct_aian': '% American Indian / Alaska Native',
        'pct_nhpi': '% Native Hawaiian / Pacific Islander',
        'pct_two_or_more': '% Two or More Races',
    }
    pop_group_options = []
    if pop_col and pop_col in counties.columns:
        pop_group_options.append({'key': pop_col, 'label': 'Total Population', 'isPct': False})
    for key, label in RACE_GROUP_LABELS.items():
        if key in counties.columns:
            pop_group_options.append({'key': key, 'label': label, 'isPct': True})

    # Religion group options: all percentages (share of county population claimed
    # by that tradition), including a "Not Claimed by Any Religious Body" option -
    # see religion_census.py's module docstring for why that's phrased that way
    # rather than "unaffiliated" (it's a different methodology than a Gallup/Pew
    # self-identification survey).
    RELIGION_GROUP_LABELS = {
        'pct_any_affiliation': 'Any Religious Affiliation',
        'pct_catholic': 'Catholic',
        'pct_evangelical': 'Evangelical Protestant',
        'pct_mainline': 'Mainline Protestant',
        'pct_black_protestant': 'Historically Black Protestant',
        'pct_lds': 'Latter-day Saints',
        'pct_jehovahs_witness': "Jehovah's Witness",
        'pct_orthodox_christian': 'Orthodox Christian',
        'pct_jewish': 'Jewish',
        'pct_muslim': 'Muslim',
        'pct_buddhist': 'Buddhist',
        'pct_hindu': 'Hindu',
        'pct_other': 'Other Religions',
        'pct_unclaimed': 'Not Claimed by Any Religious Body',
    }
    religion_group_options = []
    if religion is not None:
        for key, label in RELIGION_GROUP_LABELS.items():
            if key in religion.columns:
                religion_group_options.append({'key': key, 'label': label, 'isPct': True})
        for opt in religion_group_options:
            try:
                religion[opt['key']] = pd.to_numeric(religion[opt['key']], errors='coerce').fillna(0)
            except Exception:
                religion[opt['key']] = 0
        # trim to what the client actually needs (geometry + fips + the pct_* columns) -
        # same reasoning as the camera property trim: no reason to ship raw adherent
        # counts, county name/land-area columns, etc. to the browser.
        religion = religion[['county_fips', 'geometry'] + [o['key'] for o in religion_group_options]]

    # Crime group options: hate crime rate (real county-level data, but only for
    # the curated top-metro + state-capital counties - see fbi_crime.py) and
    # general offense rate (state-level applied to every county, since the FBI API
    # has no working agency/county-level endpoint for this - also in fbi_crime.py's
    # module docstring). Grouped and prefixed in the dropdown so it's clear which
    # resolution each option is. NOT coerced with fillna(0): missing hate-crime data
    # for a non-target county must stay null/NaN so the client can render "no data"
    # instead of a misleading "zero crime" color.
    CRIME_GROUP_LABELS = {
        'hate_crime_total': 'Hate Crime: All Bias Categories (county)',
        'hate_crime_race': 'Hate Crime: Race/Ethnicity/Ancestry (county)',
        'hate_crime_religion': 'Hate Crime: Religion (county)',
        'hate_crime_orientation': 'Hate Crime: Sexual Orientation (county)',
        'hate_crime_gender_identity': 'Hate Crime: Gender Identity (county)',
        'hate_crime_disability': 'Hate Crime: Disability (county)',
        'hate_crime_gender': 'Hate Crime: Gender (county)',
        'offense_rate_violent': 'Offense Rate: Violent Crime (state)',
        'offense_rate_property': 'Offense Rate: Property Crime (state)',
        'offense_rate_homicide': 'Offense Rate: Homicide (state)',
        'offense_rate_robbery': 'Offense Rate: Robbery (state)',
        'offense_rate_burglary': 'Offense Rate: Burglary (state)',
        'offense_rate_mvtheft': 'Offense Rate: Motor Vehicle Theft (state)',
    }
    crime_group_options = []
    if crime is not None:
        for key, label in CRIME_GROUP_LABELS.items():
            if key in crime.columns:
                crime_group_options.append({'key': key, 'label': label, 'isPct': False})
        for opt in crime_group_options:
            try:
                crime[opt['key']] = pd.to_numeric(crime[opt['key']], errors='coerce')
            except Exception:
                pass
        crime = crime[['county_fips', 'geometry'] + [o['key'] for o in crime_group_options]]

    # center map
    center = [39.5, -98.35]
    m = folium.Map(location=center, zoom_start=4)
    # Prepare data for client-side rendering: counties GeoJSON and cameras GeoJSON
    for opt in pop_group_options:
        try:
            counties[opt['key']] = pd.to_numeric(counties[opt['key']], errors='coerce').fillna(0)
        except Exception:
            counties[opt['key']] = 0

    try:
        cams = _sanitize_geojson_frame(gpd.read_file(str(cameras)).to_crs(epsg=4326))
    except Exception as e:
        print('Warning: failed to load cameras for map:', e)
        cams = gpd.GeoDataFrame(columns=['geometry'])

    # Raw OSM extracts carry the full union of every tag key seen anywhere in the
    # dataset (389 columns for the nationwide snapshot), and GeoPandas writes that
    # whole schema, mostly null, for every single feature. Drop to just the
    # properties the client JS actually reads before sampling/exporting.
    KEEP_COLS = ['operator', 'source', 'county_fips', 'surveillance:type',
                 'camera:type', 'camera:brand', 'camera:direction', 'direction',
                 'camera:orientation', 'osm_id', 'osm_type', 'geometry']
    cams = cams[[c for c in KEEP_COLS if c in cams.columns]]

    # Ship the full dataset. Marker clustering (added below, client-side) keeps
    # this responsive at any zoom level without needing to sample the data down -
    # only a safety ceiling remains in case a future snapshot is far larger than
    # anything seen so far.
    MAX_CAMERAS = 500000
    cameras_sampled = False
    cameras_total = len(cams)
    if cameras_total > MAX_CAMERAS:
        cams = cams.sample(n=MAX_CAMERAS, random_state=42)
        cameras_sampled = True
    print(f'Using {len(cams)} of {cameras_total} camera features from {cameras.name}')

    counties_json = json.loads(counties.to_json())
    cams_json = json.loads(cams.to_json())
    religion_json = json.loads(religion.to_json()) if religion is not None else {'type': 'FeatureCollection', 'features': []}
    crime_json = json.loads(crime.to_json()) if crime is not None else {'type': 'FeatureCollection', 'features': []}

    # write out separate JSON files for client-side fetching (avoid inlining huge blobs)
    out_dir = out_html.parent
    counties_path = out_dir / 'checkpoint_counties.json'
    cams_path = out_dir / 'checkpoint_cameras.json'
    religion_path = out_dir / 'checkpoint_religion.json'
    crime_path = out_dir / 'checkpoint_crime.json'
    try:
        with open(counties_path, 'w', encoding='utf-8') as fh:
            json.dump(counties_json, fh)
        with open(cams_path, 'w', encoding='utf-8') as fh:
            json.dump(cams_json, fh)
        with open(religion_path, 'w', encoding='utf-8') as fh:
            json.dump(religion_json, fh)
        with open(crime_path, 'w', encoding='utf-8') as fh:
            json.dump(crime_json, fh)
    except Exception:
        # fall back to in-memory variables if filesystem write fails
        pass

    # build operator -> color map. Deliberately cool-toned (blue/aqua/violet/
    # magenta/green) and disjoint from the population choropleth's yellow-orange-
    # red sequential ramp below, so the two layers never read as the same scale.
    # Validated for CVD-safety with the dataviz skill's palette checker
    # (light-mode, all-pairs; worst-case CVD ΔE 6.1, normal-vision floor 15.6 -
    # passes with popups providing operator names as secondary encoding).
    # 'unknown' (the single largest bucket in the raw OSM data) gets a fixed
    # neutral gray rather than a slot from the cycling palette, since it isn't
    # a real identity and shouldn't visually compete with named operators.
    CAMERA_PALETTE = ['#2a78d6', '#1baf7a', '#4a3aa7', '#e87ba4', '#008300']
    UNKNOWN_COLOR = '#8a8f98'
    ops = []
    for f in cams_json.get('features', []):
        op = (f.get('properties') or {}).get('operator') or (f.get('properties') or {}).get('source') or 'unknown'
        if op not in ops:
            ops.append(op)
    op_colors = {}
    palette_i = 0
    for op in ops:
        if op == 'unknown':
            op_colors[op] = UNKNOWN_COLOR
        else:
            op_colors[op] = CAMERA_PALETTE[palette_i % len(CAMERA_PALETTE)]
            palette_i += 1
    CAMERA_STROKE = '#20232a'

    # read snapshot manifest for timestamp display if present
    snapshot_ts = None
    snapshot_src = None
    try:
        snaps = sorted(list(snapshot_dir.glob('cameras_snapshot_*.manifest.json')))
        if snaps:
            mpath = snaps[-1]
            mtxt = json.loads(mpath.read_text())
            snapshot_ts = mtxt.get('created_at')
            snapshot_src = mtxt.get('source')
    except Exception:
        pass

    # render base map (we'll populate layers with client JS)
    # prefer_canvas=True: with tens of thousands of camera markers, SVG rendering
    # (folium/Leaflet's default) is far too slow; canvas rendering keeps pan/zoom usable.
    # zoom_control=False: replaced below with a client-positioned control (bottom-right)
    # so it doesn't overlap the left control panel.
    # worldCopyJump=True: the base tile layer repeats infinitely (normal Leaflet
    # behavior), but our county polygons and camera markers only exist at their one
    # literal coordinate - panning to a repeated world copy showed empty tiles with
    # no data. worldCopyJump snaps the view back to the equivalent point in the
    # copy that actually holds the data once panning stops, rather than needing every
    # layer duplicated at +-360 degrees longitude.
    # min_zoom=3: a DIFFERENT flavor of the same underlying issue - at zoom 0-2 the
    # world is only 256-1024px wide, narrower than most browser viewports, so two or
    # more copies are visible side by side simultaneously with no panning involved at
    # all (worldCopyJump can't fix this, it only corrects drift from dragging). At
    # zoom 3 the world is 2048px wide, wider than the vast majority of viewports, so
    # only one copy is ever visible - while still leaving plenty of zoom-out room
    # above the zoom_start=4 continental-US default view.
    m = folium.Map(location=center, zoom_start=4, min_zoom=3, prefer_canvas=True, zoom_control=False, worldCopyJump=True)

    # Leaflet.markercluster: the nationwide camera dataset (100K+ points) is shipped
    # in full rather than sampled - clustering is what keeps that renderable, only
    # materializing individual marker icons for whatever is actually on screen.
    # CSS is order-independent so it can go in <head>; the JS can't - folium injects
    # its own leaflet.js requirement into <head> at save() time, at an internal
    # position we don't control, so a <script> placed in <head> here can end up
    # BEFORE leaflet.js and crash with "L is not defined". Body scripts execute
    # only after the entire <head> (all synchronous scripts) has already run, so
    # putting it in <body> - right before checkpoint_map.js, further down - is
    # what actually guarantees load order.
    m.get_root().header.add_child(Element(
        '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>'
        '<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>'
    ))
    # expose the folium-generated map variable to `window.map` so client JS can reference it
    try:
        map_name = m.get_name()
        # folium places its own `var {map_name} = L.map(...)` initialization
        # script AFTER the closing </body> tag, so any script we inject earlier
        # in <body> that references {map_name} directly throws a ReferenceError
        # (the variable doesn't exist yet at that point in parsing). Deferring
        # to DOMContentLoaded runs this after the whole document, including
        # folium's trailing script, has parsed and executed.
        m.get_root().html.add_child(Element(
            f"<script>window.addEventListener('DOMContentLoaded', function(){{ window.map = {map_name}; }});</script>"
        ))
    except Exception:
        pass

    # expose small metadata and palette to JS; large geo data will be fetched as separate files
    data_script = f"""
    <script>
    var countiesUrl = 'checkpoint_counties.json';
    var camsUrl = 'checkpoint_cameras.json';
    var opColors = {json.dumps(op_colors)};
    var camStroke = '{CAMERA_STROKE}';
    var popGroupOptions = {json.dumps(pop_group_options)};
    var totalPopCol = '{pop_col}';
    var popCol = '{pop_col}';
    var popIsPct = false;
    var religionGroupOptions = {json.dumps(religion_group_options)};
    var crimeGroupOptions = {json.dumps(crime_group_options)};
    var snapshotTS = '{snapshot_ts or ''}';
    var snapshotSource = '{snapshot_src or ''}';
    var camerasSampled = {json.dumps(cameras_sampled)};
    var camerasTotal = {cameras_total};
    var camerasShown = {len(cams)};
    </script>
    """
    m.get_root().html.add_child(Element(data_script))

    # add control panel and legends container
    control_html = """
    <style>
    /* Fix the page itself - only #leftpanel scrolls. Without this, growing panel
       content (Population + Religion + Crime sections) pushes the whole document
       taller than the viewport and the BODY scrolls, which drags the map out of
       view along with it. */
    html, body { overflow: hidden !important; }
    /* #leftpanel itself does NOT scroll or clip - #btn_collapse is deliberately
       positioned outside its box (right:-28px) to look like an attached tab, and
       an overflow other than visible here would clip that button off. The actual
       scrolling happens on the #leftpanel-content wrapper inside it. */
    #leftpanel { position: absolute; left: 10px; top: 10px; z-index:1000; width:260px; transition: transform 0.2s ease; }
    #leftpanel.collapsed { transform: translateX(-280px); }
    #leftpanel-content { background: white; padding: 8px; border-radius:6px; box-shadow:0 2px 6px rgba(0,0,0,0.3); max-height: calc(100vh - 20px); overflow-y: auto; }
    #leftpanel h4 { margin:0 0 6px 0; font-size:14px }
    #panel-title { margin:4px 0 8px 0; font-size:15px; line-height:1.25; padding-right:6px; }
    #leftpanel .row { margin:6px 0 }
    #btn_collapse { position:absolute; right:-28px; top:8px; width:28px; height:28px; background:white; border:none; border-radius:0 6px 6px 0; box-shadow:2px 2px 4px rgba(0,0,0,0.25); cursor:pointer; font-size:14px; }
    .legend { font-size:12px }
    .legend .item { display:flex; align-items:center; margin:2px 0 }
    .legend .swatch { width:18px; height:12px; margin-right:8px; border:1px solid #666 }
    details.src { font-size:11px; margin:4px 0; color:#444; }
    details.src summary { cursor:pointer; font-weight:600; color:#555; }
    details.src div { margin-top:4px; line-height:1.4; }
    .info-icon { cursor:help; color:#777; font-size:14px; border-bottom:1px dotted #999; }
    .leaflet-control.cam-eye-control a { font-size:16px; display:flex; align-items:center; justify-content:center; text-decoration:none; }
    /* Recolor cluster bubbles to the cool camera palette (blue/aqua/violet) -
       the library default is green/yellow/orange, which reads as the same scale
       as the yellow-orange-red population choropleth underneath it. */
    .marker-cluster-small { background-color: rgba(42,120,214,0.4); }
    .marker-cluster-small div { background-color: rgba(42,120,214,0.75); }
    .marker-cluster-medium { background-color: rgba(27,175,122,0.4); }
    .marker-cluster-medium div { background-color: rgba(27,175,122,0.75); }
    .marker-cluster-large { background-color: rgba(74,58,167,0.4); }
    .marker-cluster-large div { background-color: rgba(74,58,167,0.75); }
    .marker-cluster span { color: #fff; font-weight: 600; }
    </style>
    <div id="leftpanel">
        <button id="btn_collapse" title="Collapse panel">&#9664;</button>
        <div id="leftpanel-content">
        <h3 id="panel-title">Flock Camera Cross-Reference Map</h3>
        <div class="row"><strong>Snapshot:</strong><div id="snap_meta">%s %s</div></div>
        <div class="row" id="sample_meta"></div>
        <div class="row"><em>Static point-in-time data snapshot, not a live feed.</em></div>
        <hr>

        <h4>Layers & Controls</h4>

        <div class="row"><label><input type="checkbox" id="chk_cameras" checked> <strong>Cameras</strong></label></div>
        <div class="row">Opacity: <input type="range" id="sld_cameras" min="0" max="1" step="0.05" value="1"></div>
        <details class="src"><summary>Sources</summary>
            <div>OpenStreetMap contributors (surveillance:type=ALPR and related tags), extracted via osmium from an OSM regional/national data export. &copy; OpenStreetMap contributors, ODbL license.</div>
        </details>
        <hr>

        <div class="row">Focus state: <span class="info-icon" title="Dims other states to hone in on one place - all county data stays available underneath (click through for popups), nothing is hidden or filtered out.">&#9432;</span></div>
        <div class="row"><select id="state_focus" style="width:100%%"></select></div>
        <hr>

        <div class="row"><label><input type="checkbox" id="chk_census" checked> <strong>Population</strong></label></div>
        <div class="row">Show: <select id="pop_group" style="width:100%%"></select></div>
        <div class="row">Classes: <input type="range" id="pop_classes" min="2" max="9" value="6"></div>
        <div class="row">Opacity: <input type="range" id="sld_census" min="0" max="1" step="0.05" value="0.8"></div>
        <div class="row legend" id="pop_legend"><strong>Population</strong></div>
        <details class="src"><summary>Sources</summary>
            <div>US Census Bureau, American Community Survey (ACS) 5-Year Estimates, 2024 release (2020-2024 vintage) - population and race/ethnicity, retrieved via the Census API (api.census.gov). County boundaries: Census Bureau cartographic boundary file (cb_2022_us_county_20m).</div>
        </details>
        <hr>

        <div class="row"><label><input type="checkbox" id="chk_religion"> <strong>Religion</strong></label></div>
        <div class="row">Show: <select id="religion_group" style="width:100%%"></select></div>
        <div class="row">Classes: <input type="range" id="religion_classes" min="2" max="9" value="6"></div>
        <div class="row">Opacity: <input type="range" id="sld_religion" min="0" max="1" step="0.05" value="0.8"></div>
        <div class="row legend" id="religion_legend"><strong>Religion</strong></div>
        <details class="src"><summary>Sources</summary>
            <div>2020 U.S. Religion Census: Religious Congregations and Membership Study, by the Association of Statisticians of American Religious Bodies (ASARB), distributed via the Association of Religion Data Archives (usreligioncensus.org). Counts adherents claimed by reporting congregations, not a self-identification survey - "Not Claimed" is not the same thing as "unaffiliated" in a Gallup/Pew poll.</div>
        </details>
        <hr>

        <div class="row"><label><input type="checkbox" id="chk_crime"> <strong>Crime</strong></label></div>
        <div class="row">Show: <select id="crime_group" style="width:100%%"></select></div>
        <div class="row">Classes: <input type="range" id="crime_classes" min="2" max="9" value="6"></div>
        <div class="row">Opacity: <input type="range" id="sld_crime" min="0" max="1" step="0.05" value="0.8"></div>
        <div class="row legend" id="crime_legend"><strong>Crime</strong></div>
        <details class="src"><summary>Sources</summary>
            <div>FBI Crime Data Explorer API (api.usa.gov/crime/fbi/cde). "(county)" options are real per-agency hate crime data aggregated for the ~100 largest counties by population plus every state capital's county - elsewhere shown as no data, not zero. "(state)" options are state-level general offense rates applied to every county in that state - the FBI API's agency-level endpoint for general offense rates is broken (verified: it returns state data regardless of which agency is queried), only hate crime has working agency-level data.</div>
        </details>
        <hr>
        </div>
    </div>
    """ % (snapshot_ts or '', snapshot_src or '')
    m.get_root().html.add_child(Element(control_html))

    # client-side JS to render layers, popups, FOV, legends, and interactivity
    js = """
    (function(){
    // helper: compute quantile breaks
    function quantileBreaks(values, n) {
        var vals = values.slice().sort(function(a,b){return a-b});
        var breaks = [];
        for (var i=1;i<n;i++){
            var idx = Math.floor(i*vals.length/n);
            breaks.push(vals[idx]);
        }
        return breaks;
    }
    // Population, Religion, and Crime each get their own hue so stacking them
    // (with opacity, to visually cross-reference) doesn't collapse into an
    // ambiguous blend - a dark tile needs to read as "which layer, or both" by
    // color alone, not just by whichever legend the reader remembers to check.
    var popPal = ['#ffffcc','#ffeda0','#fed976','#feb24c','#fd8d3c','#fc4e2a','#e31a1c','#bd0026','#800026'];
    var religionPal = ['#cde2fb','#b7d3f6','#9ec5f4','#86b6ef','#6da7ec','#3987e5','#256abf','#184f95','#0d366b'];
    // Purple (an earlier candidate) validated as too close to Religion's blue at
    // the dark end (CVD ΔE 3.8, normal-vision ΔE 11.6 - both below the pass
    // floors); teal, anchored on the dataviz skill's validated "slot 3" aqua hue
    // (the documented next sequential hue after blue/orange are already taken),
    // clears CVD separation (9.4) and the normal-vision floor (20.6) against both
    // Population's red and Religion's blue endpoints.
    var crimePal = ['#e3f9f0','#c9f2e2','#a3e8cd','#78d9b3','#4ec89a','#1baf7a','#189567','#147d58','#116f4d'];
    var NO_DATA_COLOR = '#e8e8e8';

    function isMissing(v) { return v === null || v === undefined || (typeof v === 'number' && isNaN(v)); }

    // Generic single-select choropleth: builds a Leaflet geoJson layer whose
    // active property/color/legend/popup all derive from one dropdown-selected
    // key (never more than one group shown at once, per-layer). Population,
    // Religion, and Crime all use this - they're the same mechanism (one active
    // group, one hue, county polygons) over different county-joined datasets, so
    // this is the one implementation all three share. Crime is the first layer
    // with real partial coverage (only ~136 counties have hate-crime data), so
    // this treats null/missing distinctly from 0 throughout: excluded from the
    // quantile breaks, rendered in a flat neutral gray, called out in the legend
    // and popup as "No data" rather than folding into the lowest color bucket -
    // conflating "no data" with "zero crime" is exactly the kind of misleading
    // gap-hiding the project's data sources call out explicitly (uneven crime
    // reporting) and is worth getting right generically, not just for Crime.
    function createChoroplethLayer(cfg) {
        var state = {key: cfg.defaultKey, isPct: false};
        var initOpt = cfg.options.filter(function(o){ return o.key === cfg.defaultKey; })[0];
        if (initOpt) state.isPct = !!initOpt.isPct;
        var values = [];
        function recompute() {
            values = cfg.data.features.map(function(f){ return f.properties[state.key]; })
                .filter(function(v){ return !isMissing(v); })
                .map(Number);
        }
        recompute();
        function formatValue(v) {
            if (isMissing(v)) return 'No data';
            return state.isPct ? (Math.round(v * 10) / 10) + '%' : Math.round(v).toLocaleString();
        }
        function currentLabel() {
            var opt = cfg.options.filter(function(o){ return o.key === state.key; })[0];
            return opt ? opt.label : cfg.legendFallback;
        }
        function styleForFeature(feature, breaks) {
            var raw = feature.properties[state.key];
            if (isMissing(raw)) {
                return {color:'#999', weight:0.5, fillColor: NO_DATA_COLOR, fillOpacity: Number(cfg.opacityEl.value) * 0.5, dashArray: '3'};
            }
            var v = Number(raw);
            var idx = 0;
            while (idx < breaks.length && v > breaks[idx]) idx++;
            return {color:'#555', weight:0.5, fillColor: cfg.palette[idx], fillOpacity: Number(cfg.opacityEl.value)};
        }
        var layer = L.geoJson(cfg.data, {
            style: function(f){ return styleForFeature(f, quantileBreaks(values, Number(cfg.classesEl.value))); },
            onEachFeature: function(feature, lyr){
                lyr.bindPopup(function(){ return cfg.popupBuilder(feature, state, formatValue); });
            }
        });
        function update() {
            var n = Number(cfg.classesEl.value);
            var breaks = quantileBreaks(values, n);
            layer.eachLayer(function(lyr){ lyr.setStyle(styleForFeature(lyr.feature, breaks)); });
            var legend = cfg.legendEl;
            legend.innerHTML = '<strong>'+currentLabel()+'</strong>';
            for (var i=0;i<n;i++){
                var lo = i===0?0:breaks[i-1];
                var hi = i<breaks.length?breaks[i]:Math.max.apply(null, values);
                legend.innerHTML += '<div class="item"><div class="swatch" style="background:'+cfg.palette[i]+'"></div><div>'+formatValue(lo)+' - '+formatValue(hi)+'</div></div>';
            }
            var hasMissing = cfg.data.features.some(function(f){ return isMissing(f.properties[state.key]); });
            if (hasMissing) {
                legend.innerHTML += '<div class="item"><div class="swatch" style="background:'+NO_DATA_COLOR+'; border-style:dashed;"></div><div>No data</div></div>';
            }
        }
        cfg.options.forEach(function(opt){
            var o = document.createElement('option');
            o.value = opt.key; o.textContent = opt.label;
            cfg.selectEl.appendChild(o);
        });
        cfg.selectEl.value = state.key;
        cfg.selectEl.addEventListener('change', function(){
            var opt = cfg.options.filter(function(o){ return o.key === cfg.selectEl.value; })[0];
            state.key = cfg.selectEl.value;
            state.isPct = opt ? !!opt.isPct : false;
            recompute(); update();
        });
        cfg.classesEl.addEventListener('input', update);
        cfg.opacityEl.addEventListener('input', update);
        return {layer: layer, update: update};
    }

    function initWithData(countiesData, religionData, crimeData, camsData) {
    var popChoropleth = createChoroplethLayer({
        data: countiesData,
        palette: popPal,
        defaultKey: totalPopCol,
        options: popGroupOptions,
        selectEl: document.getElementById('pop_group'),
        classesEl: document.getElementById('pop_classes'),
        opacityEl: document.getElementById('sld_census'),
        legendEl: document.getElementById('pop_legend'),
        legendFallback: 'Population',
        popupBuilder: function(feature, state, formatValue){
            var totalVal = Number(feature.properties[totalPopCol] || 0);
            var html = '<b>County:</b> '+(feature.properties.county_fips||'')+'<br>'+
                       '<b>Total Population:</b> '+Math.round(totalVal).toLocaleString();
            if (state.key !== totalPopCol) {
                var opt = popGroupOptions.filter(function(o){ return o.key === state.key; })[0];
                html += '<br><b>'+(opt?opt.label:state.key)+':</b> '+formatValue(Number(feature.properties[state.key]||0));
            }
            return html;
        }
    });
    var popLayer = popChoropleth.layer.addTo(window.map);
    var updatePopulation = popChoropleth.update;

    var religionChoropleth = createChoroplethLayer({
        data: religionData,
        palette: religionPal,
        defaultKey: 'pct_any_affiliation',
        options: religionGroupOptions,
        selectEl: document.getElementById('religion_group'),
        classesEl: document.getElementById('religion_classes'),
        opacityEl: document.getElementById('sld_religion'),
        legendEl: document.getElementById('religion_legend'),
        legendFallback: 'Religion',
        popupBuilder: function(feature, state, formatValue){
            var opt = religionGroupOptions.filter(function(o){ return o.key === state.key; })[0];
            return '<b>County:</b> '+(feature.properties.county_fips||'')+'<br>'+
                   '<b>'+(opt?opt.label:state.key)+':</b> '+formatValue(Number(feature.properties[state.key]||0));
        }
    });
    var religionLayer = religionChoropleth.layer;

    var crimeChoropleth = createChoroplethLayer({
        data: crimeData,
        palette: crimePal,
        defaultKey: (crimeGroupOptions[0] || {}).key,
        options: crimeGroupOptions,
        selectEl: document.getElementById('crime_group'),
        classesEl: document.getElementById('crime_classes'),
        opacityEl: document.getElementById('sld_crime'),
        legendEl: document.getElementById('crime_legend'),
        legendFallback: 'Crime',
        popupBuilder: function(feature, state, formatValue){
            var opt = crimeGroupOptions.filter(function(o){ return o.key === state.key; })[0];
            var raw = feature.properties[state.key];
            var valueText = isMissing(raw) ? 'No data' : formatValue(Number(raw)) + ' per 100k/yr';
            return '<b>County:</b> '+(feature.properties.county_fips||'')+'<br>'+
                   '<b>'+(opt?opt.label:state.key)+':</b> '+valueText;
        }
    });
    var crimeLayer = crimeChoropleth.layer;

    // Focus-state picker: a purely visual dim mask over every county NOT in the
    // selected state, sitting on top of the choropleth layers so it works
    // regardless of which of them are checked. interactive:false lets clicks
    // pass through it to whatever's underneath, so popups keep working
    // everywhere - this hones in on one place, it never hides or filters data.
    var stateSel = document.getElementById('state_focus');
    var stateNames = countiesData.features
        .map(function(f){ return f.properties.STATE_NAME; })
        .filter(function(s, i, arr){ return s && arr.indexOf(s) === i; })
        .sort();
    var allStatesOpt = document.createElement('option');
    allStatesOpt.value = 'ALL'; allStatesOpt.textContent = 'All States';
    stateSel.appendChild(allStatesOpt);
    stateNames.forEach(function(name){
        var o = document.createElement('option');
        o.value = name; o.textContent = name;
        stateSel.appendChild(o);
    });
    stateSel.value = 'ALL';
    var stateMaskLayer = null;
    stateSel.addEventListener('change', function(){
        if (stateMaskLayer) { window.map.removeLayer(stateMaskLayer); stateMaskLayer = null; }
        if (stateSel.value === 'ALL') return;
        stateMaskLayer = L.geoJson(countiesData, {
            filter: function(f){ return f.properties.STATE_NAME !== stateSel.value; },
            interactive: false,
            style: function(){ return {stroke: false, fillColor: '#1a1a1a', fillOpacity: 0.55}; }
        }).addTo(window.map);
        stateMaskLayer.bringToFront();
    });

    // Camera marker icon: a circle (fixed outline, operator-colored fill) with
    // an optional cone showing the camera's facing direction/field of view -
    // matching the visual convention used by ALPR-mapping sites like
    // dontgetflocked.com. Built as an inline SVG divIcon so it works with
    // marker clustering (which requires L.Marker, not L.circleMarker/Path).
    var iconCache = {};
    function cameraIcon(color, direction) {
        var key = color + '|' + direction;
        if (iconCache[key]) return iconCache[key];
        // viewBox must comfortably contain the cone tip (cx/cy + coneR) or SVG
        // silently clips it at the root <svg> bounds - 34/17/14 leaves a 3px margin.
        var size = 34, cx = 17, cy = 17, r = 5, coneR = 14, halfAngle = 28;
        var wedge = '';
        var dirNum = Number(direction);
        if (direction !== undefined && direction !== null && direction !== '' && !isNaN(dirNum)) {
            function pt(angleDeg){
                var rad = (angleDeg - 90) * Math.PI / 180;
                return [(cx + coneR*Math.cos(rad)).toFixed(1), (cy + coneR*Math.sin(rad)).toFixed(1)];
            }
            var p1 = pt(dirNum - halfAngle), p2 = pt(dirNum + halfAngle);
            wedge = '<path d="M '+cx+','+cy+' L '+p1[0]+','+p1[1]+' L '+p2[0]+','+p2[1]+' Z" fill="'+color+'" fill-opacity="0.35"/>';
        }
        var svg = '<svg width="'+size+'" height="'+size+'" viewBox="0 0 '+size+' '+size+'" xmlns="http://www.w3.org/2000/svg">' + wedge +
            '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="'+color+'" stroke="'+camStroke+'" stroke-width="1.5"/></svg>';
        var icon = L.divIcon({html: svg, className: '', iconSize: [size, size], iconAnchor: [cx, cy]});
        iconCache[key] = icon;
        return icon;
    }

    // create camera layer: clustered markers with FOV cones. Clustering is what
    // makes shipping the full nationwide dataset (100K+ points) viable - only
    // markers actually visible at the current zoom/viewport get a DOM icon.
    var camLayer = L.markerClusterGroup({
        chunkedLoading: true,
        maxClusterRadius: 50,
        disableClusteringAtZoom: 15,
        showCoverageOnHover: false
    });
    camsData.features.forEach(function(f){
        var props = f.properties || {};
        var coords = f.geometry && f.geometry.coordinates;
        if (!coords) return;
        var lon = coords[0], lat = coords[1];
        var op = props.operator || props.source || 'unknown';
        var color = opColors[op] || '#3388ff';
        var dir = props['camera:direction'] || props['direction'] || props['camera:orientation'];
        // operator and surveillance:type/camera:type are populated often enough to
        // always show (with an explicit "(unknown)" fallback for operator, since
        // that's also the fallback used for its marker color); source is filled
        // on well under 1% of records in the raw OSM data, so showing it
        // unconditionally just reads as a blank line on almost every popup.
        var osmLink = (props.osm_id) ? 'https://www.openstreetmap.org/'+(props.osm_type||'node')+'/'+props.osm_id : null;
        var popup = '<b>operator:</b> '+(props.operator||'(unknown)')+'<br>'+
                                '<b>surveillance:type:</b> '+(props['surveillance:type']||'')+'<br>'+
                                '<b>camera type/brand:</b> '+(props['camera:type']||props['camera:brand']||'')+'<br>'+
                                (dir ? '<b>direction:</b> '+dir+'&deg;<br>' : '') +
                                (props.source ? '<b>source:</b> '+props.source+'<br>' : '') +
                                '<b>county FIPS:</b> '+(props.county_fips||'') +
                                (osmLink ? '<br><a href="'+osmLink+'" target="_blank" rel="noopener">View on OpenStreetMap</a>' : '');
        var marker = L.marker([lat, lon], {icon: cameraIcon(color, dir)}).bindPopup(popup);
        camLayer.addLayer(marker);
    });
    camLayer.addTo(window.map);

    // zoom control: bottom-right (so it never overlaps the left panel), with an
    // eye-icon toggle to hide/show it entirely.
    var zoomVisible = true;
    var zoomCtl = L.control.zoom({position:'bottomright'}).addTo(window.map);
    var EyeControl = L.Control.extend({
        options: {position: 'bottomright'},
        onAdd: function(){
            var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control cam-eye-control');
            div.innerHTML = '<a href="#" title="Show/hide zoom controls">&#128065;</a>';
            L.DomEvent.disableClickPropagation(div);
            L.DomEvent.on(div, 'click', function(e){
                L.DomEvent.preventDefault(e);
                if (zoomVisible) { window.map.removeControl(zoomCtl); zoomVisible = false; }
                else { zoomCtl.addTo(window.map); zoomVisible = true; }
            });
            return div;
        }
    });
    new EyeControl().addTo(window.map);

    // wire up controls. Classes/opacity sliders for Population and Religion are
    // already wired inside createChoroplethLayer - only the on/off checkboxes
    // (which add/remove the whole layer) and cameras (a different layer type)
    // need wiring here.
    document.getElementById('sld_cameras').addEventListener('input', function(){
        var v = Number(document.getElementById('sld_cameras').value);
        camLayer.eachLayer(function(l){ if (l.setOpacity) l.setOpacity(v); });
    });
    document.getElementById('chk_census').addEventListener('change', function(e){ if (e.target.checked) window.map.addLayer(popLayer); else window.map.removeLayer(popLayer); });
    document.getElementById('chk_religion').addEventListener('change', function(e){ if (e.target.checked) window.map.addLayer(religionLayer); else window.map.removeLayer(religionLayer); });
    document.getElementById('chk_crime').addEventListener('change', function(e){ if (e.target.checked) window.map.addLayer(crimeLayer); else window.map.removeLayer(crimeLayer); });
    document.getElementById('chk_cameras').addEventListener('change', function(e){ if (e.target.checked) window.map.addLayer(camLayer); else window.map.removeLayer(camLayer); });
    document.getElementById('btn_collapse').addEventListener('click', function(){
        var panel = document.getElementById('leftpanel');
        var collapsed = panel.classList.toggle('collapsed');
        this.innerHTML = collapsed ? '&#9654;' : '&#9664;';
    });

    // init
    updatePopulation();
    religionChoropleth.update();
    crimeChoropleth.update();
    var sampleEl = document.getElementById('sample_meta');
    if (sampleEl) {
        sampleEl.innerHTML = camerasSampled
            ? '<em>Showing ' + camerasShown.toLocaleString() + ' of ' + camerasTotal.toLocaleString() + ' cameras (sampled for performance)</em>'
            : '<em>' + camerasShown.toLocaleString() + ' cameras</em>';
    }
    }

    // fetch all four datasets in parallel and initialize the map rendering
    try {
        Promise.all([
            fetch('checkpoint_counties.json').then(function(r){ return r.json(); }),
            fetch('checkpoint_religion.json').then(function(r){ return r.json(); })
                .catch(function(e){ console.error('Failed to load religion JSON', e); return {type:'FeatureCollection', features:[]}; }),
            fetch('checkpoint_crime.json').then(function(r){ return r.json(); })
                .catch(function(e){ console.error('Failed to load crime JSON', e); return {type:'FeatureCollection', features:[]}; }),
            fetch('checkpoint_cameras.json').then(function(r){ return r.json(); })
                .catch(function(e){ console.error('Failed to load cameras JSON', e); return {type:'FeatureCollection', features:[]}; })
        ]).then(function(results){
            initWithData(results[0], results[1], results[2], results[3]);
        }).catch(function(e){ console.error('Failed to load counties JSON', e); });
    } catch(e) { console.error(e); }

    })();
    </script>
    """
    # write the large client JS out to a separate file and include it by reference
    js_path = out_dir / 'checkpoint_map.js'
    try:
        # strip the outer <script> tags if present
        js_text = js
        if js_text.strip().startswith('<script>'):
            js_text = js_text.strip()[8:]
        if js_text.strip().endswith('</script>'):
            js_text = js_text.strip()[:-9]
        js_path.write_text(js_text, encoding='utf-8')
        m.get_root().html.add_child(Element(
            "<script src='https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js'></script>"
            "<script src='checkpoint_map.js'></script>"
        ))
    except Exception:
        # fallback: inline (may risk large template compile)
        m.get_root().html.add_child(Element(js))

    m.save(str(out_html))
    print('Wrote checkpoint map to', out_html)


if __name__ == '__main__':
    main()
