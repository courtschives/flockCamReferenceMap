#!/usr/bin/env python3
"""Overpass per-state camera snapshot (test-first)

Usage:
  python overpass_state_snapshot.py --state DE [--test-only]

This script queries Overpass per-state (by ISO3166-2 code like US-DE),
fetching elements with either `surveillance:type=ALPR` or `man_made=surveillance`.
It prints a raw feature count and three sample features (full tags) for verification.

Retry logic with exponential backoff and mirror fallback included.
"""
import argparse
import json
import os
import sys
import time
from typing import List, Dict, Any

import requests

BASE_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def build_query(state_iso2: str) -> str:
    # state_iso2 should be like 'US-DE'
    q = (
        '[out:json][timeout:180];'
        'area["ISO3166-2"="%s"]->.searchArea;'
        '('
        '  node(area.searchArea)["surveillance:type"="ALPR"];'
        '  way(area.searchArea)["surveillance:type"="ALPR"];'
        '  relation(area.searchArea)["surveillance:type"="ALPR"];'
        '  node(area.searchArea)["man_made"="surveillance"];'
        '  way(area.searchArea)["man_made"="surveillance"];'
        '  relation(area.searchArea)["man_made"="surveillance"];'
        ');'
        'out center tags;'
    ) % state_iso2
    return q


def query_overpass(state_iso2: str, retries: int = 3, delay: float = 2.0) -> Dict[str, Any]:
    q = build_query(state_iso2)
    last_exc = None
    for attempt in range(1, retries + 1):
        for base in BASE_URLS:
            try:
                resp = requests.post(base, data=q.encode('utf-8'), headers={"Accept": "application/json"}, timeout=60)
                if resp.status_code != 200:
                    last_exc = RuntimeError(f"HTTP {resp.status_code} from {base}")
                    # If 406/504 treat as retryable
                    time.sleep(delay * attempt)
                    continue
                try:
                    return resp.json()
                except ValueError as e:
                    last_exc = e
                    time.sleep(delay * attempt)
                    continue
            except requests.RequestException as e:
                last_exc = e
                time.sleep(delay * attempt)
                continue
        # if we reach here, we've tried all bases once; exponential backoff before retry
        time.sleep(delay * (2 ** (attempt - 1)))
    raise last_exc or RuntimeError("Overpass query failed after retries")


def elements_to_features(elements: List[Dict[str, Any]], save_props: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    features = []
    for el in elements:
        tags = el.get('tags', {}) or {}
        lat = el.get('lat')
        lon = el.get('lon')
        # ways/relations may have 'center'
        if 'center' in el and isinstance(el['center'], dict):
            lat = el['center'].get('lat')
            lon = el['center'].get('lon')
        if lat is None or lon is None:
            # skip elements without coords
            continue
        matched = {
            'matched_surveillance_type': bool(tags.get('surveillance:type') and tags.get('surveillance:type').upper() == 'ALPR'),
            'matched_man_made': tags.get('man_made') == 'surveillance'
        }
        props = {
            'osm_id': el.get('id'),
            'osm_type': el.get('type'),
            'tags': tags,
            **matched,
        }
        if save_props:
            props.update(save_props)
        feat = {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': props,
        }
        features.append(feat)
    return features


def write_geojson(dst: str, features: List[Dict[str, Any]]):
    coll = {'type': 'FeatureCollection', 'features': features}
    with open(dst, 'w', encoding='utf8') as fh:
        json.dump(coll, fh)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', required=True, help='State code ISO3166-2 (US-DE)')
    p.add_argument('--test-only', action='store_true', help='Run only this state and print samples')
    p.add_argument('--out-dir', default='data/snapshots', help='Output folder for state geojson')
    p.add_argument('--retries', type=int, default=3)
    p.add_argument('--delay', type=float, default=2.0)
    args = p.parse_args()

    state = args.state.upper()
    if not state.startswith('US-'):
        print('State must be ISO3166-2 like US-DE', file=sys.stderr)
        sys.exit(2)

    print('Overpass query for', state)
    q = build_query(state)
    print('Query (truncated):', q[:200].replace('\n',' '))

    try:
        data = query_overpass(state, retries=args.retries, delay=args.delay)
    except Exception as e:
        print('Overpass query failed:', str(e), file=sys.stderr)
        sys.exit(1)

    elements = data.get('elements', [])
    print('Raw elements returned:', len(elements))

    features = elements_to_features(elements, save_props={'state': state})
    print('Converted features with coords:', len(features))

    os.makedirs(args.out_dir, exist_ok=True)
    dst = os.path.join(args.out_dir, f'overpass_state_{state}.geojson')
    write_geojson(dst, features)
    print('Wrote', dst)

    # Print 3 sample features' tag sets
    print('\n--- Sample features (up to 3) ---')
    for i, f in enumerate(features[:3]):
        print(f'Feature {i+1}: osm_type={f["properties"]["osm_type"]} osm_id={f["properties"]["osm_id"]} matched_surveillance_type={f["properties"]["matched_surveillance_type"]} matched_man_made={f["properties"]["matched_man_made"]}')
        print(json.dumps(f['properties']['tags'], indent=2, ensure_ascii=False))

    if args.test_only:
        print('\nTest complete. Do not proceed to other states until you confirm.')


if __name__ == '__main__':
    main()
