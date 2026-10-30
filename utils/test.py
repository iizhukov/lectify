#!/usr/bin/env python3
"""Generate the project and run each test suite in its own Python process."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def discover(root):
    suites = []
    excluded = {'generated', '.venv', 'venv', 'env', 'node_modules', '__pycache__', '.git'}
    for category in ('utils', 'services', 'plugins'):
        for directory, children, _ in os.walk(root / category):
            children[:] = [name for name in children if name not in excluded]
            if 'tests' not in children:
                continue
            tests = Path(directory) / 'tests'
            if any(tests.rglob('test_*.py')) or any(tests.rglob('*_test.py')):
                suites.append(tests.parent)
            children.remove('tests')
    return sorted(set(suites), key=lambda path: (path != root / 'utils/codegen', str(path)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', action='append', default=[], help='Repository-relative suite path; repeatable')
    parser.add_argument('--no-generate', action='store_true', help='Use existing generated service dependencies')
    parser.add_argument('--list', action='store_true', help='List suites without executing commands')
    args = parser.parse_args(argv)
    suites = discover(ROOT)
    if args.suite:
        selected = {(ROOT / name).resolve() for name in args.suite}
        missing = selected - set(suites)
        if missing:
            parser.error('Unknown test suite: ' + ', '.join(str(path) for path in sorted(missing)))
        suites = [suite for suite in suites if suite in selected]
    if args.list:
        for suite in suites:
            print(suite.relative_to(ROOT))
        return 0
    if not suites:
        parser.error('No test suites discovered')
    environment = dict(os.environ, LECTIFY_ROOT=str(ROOT))
    if not args.no_generate:
        result = subprocess.run(
            [sys.executable, str(ROOT / 'utils/codegen/src/cli.py'), 'project'],
            cwd=ROOT, env=environment,
        )
        if result.returncode:
            return result.returncode
    failed = []
    for suite in suites:
        name = str(suite.relative_to(ROOT))
        print(f'Running {name}', flush=True)
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests', '--import-mode=importlib', '-q'],
            cwd=suite, env=environment,
        )
        if result.returncode:
            failed.append((name, result.returncode))
    for name, code in failed:
        print(f'FAILED {name} (exit {code})', file=sys.stderr)
    print(f'Suites: {len(suites)}, passed: {len(suites) - len(failed)}, failed: {len(failed)}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
