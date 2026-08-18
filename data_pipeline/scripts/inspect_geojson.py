#!/usr/bin/env python3
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'data/snapshots/cameras.geojson'
with open(path, 'r', encoding='utf8') as fh:
    data = json.load(fh)
feats = data.get('features', [])
print('feature_count:', len(feats))
print('\n--- sample features (up to 5) ---')
for i, f in enumerate(feats[:5]):
    props = f.get('properties', {})
    tags = props.get('tags', {})
    print(f'Feature {i+1}: osm_type={props.get("osm_type")} osm_id={props.get("osm_id")}')
    print(json.dumps(tags, indent=2, ensure_ascii=False))
