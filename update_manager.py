#!/usr/bin/env python3
"""Football Analyzer software updater.

The application code lives on GitHub. Local user data, config and virtualenv
stay on the Mac. This updater only replaces the application source when the
GitHub main branch has changed; it downloads the exact commit SHA so a cached
branch archive can never leave the Mac on stale source code. It does not refresh football data.
"""
import json, os, shutil, sys, tempfile, urllib.request, zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / 'config.env'
COMMIT_FILE = BASE / '.software_commit'

PROTECTED = {
    'config.env', '.software_commit', 'cache.json', 'odds_cache.json',
    'sofa_cache.json', 'football_analyzer.log', 'football_analyzer.pid',
    'updater.log', 'updater_launchd.log', 'config.local.json',
    'context_cache.json', 'news_cache.json', 'data', 'cache', '.venv',
    '__pycache__', '.DS_Store'
}


def local_config():
    values = {}
    if CONFIG_FILE.exists():
        for raw in CONFIG_FILE.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'FootballAnalyzer-Updater'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def download(url, path):
    req = urllib.request.Request(url, headers={'User-Agent': 'FootballAnalyzer-Updater'})
    with urllib.request.urlopen(req, timeout=90) as r, open(path, 'wb') as f:
        shutil.copyfileobj(r, f)


def copy_tree(src, dst):
    for item in src.iterdir():
        if item.name in PROTECTED:
            continue
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def remote_commit(repo):
    data = get_json(f'https://api.github.com/repos/{repo}/commits/main')
    return data.get('sha', '')


def main():
    cfg = local_config()
    repo = cfg.get('UPDATE_REPO', '').strip() or 'Football-Analyzer-Lads/Football-Analyzer-PRO'
    if '/' not in repo or repo.startswith('http'):
        print('AUTO-UPDATE: UPDATE_REPO non valido.')
        return 0

    try:
        latest_sha = remote_commit(repo)
        if not latest_sha:
            print('AUTO-UPDATE: commit GitHub non disponibile.')
            return 0

        installed_sha = COMMIT_FILE.read_text(encoding='utf-8').strip() if COMMIT_FILE.exists() else ''
        if installed_sha == latest_sha:
            print('AUTO-UPDATE: software già aggiornato.')
            return 0

        print('AUTO-UPDATE: nuova versione del software disponibile...')
        with tempfile.TemporaryDirectory(prefix='fa_update_') as td:
            archive = Path(td) / 'source.zip'
            extract = Path(td) / 'extract'
            backup = Path(td) / 'backup'
            download(f'https://codeload.github.com/{repo}/zip/{latest_sha}', archive)
            extract.mkdir()
            with zipfile.ZipFile(archive) as z:
                z.extractall(extract)

            roots = [p for p in extract.iterdir() if p.name != '__MACOSX']
            source = roots[0] if len(roots) == 1 and roots[0].is_dir() else extract

            # Safety check: never install an archive that does not contain the
            # current application bootstrap/source tree.
            required = [source / 'app.py', source / 'app_source_01.py', source / 'app_source_04.py', source / 'static' / 'app.js']
            if not all(p.exists() for p in required):
                raise RuntimeError('GitHub archive incompleto: file applicazione mancanti')

            backup.mkdir()
            copy_tree(BASE, backup)
            try:
                copy_tree(source, BASE)
                for script in ('start.command', 'install.command'):
                    target = BASE / script
                    if target.exists():
                        target.chmod(target.stat().st_mode | 0o111)
                COMMIT_FILE.write_text(latest_sha + '\n', encoding='utf-8')
            except Exception:
                copy_tree(backup, BASE)
                raise

        print('AUTO-UPDATE: software aggiornato.')
        print('config.env, API key, .venv e dati locali sono stati preservati.')
        return 0
    except Exception as e:
        print(f'AUTO-UPDATE: nessun aggiornamento applicato ({e}).')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())