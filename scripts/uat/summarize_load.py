"""Turn the run_light_load.ps1 CSVs into markdown tables for docs/uat/light-load.md.

    python scripts/uat/summarize_load.py frontend/test-results-uat/load
"""
import csv
import sys
from pathlib import Path


def stats(path):
    rows = {}
    with open(path, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['Name'] == 'Aggregated' or r['Type'] == '403':
                continue
            rows[f"{r['Type']} {r['Name']}"] = r
    return rows


def forbidden(path):
    with open(path, encoding='utf-8') as fh:
        return {r['Name']: int(r['Request Count']) for r in csv.DictReader(fh) if r['Type'] == '403'}


def aggregated(path):
    with open(path, encoding='utf-8') as fh:
        return next(r for r in csv.DictReader(fh) if r['Name'] == 'Aggregated')


def ms(v):
    return 'n/a' if v in ('', 'N/A') else f'{float(v):,.0f}'


def main(folder):
    folder = Path(folder)
    stages = sorted(folder.glob('load_*u_stats.csv'), key=lambda p: int(p.name.split('_')[1][:-1]))
    data = {p.name.split('_')[1]: stats(p) for p in stages}
    tags = list(data)
    names = sorted({n for d in data.values() for n in d})
    out = []
    head = '| Endpoint | ' + ' | '.join(f'{t} n | {t} fail | {t} p50 | {t} p95 | {t} max' for t in tags) + ' |'
    out += [head, '|---|' + '---:|' * (5 * len(tags))]
    for n in names:
        cells = []
        for t in tags:
            r = data[t].get(n)
            cells += ([r['Request Count'], r['Failure Count'], ms(r['50%']), ms(r['95%']), ms(r['Max Response Time'])]
                      if r else ['–'] * 5)
        out.append(f'| `{n}` | ' + ' | '.join(cells) + ' |')
    out.append('')
    for p in stages:
        a = aggregated(p)
        n, f = int(a['Request Count']), int(a['Failure Count'])
        out.append(f"- **{p.name.split('_')[1]}**: {n} requests, {f} failures ({100 * f / max(n, 1):.2f} %), "
                   f"{float(a['Requests/s']):.2f} req/s, p50 {ms(a['50%'])} ms, p95 {ms(a['95%'])} ms, "
                   f"max {ms(a['Max Response Time'])} ms; 403 (role not allowed, not counted as failure): "
                   f"{sum(forbidden(p).values())} ({', '.join(f'{k} {v}' for k, v in forbidden(p).items()) or 'none'})")
    out.append('')
    last = tags[-1]
    top = sorted(data[last].items(), key=lambda kv: -float(kv[1]['95%'] or 0))[:15]
    out += [f'Slowest 15 by p95 at {last}:', '', '| # | Endpoint | n | p50 | p95 | max |', '|---:|---|---:|---:|---:|---:|']
    for i, (n, r) in enumerate(top, 1):
        out.append(f"| {i} | `{n}` | {r['Request Count']} | {ms(r['50%'])} | {ms(r['95%'])} | {ms(r['Max Response Time'])} |")
    out.append('')
    for p in stages:
        fp = p.with_name(p.name.replace('_stats.csv', '_failures.csv'))
        if fp.exists():
            with open(fp, encoding='utf-8') as fh:
                fails = list(csv.DictReader(fh))
            for r in fails:
                out.append(f"- {p.name.split('_')[1]} failure: {r['Method']} {r['Name']} — {r['Error'][:160]} × {r['Occurrences']}")
    mem = folder / 'memory.csv'
    if mem.exists():
        with open(mem, encoding='utf-8-sig') as fh:
            m = list(csv.DictReader(fh))
        if m:
            for t in tags:
                mt = [r for r in m if r['stage'] == f'load_{t}']
                if mt:
                    out.append(f"- memory {t}: free RAM min {min(float(r['free_gb']) for r in mt)} GB / "
                               f"max {max(float(r['free_gb']) for r in mt)} GB; Postgres working set max "
                               f"{max(float(r['pg_ws_gb']) for r in mt)} GB (private {max(float(r['pg_private_gb']) for r in mt)} GB, "
                               f"{max(int(r['pg_procs']) for r in mt)} processes); runserver max "
                               f"{max((float(r['server_ws_gb']) for r in mt if r['server_ws_gb']), default=0)} GB; {len(mt)} samples")
    print('\n'.join(out))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'frontend/test-results-uat/load')
