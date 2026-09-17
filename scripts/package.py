"""Build a reproducible AI-only source archive; secrets and local state are never included."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    'main.py', 'requirements.txt', 'requirements-dev.txt', 'pytest.ini',
    'Dockerfile', '.dockerignore', '.gitignore', '.env.example',
    'compose.yaml', 'compose.demo.yaml', 'compose.test.yaml', 'README.md',
)


def package(root=ROOT):
    root = root.resolve()
    sources = [root / name for name in ROOT_FILES]
    sources += sorted((root / 'app').rglob('*.py'))
    sources += sorted((root / 'app/data/fixtures').glob('*.json'))
    sources += sorted((root / 'scripts').glob('*.py'))
    sources += sorted((root / 'docs').rglob('*.md'))
    sources += sorted((root / 'ci').glob('*.yml'))
    sources += [root / 'data/financial_decisions.jsonl']
    payload = {}
    for path in sources:
        path.resolve().relative_to(root)  # reject links outside the service
        payload[path.relative_to(root).as_posix()] = path.read_bytes()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    payload['MANIFEST.sha256.json'] = json.dumps(manifest, indent=2, sort_keys=True).encode()
    target = root / 'dist/moerpy-ai-service-source.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(payload.items()):
            entry = zipfile.ZipInfo(name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{digest}  {target.name}\n', encoding='utf-8')
    return target, len(manifest), digest


if __name__ == '__main__':
    target, count, digest = package()
    print(json.dumps({'archive': str(target), 'files': count, 'sha256': digest}))
