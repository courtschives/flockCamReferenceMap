"""Merge the per-state re-extraction (real OSM IDs, 38 of 51 states) with the
original full nationwide snapshot (167,775 cameras, no OSM IDs) so the map
keeps complete coverage while gaining working OSM links wherever available.

13 states (the most populous ones - CA, TX, FL, NY, PA, IL, OH, GA, NC, MI,
VA, WA, CO) couldn't be re-extracted with pyrosm on this machine (a real
memory constraint building an OSM node lookup table, documented in
extract_cameras_per_state.py) - this fills that gap with the original
ID-less data for just those states, rather than losing that coverage.
"""
from pathlib import Path
from datetime import datetime
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# States the per-state re-extraction could not process (see extract_cameras_per_state.py run log).
# 2-digit state FIPS codes.
MISSING_STATE_FIPS = {
    '06',  # California
    '48',  # Texas
    '12',  # Florida
    '36',  # New York
    '42',  # Pennsylvania
    '17',  # Illinois
    '39',  # Ohio
    '13',  # Georgia
    '37',  # North Carolina
    '26',  # Michigan
    '51',  # Virginia
    '53',  # Washington
    '08',  # Colorado
}

OLD_SNAPSHOT = ROOT / 'data' / 'snapshots' / 'cameras_snapshot_20260816T144158Z_osmium.geojson'
NEW_SNAPSHOT = ROOT / 'data' / 'snapshots' / 'cameras_snapshot_20260818T191452Z_perstate_withid.geojson'
SNAP_DIR = ROOT / 'data' / 'snapshots'


def main():
    old_data = json.loads(OLD_SNAPSHOT.read_text(encoding='utf-8'))
    new_data = json.loads(NEW_SNAPSHOT.read_text(encoding='utf-8'))

    fallback_features = []
    skipped_no_fips = 0
    for f in old_data['features']:
        fips = f.get('properties', {}).get('county_fips')
        state_fips = fips[:2] if fips and len(fips) >= 2 else None
        if state_fips is None:
            skipped_no_fips += 1
            continue
        if state_fips in MISSING_STATE_FIPS:
            fallback_features.append(f)

    merged = fallback_features + new_data['features']

    print(f'Old dataset: {len(old_data["features"])} features ({skipped_no_fips} with no county_fips, dropped)')
    print(f'Fallback (from 13 missing states): {len(fallback_features)} features')
    print(f'New per-state (38 states, with OSM IDs): {len(new_data["features"])} features')
    print(f'Merged total: {len(merged)} features')

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_geo = SNAP_DIR / f'cameras_snapshot_{ts}_merged.geojson'
    out_manifest = SNAP_DIR / f'cameras_snapshot_{ts}_merged.manifest.json'
    with open(out_geo, 'w', encoding='utf-8') as fh:
        json.dump({'type': 'FeatureCollection', 'features': merged}, fh)
    with open(out_manifest, 'w', encoding='utf-8') as fh:
        json.dump({
            'created_at': ts,
            'source': 'merged_perstate_plus_fallback',
            'file': str(out_geo.relative_to(ROOT)).replace('\\', '/'),
            'feature_count': len(merged),
            'note': f'{len(new_data["features"])} features from 38-state re-extraction have real osm_id/osm_type; '
                    f'{len(fallback_features)} features from 13 states ({sorted(MISSING_STATE_FIPS)}) are the original '
                    f'extraction and have no osm_id (memory constraint on those states\' PBF files - see '
                    f'extract_cameras_per_state.py docstring)',
        }, fh)
    print(f'Wrote merged snapshot to {out_geo}')


if __name__ == '__main__':
    main()
