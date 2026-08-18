#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else 'data/snapshots/cameras.geojson'
with open(path, 'r', encoding='utf8') as fh:
    data = json.load(fh)
feats = data.get('features', [])
print('feature_count:', len(feats))
print('\n--- raw first 5 features ---')
for i,f in enumerate(feats[:5]):
    print('Feature', i+1)
    print(json.dumps(f, indent=2, ensure_ascii=False))
