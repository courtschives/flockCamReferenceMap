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
    