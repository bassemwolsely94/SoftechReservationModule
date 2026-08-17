"""
InsightEngine (doc 18) — run the rule catalog for a period, persist an auditable
run + findings, and render a deterministic bilingual (AR/EN) narrative.
"""
from decimal import Decimal
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.insights.rules import RULES, Ctx, rule_domain


def period_bounds(period_type, ref_date):
    """Rolling windows ending on ref_date. Prev period = equal window just before.
    'mtd' (month-to-date) runs from the 1st of ref_date's month through ref_date."""
    if period_type == 'day':
        return ref_date, ref_date
    if period_type == 'week':
        return ref_date - timedelta(days=6), ref_date
    if period_type == 'mtd':
        return ref_date.replace(day=1), ref_date
    return ref_date - timedelta(days=29), ref_date   # month ≈ 30 days


class InsightEngine:

    @classmethod
    def ensure_rules(cls):
        """Create missing rules from the RULES catalog. For existing rows keep the
        owner-tuned threshold/enabled/periods, but REFRESH the display metadata
        (name_ar/name_en/category/severity) so code-side renames reach the DB."""
        from apps.insights.models import InsightRule
        for code, (fn, ar, en, cat, sev, thr, periods) in RULES.items():
            obj, created = InsightRule.objects.get_or_create(
                code=code, defaults=dict(
                    name_ar=ar, name_en=en, category=cat, severity=sev,
                    threshold=(Decimal(str(thr)) if thr is not None else None),
                    periods=periods))
            if not created:
                changed = [f for f, new in
                           (('name_ar', ar), ('name_en', en), ('category', cat), ('severity', sev))
                           if getattr(obj, f) != new]
                if changed:
                    for f, new in (('name_ar', ar), ('name_en', en), ('category', cat), ('severity', sev)):
                        setattr(obj, f, new)
                    obj.save(update_fields=changed)

    @classmethod
    @transaction.atomic
    def run(cls, period_type='day', ref_date=None, start=None, end=None, domain='sales'):
        """Generate one report for a period + DOMAIN ('sales' or 'purchasing'). Pass explicit
        start/end for a custom range (validated by the caller/view); else a rolling window ends
        on ref_date. Only the rules belonging to `domain` run."""
        from apps.insights.models import InsightRule, InsightRun, InsightFinding
        cls.ensure_rules()
        if start and end:
            if end < start:
                start, end = end, start
        else:
            ref_date = ref_date or (timezone.localdate() - timedelta(days=1))  # yesterday (complete)
            start, end = period_bounds(period_type, ref_date)
        ctx = Ctx(period_type, start, end)

        rules = {r.code: r for r in InsightRule.objects.all()}
        # MTD is a month-shaped period → it runs whatever the 'month' period enables.
        gate = 'month' if period_type == 'mtd' else period_type
        findings = []
        for code, (fn, *_rest) in RULES.items():
            if rule_domain(code) != domain:
                continue
            cfg = rules.get(code)
            if not cfg or not cfg.runs_for(gate):
                continue
            try:
                findings.extend(fn(ctx, cfg.threshold))
            except Exception as exc:   # a broken rule must not sink the whole report
                import logging
                logging.getLogger('elrezeiky').exception('insight rule %s failed: %s', code, exc)

        # Idempotent: regenerating a (period, domain) replaces its previous run.
        InsightRun.objects.filter(period_type=period_type, period_start=start, domain=domain).delete()
        run = InsightRun.objects.create(
            domain=domain, period_type=period_type, period_start=start, period_end=end,
            findings_count=len(findings))
        objs = [InsightFinding(
            run=run, rule_code=f['rule_code'], category=f['category'], severity=f['severity'],
            scope_type=f.get('scope_type', ''), scope_key=f.get('scope_key', '') or '',
            scope_label=f.get('scope_label', '') or '', value=f.get('value'),
            baseline=f.get('baseline'), threshold=f.get('threshold'),
            message_ar=f['message_ar'], message_en=f['message_en']) for f in findings]
        InsightFinding.objects.bulk_create(objs)

        run.narrative_ar = cls.render(ctx, findings, 'ar', domain=domain)
        run.narrative_en = cls.render(ctx, findings, 'en', domain=domain)
        run.save(update_fields=['narrative_ar', 'narrative_en'])
        return run

    # ── renderer (deterministic, bilingual) ─────────────────────────────────────
    _SEV_ORDER = {'critical': 0, 'warning': 1, 'info': 2}
    _CAT_AR = {'coverage': '🧭 تغطية البيانات', 'volume': '📊 حجم المبيعات',
               'mix': '🧴 مزيج المنتجات', 'discount': '🏷️ الخصومات',
               'comparison': '📈 مقارنات', 'highlight': '🏆 إنجازات'}
    _CAT_EN = {'coverage': '🧭 Data coverage', 'volume': '📊 Sales volume',
               'mix': '🧴 Product mix', 'discount': '🏷️ Discounts',
               'comparison': '📈 Comparisons', 'highlight': '🏆 Highlights'}
    _PERIOD_AR = {'day': 'اليومي', 'week': 'الأسبوعي', 'month': 'الشهري', 'mtd': 'الشهر حتى تاريخه'}
    _PERIOD_EN = {'day': 'Daily', 'week': 'Weekly', 'month': 'Monthly', 'mtd': 'Month-to-date'}
    # phrase for the "vs previous" comparison, per period
    _PREV_AR = {'mtd': 'عن نفس الفترة من الشهر السابق'}
    _PREV_EN = {'mtd': 'vs same period last month'}

    @classmethod
    def render_for_branch(cls, run, branch_id, lang):
        """Re-render a stored run filtered to one branch's findings. None if nothing for it."""
        from apps.branches.models import Branch
        b = Branch.objects.filter(pk=branch_id).first()
        if not b:
            return None
        code = b.code or b.softech_branch_id
        fs = [dict(rule_code=f.rule_code, category=f.category, severity=f.severity,
                   scope_type=f.scope_type, scope_key=f.scope_key, scope_label=f.scope_label,
                   value=f.value, baseline=f.baseline, threshold=f.threshold,
                   message_ar=f.message_ar, message_en=f.message_en)
              for f in run.findings.filter(scope_key=code)]
        if not fs:
            return None
        nm = b.name_ar or b.name
        head = (f'📋 تقرير {nm} — {run.period_start} إلى {run.period_end}' if lang == 'ar'
                else f'📋 {nm} report — {run.period_start} to {run.period_end}')
        key = 'message_ar' if lang == 'ar' else 'message_en'
        cats = cls._CAT_AR if lang == 'ar' else cls._CAT_EN
        lines = [head, '']
        by_cat = {}
        for f in fs:
            by_cat.setdefault(f['category'], []).append(f)
        for cat in ['coverage', 'volume', 'mix', 'discount', 'comparison', 'highlight']:
            if cat in by_cat:
                lines.append(cats.get(cat, cat))
                for f in sorted(by_cat[cat], key=lambda x: cls._SEV_ORDER.get(x['severity'], 3)):
                    lines.append('• ' + f[key])
                lines.append('')
        return '\n'.join(lines).strip()

    @classmethod
    def render_for_salesperson(cls, run, usercode, lang):
        """Re-render a stored run filtered to one salesperson's findings (standings, over-
        discount, basket, etc.) — for rep-level (WhatsApp) reports. None if nothing for them."""
        code = str(usercode)
        fs = [dict(rule_code=f.rule_code, category=f.category, severity=f.severity,
                   scope_type=f.scope_type, scope_key=f.scope_key, scope_label=f.scope_label,
                   value=f.value, baseline=f.baseline, threshold=f.threshold,
                   message_ar=f.message_ar, message_en=f.message_en)
              for f in run.findings.filter(scope_type='salesperson', scope_key=code)]
        if not fs:
            return None
        from apps.users.models import ERPUser
        name = (ERPUser.objects.filter(username=code).exclude(user_id='')
                .values_list('user_id', flat=True).first()) or code
        head = (f'📋 تقرير مسئول البيع {name} — {run.period_start} إلى {run.period_end}' if lang == 'ar'
                else f'📋 Salesperson {name} report — {run.period_start} to {run.period_end}')
        key = 'message_ar' if lang == 'ar' else 'message_en'
        cats = cls._CAT_AR if lang == 'ar' else cls._CAT_EN
        lines = [head, '']
        by_cat = {}
        for f in fs:
            by_cat.setdefault(f['category'], []).append(f)
        for cat in ['coverage', 'volume', 'mix', 'discount', 'comparison', 'highlight']:
            if cat in by_cat:
                lines.append(cats.get(cat, cat))
                for f in sorted(by_cat[cat], key=lambda x: cls._SEV_ORDER.get(x['severity'], 3)):
                    lines.append('• ' + f[key])
                lines.append('')
        return '\n'.join(lines).strip()

    @classmethod
    def render(cls, ctx, findings, lang, domain='sales'):
        """Concise CHAIN BOARD report: headline + Top-5 attention + highlights/rankings +
        a compact findings summary. Full per-branch detail lives in render_for_branch.
        Purchasing reports get a purchasing headline instead of the net-sales one."""
        from collections import Counter
        ar = lang == 'ar'
        key = 'message_ar' if ar else 'message_en'
        f2 = lambda n: f'{float(n or 0):,.0f}'
        L = []
        if domain == 'purchasing':
            if ar:
                L.append(f'📦 تقرير المشتريات والتموين {cls._PERIOD_AR.get(ctx.period_type,"")} — {ctx.start} إلى {ctx.end}')
            else:
                L.append(f'📦 Purchasing & replenishment report {cls._PERIOD_EN.get(ctx.period_type,"")} — {ctx.start} to {ctx.end}')
        else:
            r = ctx.resolver
            cur = r.resolve('net_revenue', branch_ids=ctx.branch_ids, start=ctx.start, end=ctx.end)
            prev = r.resolve('net_revenue', branch_ids=ctx.branch_ids, start=ctx.prev_start, end=ctx.prev_end)
            delta = ((cur - prev) / prev * 100) if prev else Decimal('0')
            arrow = '▲' if delta >= 0 else '▼'
            prev_ar = cls._PREV_AR.get(ctx.period_type, 'عن الفترة السابقة')
            prev_en = cls._PREV_EN.get(ctx.period_type, f'vs previous {ctx.period_type}')
            if ar:
                L.append(f'📋 التقرير السردي {cls._PERIOD_AR.get(ctx.period_type,"")} — {ctx.start} إلى {ctx.end}')
                L.append(f'إجمالى صافي المبيعات: {f2(cur)} ج.م ({arrow} {abs(float(delta)):.0f}% {prev_ar}).')
            else:
                L.append(f'📋 {cls._PERIOD_EN.get(ctx.period_type,"")} board report — {ctx.start} to {ctx.end}')
                L.append(f'Total net sales: {f2(cur)} EGP ({arrow} {abs(float(delta)):.0f}% {prev_en}).')

        # ① Top-5 attention — most severe first, then largest magnitude
        attention = [f for f in findings if f['severity'] in ('critical', 'warning')]
        attention.sort(key=lambda x: (cls._SEV_ORDER.get(x['severity'], 3), -abs(float(x.get('value') or 0))))
        if attention:
            L.append('')
            L.append('⚠️ أهم النقاط التي تحتاج انتباه:' if ar else '⚠️ Top items to act on:')
            for i, f in enumerate(attention[:5], 1):
                L.append(f'{i}. ' + f[key])

        # ② Highlights & rankings (positive/comparative)
        highlights = [f for f in findings if f['category'] == 'highlight']
        if highlights:
            L.append('')
            L.append('🏆 إنجازات ومقارنات:' if ar else '🏆 Highlights & rankings:')
            for f in highlights:
                L.append('• ' + f[key])

        # ③ Compact findings summary (counts per rule) — detail goes to branch reports.
        #   Exclude pure per-branch info detail (e.g. branch standings, customer mix) — those
        #   belong in each branch's own report, not the chain board summary.
        nonhi = [f for f in findings if f['category'] != 'highlight'
                 and not (f.get('severity') == 'info' and f.get('scope_type') in ('branch', 'salesperson'))]
        if nonhi:
            labels = {code: (v[1] if ar else v[2]) for code, v in RULES.items()}
            parts = [f'{labels.get(code, code)}: {n}' for code, n in Counter(f['rule_code'] for f in nonhi).most_common()]
            L.append('')
            L.append(('📊 ملخص الملاحظات — ' if ar else '📊 Findings summary — ') + ' · '.join(parts))
            L.append('التفاصيل الكاملة لكل فرع فى تقرير الفرع.' if ar else 'Full per-branch detail in each branch report.')
        elif not attention and not highlights:
            L.append('لا توجد ملاحظات لافتة. ✅' if ar else 'No notable findings. ✅')
        return '\n'.join(L)
