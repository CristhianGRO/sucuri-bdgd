"""Persistent result index. Source metadata and engine code identify compatible results."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ('network.geojson', 'powerflow.zip', 'report.json')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.state-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(dataset, feeder, crs, analysis='network'):
    dataset = Path(dataset).resolve()
    files = sorted(dataset.glob('*.csv'))
    metadata = dataset / 'source.json'
    if metadata.exists():
        files.append(metadata)
        source = json.loads(metadata.read_text(encoding='utf-8'))
        gdb = Path(source['gdb'])
        files.extend(sorted(p for p in gdb.rglob('*') if p.is_file() and not p.name.lower().endswith('.lock')))
    sources = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    engine = hashlib.sha256()
    for path in sorted((ROOT/'core').glob('*.py')) + [ROOT/'app/controller.py',ROOT/'app/utils.py',ROOT/'web_backend/worker.py',ROOT/'web_backend/result_cache.py',ROOT/'web/tools/export_geojson.py']:
        engine.update(path.read_bytes())
    versions = {}
    for package in ('pandas','numpy','networkx','scipy','pyproj','fiona','shapely'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    value = {'dataset':str(dataset),'feeder':str(feeder),'crs':crs,'analysis':analysis,'sources':sources,'engine':engine.hexdigest(),'python':sys.version,'packages':versions}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def artifact_signature(job):
    return {name: {'size':(job/name).stat().st_size, 'mtime_ns':(job/name).stat().st_mtime_ns} for name in ARTIFACTS}


def find_cached(jobs_root, key):
    try:
        entry = json.loads((Path(jobs_root).parent/'cache'/f'{key}.json').read_text(encoding='utf-8'))
        job_id = entry['id']
        if not re.fullmatch(r'[a-f0-9]{32}', job_id):
            return None
        job = Path(jobs_root)/job_id
        state = json.loads((job/'state.json').read_text(encoding='utf-8'))
        if state.get('status') != 'completed' or state.get('cache_key') != key:
            return None
        if artifact_signature(job) != entry['artifacts']:
            return None
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def publish_cached(jobs_root, key, job_id):
    write_json(Path(jobs_root).parent/'cache'/f'{key}.json', {'id':job_id,'artifacts':artifact_signature(Path(jobs_root)/job_id)})
