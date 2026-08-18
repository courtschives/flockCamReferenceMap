from pathlib import Path
import json
p = Path('data/output/census_counties_population.geojson')
if not p.exists():
    print('file missing', p)
    raise SystemExit(1)
with p.open() as f:
    data = json.load(f)
print('features', len(data.get('features', [])))
keys = []
for feat in data.get('features', []):
    props = feat.get('properties', {})
    keys = list(props.keys())
    break
print('sample property keys:', keys[:30])
# look for B01003_001E
found = False
for feat in data.get('features', []):
    v = feat.get('properties', {}).get('B01003_001E')
    if v not in (None, '', 'nan'):
        print('found non-null B01003_001E sample:', v)
        found = True
        break
if not found:
    print('no non-null B01003_001E found')
