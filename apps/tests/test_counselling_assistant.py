"""Project 4 — staff drug assistant: safety first, verified vs unverified, drafts never to counter staff."""
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.composition.alternatives import unverified_alternatives_for
from apps.composition.models import ItemMoleculeIndex
from apps.counselling import services

from .factories import make_branch, make_branch2, make_item, make_user

_aicode = [5000]
ON = dict(DRUG_ASSISTANT_ENABLED=True, COUNSELLING_CONTENT_ENABLED=True)


def _idx(item, molecule, value, source='approved', form='TABLET'):
    _aicode[0] += 1
    return ItemMoleculeIndex.objects.create(
        item=item, item_softech_id=item.softech_id, item_name=item.name, aicode=_aicode[0],
        molecule=molecule, strength_value=Decimal(str(value)), strength_unit='MG', dosage_form=form,
        source=source)


def _url(item, branch=None):
    return f'/api/counselling/assistant/{item.pk}/' + (f'?branch={branch.pk}' if branch else '')


@override_settings(**ON)
class AssistantTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.ph, self.ph_c = make_user('ph_as', role='pharmacist', branch=self.branch)
        _, self.sp, self.sp_c = make_user('sp_as', role='salesperson', branch=self.branch)
        self.a = make_item('CONCOR 5', 'AS001')

    @override_settings(DRUG_ASSISTANT_ENABLED=False)
    def test_assistant_404_when_switch_off(self):
        self.assertEqual(self.sp_c.get(_url(self.a)).status_code, 404)

    def test_blocked_item_flags_first(self):
        self.a.item_archive = True
        self.a.save()
        r = self.sp_c.get(_url(self.a))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['blocked'])
        self.assertEqual(r.data['safety'][0]['severity'], 'block')
        self.assertEqual(list(r.data)[:3], ['item_id', 'safety', 'blocked'])

    def test_verified_and_unverified_split(self):
        b, c = make_item('BISOCOR 5', 'AS002'), make_item('BISOLOL 5', 'AS003')
        _idx(self.a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 5); _idx(c, 'BISOPROLOL', 5, source='parsed')
        r = self.sp_c.get(_url(self.a)).data
        self.assertEqual([x['softech_id'] for x in r['alternatives']['same']], ['AS002'])
        self.assertEqual([x['softech_id'] for x in r['suggestions']], ['AS003'])
        self.assertTrue(r['suggestions'][0]['unverified'])
        self.assertTrue(r['molecules_verified'])

    def test_unverified_item_gets_only_suggestions(self):
        b = make_item('BISOCOR 5', 'AS004')
        _idx(self.a, 'BISOPROLOL', 5, source='parsed'); _idx(b, 'BISOPROLOL', 5)
        r = self.sp_c.get(_url(self.a)).data
        self.assertFalse(r['alternatives']['verified'])
        self.assertEqual([x['softech_id'] for x in r['suggestions']], ['AS004'])
        self.assertFalse(r['molecules'][0]['verified'])

    def test_unverified_excludes_blocked_items(self):
        b = make_item('BISO ARCH', 'AS005')
        b.item_archive = True
        b.save()
        _idx(self.a, 'BISOPROLOL', 5, source='parsed'); _idx(b, 'BISOPROLOL', 5, source='parsed')
        self.assertEqual(unverified_alternatives_for(self.a.pk)['items'], [])

    def test_unverified_builds_stock_once(self):
        """Deferred minor: verified matches are only excluded, never built (stock / thumbs) first."""
        from unittest import mock
        b, c = make_item('BISOCOR 5', 'AS007'), make_item('BISOLOL 5', 'AS008')
        _idx(self.a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 5); _idx(c, 'BISOPROLOL', 5, source='parsed')
        with mock.patch('apps.composition.alternatives.network_stock', return_value={}) as ns:
            rows = unverified_alternatives_for(self.a.pk)['items']
        self.assertEqual([r['softech_id'] for r in rows], ['AS008'])
        self.assertEqual(ns.call_count, 1)

    def test_never_reads_name_scientific(self):
        b = make_item('OTHER', 'AS006')
        for it in (self.a, b):
            it.name_scientific = 'BISOPROLOL 5MG'
            it.save()
        self.assertEqual(self.sp_c.get(_url(self.a)).data['suggestions'], [])

    def _draft_only(self):
        services.create_sheet(self.ph, {'dose_ar': 'نص لم يراجع', 'how_to_use_ar': 'x'}, [self.a.pk],
                              source='ai_draft', ai_model='m')

    def test_salesperson_never_sees_draft_text(self):
        self._draft_only()
        r = self.sp_c.get(_url(self.a))
        g = r.data['guidance']
        self.assertEqual((g['status'], g['content']), ('none', None))
        self.assertNotIn('draft', g)
        self.assertNotIn('نص لم يراجع', r.content.decode('utf-8'))

    def test_pharmacist_sees_draft_marked(self):
        self._draft_only()
        g = self.ph_c.get(_url(self.a)).data['guidance']
        self.assertEqual(g['status'], 'draft')
        self.assertEqual((g['draft']['dose_ar'], g['draft']['source']), ('نص لم يراجع', 'ai_draft'))

    def test_approved_guidance_for_everyone(self):
        c = services.create_sheet(self.ph, {'dose_ar': 'قرص', 'how_to_use_ar': 'يبلع'}, [self.a.pk])
        services.approve(self.ph, c)
        g = self.sp_c.get(_url(self.a)).data['guidance']
        self.assertEqual((g['status'], g['content']['dose_ar']), ('approved', 'قرص'))

    def test_branch_outside_scope_refused(self):
        other = make_branch2()
        self.assertEqual(self.sp_c.get(_url(self.a, other)).status_code, 403)
        self.assertEqual(self.sp_c.get(_url(self.a, self.branch)).status_code, 200)

    def test_delivery_role_refused(self):
        _, _, d_c = make_user('dl_as', role='delivery', branch=self.branch)
        self.assertEqual(d_c.get(_url(self.a)).status_code, 403)
