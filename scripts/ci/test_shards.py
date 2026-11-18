"""
scripts/ci/test_shards.py — split the backend test suite into N shards of about equal run time.

CI runs each shard on its own runner at the same time (.github/workflows/ci.yml). The test set is
what `manage.py test` itself discovers, so a new test module is always in exactly one shard: a
module missing from test_timings.json gets DEFAULT_SECONDS and is still placed. Placement is
greedy longest-first, so the same inputs always give the same shards.

    python scripts/ci/test_shards.py --shards 6            # JSON matrix for GitHub Actions
    python scripts/ci/test_shards.py --shards 6 --show     # human-readable split

When the shards drift apart in run time, refresh test_timings.json: scripts/ci/refresh_timings.py.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMINGS = Path(__file__).with_name('test_timings.json')
DEFAULT_SECONDS = 5.0


def discovered_modules():
    """Every test module `manage.py test` (no labels) would run, with its test count."""
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    sys.argv = ['manage.py', 'test']          # settings switch to test mode on argv[1] == 'test'
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.test.runner import DiscoverRunner

    counts = {}
    for test in DiscoverRunner(verbosity=0).build_suite([]):
        module = type(test).__module__
        counts[module] = counts.get(module, 0) + 1
    return counts


def split(counts, timings, shards):
    weight = {m: timings.get(m, DEFAULT_SECONDS) for m in counts}
    bins = [{'seconds': 0.0, 'modules': []} for _ in range(shards)]
    for module in sorted(weight, key=lambda m: (-weight[m], m)):
        target = min(bins, key=lambda b: b['seconds'])
        target['modules'].append(module)
        target['seconds'] += weight[module]
    return bins


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--shards', type=int, required=True)
    parser.add_argument('--show', action='store_true')
    args = parser.parse_args()

    counts = discovered_modules()
    timings = json.loads(TIMINGS.read_text(encoding='utf-8'))
    bins = split(counts, timings, args.shards)

    placed = [m for b in bins for m in b['modules']]
    if sorted(placed) != sorted(counts):          # every module exactly once, or the run fails
        sys.exit('test_shards: shards do not cover the discovered test modules exactly once')

    if args.show:
        for i, b in enumerate(bins, 1):
            tests = sum(counts[m] for m in b['modules'])
            print(f'shard {i}: {b["seconds"] / 60:5.1f} min (last CI), {len(b["modules"])} modules, {tests} tests')
        print(f'total: {sum(counts.values())} tests in {len(counts)} modules')
        return
    matrix = [{'shard': i, 'labels': ' '.join(sorted(b['modules']))} for i, b in enumerate(bins, 1)]
    print(json.dumps(matrix))


if __name__ == '__main__':
    main()
