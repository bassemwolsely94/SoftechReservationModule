"""
scripts/ci/refresh_timings.py — rebuild test_timings.json from backend CI logs.

GitHub stamps every log line with a time, and the suite runs with --verbosity 2 (one line per test,
printed when the test ends), so a test's time is the gap since the line before it. Pass the log of
every backend shard of one run; modules are summed across them.

    gh run view <run-id> --log > ci.log
    python scripts/ci/refresh_timings.py ci.log
"""
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

STAMP = re.compile(r'(\d{4}-\d\d-\d\dT[\d:.]+)Z (.*)')
TEST = re.compile(r'\w+ \(([\w.]+)\) \.\.\. ')


def main(paths):
    seconds = collections.Counter()
    for path in paths:
        last = {}                                  # per job: the stamp of the previous test line
        for line in open(path, encoding='utf-8', errors='replace'):
            m = STAMP.search(line)
            if not m:
                continue
            job = line.split('\t', 1)[0]
            when = dt.datetime.fromisoformat(m.group(1)[:26])
            text = m.group(2)
            if text.startswith('System check identified'):
                last[job] = when
                continue
            t = TEST.match(text)
            if t and job in last:
                module = '.'.join(t.group(1).split('.')[:-2])
                seconds[module] += (when - last[job]).total_seconds()
                last[job] = when
    if not seconds:
        sys.exit('no test lines found — was the log from a --verbosity 2 backend run?')
    out = Path(__file__).with_name('test_timings.json')
    out.write_text(json.dumps({k: round(v, 1) for k, v in sorted(seconds.items())}, indent=0) + '\n',
                   encoding='utf-8')
    print(f'{len(seconds)} modules, {sum(seconds.values()) / 60:.1f} min -> {out}')


if __name__ == '__main__':
    main(sys.argv[1:])
