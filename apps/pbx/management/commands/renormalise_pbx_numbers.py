"""
python manage.py renormalise_pbx_numbers            # dry run: what would change
python manage.py renormalise_pbx_numbers --commit   # recompute + relink

Recomputes CdrCall.customer_number / phone_key / line_prefix for every stored call from its raw
src / dst / channel / dstchannel with the Egyptian national-number rules (apps/pbx/cdr.py), then
re-resolves each call's PIC, and re-keys pic_analytics PhoneLabel rows to the new phone_key.
Idempotent; touches only our own tables (never SOFTECH).
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Re-normalise stored PBX call numbers (Egyptian national form) and relink PICs'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true', help='write the changes (default: dry run)')

    def handle(self, *args, **opts):
        from apps.pbx import cdr
        from apps.pbx.models import CdrCall

        commit = opts['commit']
        gateways, gw_meta = cdr._gateway_registry()
        resolver = cdr.PicResolver()
        before, after = Counter(), Counter()
        changed = total = 0
        batch = []
        fields = ('id', 'src', 'dst', 'channel', 'dstchannel', 'dcontext', 'customer_number', 'phone_key',
                  'line_prefix', 'call_at', 'pic', 'pic_match', 'shared_pics', 'customer_id')
        for (cid, src, dst, ch, dch, dctx, num, key, lp, call_at, pic, match, shared,
             cust) in CdrCall.objects.values_list(*fields).iterator(chunk_size=5000):
            total += 1
            before[match] += 1
            f = cdr.classify({'src': src, 'dst': dst, 'channel': ch, 'dstchannel': dch, 'dcontext': dctx},
                             gateways, gw_meta)
            if f is None:                      # not a customer call any more — leave untouched
                after[match] += 1
                continue
            nnum, nkey, nlp = f['customer_number'], f['phone_key'], f['line_prefix']
            npic, ncust, nmatch, nshared = resolver.resolve(nkey, timezone.localtime(call_at).date())
            after[nmatch] += 1
            if (nnum, nkey, nlp, npic, nmatch, nshared, ncust) != (num, key, lp, pic, match, shared, cust):
                changed += 1
                if commit:
                    batch.append(CdrCall(id=cid, customer_number=nnum, phone_key=nkey, line_prefix=nlp,
                                         pic=npic, pic_match=nmatch, shared_pics=nshared, customer_id=ncust))
            if commit and len(batch) >= 2000:
                self._save(batch)
                batch = []
        if commit and batch:
            self._save(batch)
        labels = self._relabel(commit)

        verb = 'changed' if commit else 'would change'
        self.stdout.write(f'{total} calls; {verb} {changed}; phone labels re-keyed {labels}')
        for m in sorted(set(before) | set(after)):
            self.stdout.write(f'  pic_match {m:18s} before {before[m]:8d}  after {after[m]:8d}')
        if not commit:
            self.stdout.write('dry run — pass --commit to write')

    @staticmethod
    def _save(batch):
        from apps.pbx.models import CdrCall
        CdrCall.objects.bulk_update(
            batch, ['customer_number', 'phone_key', 'line_prefix', 'pic', 'pic_match', 'shared_pics', 'customer'])

    def _relabel(self, commit):
        """PhoneLabel keys follow the new phone_key (a label on '1000000010' -> '01000000010').
        When several labels collapse to one key the newest wins; the dropped ones are reported."""
        from collections import defaultdict
        from apps.pbx.cdr import phone_key
        from apps.pic_analytics.models import PhoneLabel
        groups = defaultdict(list)
        for pl in PhoneLabel.objects.order_by('created_at', 'pk'):
            groups[phone_key(pl.phone_key) or pl.phone_key].append(pl)
        moved = 0
        with transaction.atomic():
            for nk, pls in groups.items():
                keep, drop = pls[-1], pls[:-1]
                for d in drop:
                    self.stdout.write(f'  label collision on {nk}: dropping older label {d.pk} '
                                      f'({d.label}, key {d.phone_key}); keeping {keep.pk} ({keep.label})')
                if keep.phone_key != nk:
                    moved += 1
                if commit:
                    for d in drop:
                        d.delete()
                    if keep.phone_key != nk:
                        keep.phone_key = nk
                        keep.save(update_fields=['phone_key'])
        return moved
