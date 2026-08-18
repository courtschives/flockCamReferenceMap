from pathlib import Path

def get_credentials_path():
    # Credentials live in repo root file `credentials.txt`
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / 'credentials.txt'

def _load_credentials():
    p = get_credentials_path()
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out

_CREDS = None

def get_credential(name):
    global _CREDS
    if _CREDS is None:
        _CREDS = _load_credentials()
    return _CREDS.get(name)
