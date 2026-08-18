"""Fetch a full US ALPR camera snapshot by chunking Overpass and save with manifest.

WARNING: This runs many Overpass requests and can be slow or rate-limited.
Use this once to create a canonical snapshot; consider running on a machine
with good connectivity and patience. The script does NOT run automatically
when added; invoke it explicitly.
"""
from pathlib import Path
from datetime import datetime
import json
import argparse

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.pipelines.overpass_cameras import (
    fetch_overpass,
    chunk_bbox_grid,
    load_counties_geojson,
    assign_county_fips,
)
import time
import logging


def setup_logger(log_path):
    logger = logging.getLogger('fetch_snapshot')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    fh.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(fh)
    return logger


def main(out_dir=None, step_deg=1.0, delay=1.0, coarse_step=None):
    repo_root = Path(__file__).resolve().parents[2]
    if out_dir is None:
        out_dir = repo_root / 'data' / 'snapshots'
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    outpath = out_dir / f'cameras_snapshot_{ts}.geojson'
    manifest = out_dir / f'cameras_snapshot_{ts}.manifest.json'
    logpath = out_dir / f'cameras_snapshot_{ts}.log'
    progress_path = out_dir / f'cameras_snapshot_{ts}.progress.json'
    partial_path = out_dir / f'cameras_snapshot_{ts}.partial.json'

    logger = setup_logger(str(logpath))
    logger.info('Starting full camera snapshot')

    # Prepare coarse/fine grid params
    south, west, north, east = 24.0, -125.0, 50.0, -66.0
    if coarse_step is None:
        coarse_step = step_deg * 2.0 if step_deg < 2.0 else step_deg * 2.0
    # CLI can override coarse/fine via args (populated at CLI parse)
    grid_coarse = list(chunk_bbox_grid(south, west, north, east, step_deg=coarse_step))
    total_coarse = len(grid_coarse)

    # resume support: load partial features and processed indexes if present
    processed = set()
    features = []
    if progress_path.exists():
        try:
            pj = json.loads(progress_path.read_text())
            processed = set(tuple(b) for b in pj.get('processed', []))
            logger.info(f'Resuming: {len(processed)} tiles already processed')
        except Exception as e:
            logger.warning(f'Failed to read progress file: {e}')
    if partial_path.exists():
        try:
            pj = json.loads(partial_path.read_text())
            features = pj.get('features', [])
            logger.info(f'Loaded {len(features)} existing features from partial output')
        except Exception as e:
            logger.warning(f'Failed to read partial file: {e}')

    counties = None
    if (repo_root / 'data' / 'tiger_counties.geojson').exists():
        try:
            counties = load_counties_geojson(str(repo_root / 'data' / 'tiger_counties.geojson'))
            logger.info('Loaded counties for FIPS assignment')
        except Exception as e:
            logger.warning(f'Could not load counties: {e}')

    # Two-phase approach: coarse scan to find non-empty tiles, then subdivide
    logger.info(f'Starting coarse scan: {total_coarse} tiles (coarse_step={coarse_step})')
    for cidx, cbbox in enumerate(grid_coarse):
        if tuple(cbbox) in processed:
            continue
        logger.info(f'Coarse tile {cidx+1}/{total_coarse} bbox={cbbox}')
        try:
            c_fc = fetch_overpass(cbbox)
            c_feats = c_fc.get('features', [])
        except Exception as e:
            logger.warning(f'Coarse fetch failed for bbox {cbbox}: {e}')
            c_feats = []
        processed.add(tuple(cbbox))
        # if coarse tile had features, subdivide into fine tiles
        if c_feats:
            logger.info(f'Coarse tile has {len(c_feats)} features; subdividing')
            # subdivide coarse bbox into fine tiles
            fine_grid = list(chunk_bbox_grid(cbbox[0], cbbox[1], cbbox[2], cbbox[3], step_deg=step_deg))
            for fidx, fbbox in enumerate(fine_grid):
                if tuple(fbbox) in processed:
                    continue
                logger.info(f'  Fine tile {fidx+1}/{len(fine_grid)} bbox={fbbox}')
                try:
                    f_fc = fetch_overpass(fbbox)
                    new_feats = f_fc.get('features', [])
                    if new_feats:
                        features.extend(new_feats)
                        logger.info(f'  Got {len(new_feats)} features from fine tile')
                    else:
                        logger.info('  No features in fine tile')
                except Exception as e:
                    logger.warning(f'  Fetch failed for fine bbox {fbbox}: {e}')
                processed.add(tuple(fbbox))
                # write progress periodically
                if len(processed) % 20 == 0:
                    try:
                        partial_path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
                        progress_path.write_text(json.dumps({'processed': [list(p) for p in processed], 'coarse_idx': cidx}))
                        logger.info(f'Wrote progress: {len(features)} features, {len(processed)} processed tiles')
                    except Exception as e:
                        logger.warning(f'Failed to write progress files: {e}')
                time.sleep(delay)
        else:
            logger.info('Coarse tile empty; skipping subdivision')
        # coarse-level write after each coarse tile
        if (cidx + 1) % 5 == 0 or (cidx + 1) == total_coarse:
            try:
                partial_path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
                progress_path.write_text(json.dumps({'processed': [list(p) for p in processed], 'coarse_idx': cidx}))
                logger.info(f'Coarse progress saved: {len(features)} features, {len(processed)} processed tiles')
            except Exception as e:
                logger.warning(f'Failed to write coarse progress files: {e}')

    # assign counties if available
    combined = {'type': 'FeatureCollection', 'features': features}
    if counties is not None:
        try:
            combined = assign_county_fips(combined, counties)
            logger.info('Assigned county_fips to features')
        except Exception as e:
            logger.warning(f'County assignment failed: {e}')

    outp = outpath
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(combined))
    logger.info(f'Wrote final snapshot with {len(combined.get("features", []))} features to {outp}')

    # write manifest
    m = {
        'created_at': ts,
        'source': 'overpass_api_chunked',
        'file': str(outp.relative_to(repo_root)),
        'coarse_tiles_total': total_coarse,
        'tiles_processed': len(processed),
    }
    manifest.write_text(json.dumps(m, indent=2))
    print(f'Wrote snapshot and manifest to {out_dir}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out', help='output directory for snapshot files')
    p.add_argument('--step-deg', type=float, default=1.0)
    p.add_argument('--coarse-step', type=float, default=None, help='coarse grid step in degrees (overrides auto)')
    p.add_argument('--delay', type=float, default=1.0)
    args = p.parse_args()
    # If coarse_step provided, pass it via environment by temporarily monkeypatching
    main(out_dir=args.out, step_deg=args.step_deg, delay=args.delay, coarse_step=args.coarse_step)
