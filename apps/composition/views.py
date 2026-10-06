"""
Reconciliation API — READ-ONLY in Batch 1.

Exposes the SOFTECH mirror and the parser's review queue so a pharmacist can see
how the dirty ``activeingredients`` master breaks down (dedup groups, combos,
low-confidence rows). Approving candidates and any SOFTECH writeback are a later,
gated phase (Track B) — nothing here mutates SOFTECH or the canonical taxonomy.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Sum, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.chronic.models import IngredientClass
from .models import SoftechIngredientRaw, IngredientParseCandidate, ItemMoleculeIndex
from .serializers import (
    SoftechIngredientRawSerializer,
    IngredientParseCandidateSerializer,
    IngredientClassSerializer,
    ItemMoleculeIndexSerializer,
)
from . import approve as approve_engine


def _can_edit(request):
    """RBAC: catalog/edit gate (admins bypass) — same pattern as catalog tags."""
    p = getattr(request.user, 'staff_profile', None)
    if not (p and p.is_active):
        return False
    if p.role == 'admin':
        return True
    try:
        return p.can_do('catalog', 'edit')
    except Exception:
        return False


def _forbidden():
    return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)


class StandardPagination(PageNumberPagination):
    page_size             = 50
    page_size_query_param = 'page_size'
    max_page_size         = 500


class IngredientClassViewSet(viewsets.ModelViewSet):
    """Pharmacology class taxonomy — for the review UI's class picker.

    Read: any staff. Create/edit: RBAC catalog/edit — pharmacists add missing
    classes themselves (e.g. "Systemic Anti-inflammatory & Anti-edematous Agents").
    Platform-native; a new class has no SOFTECH code until Track B pushes it to
    basic_data(600). Delete is admin-only and blocked while the class is in use.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = IngredientClassSerializer
    pagination_class   = None   # small fixed lookup (~90) — return the full list

    def get_queryset(self):
        qs = IngredientClass.objects.all().order_by('name')
        if self.request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True)
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(name_ar__icontains=q) | Q(key__icontains=q))
        return qs

    def _guard_edit(self, request):
        if not _can_edit(request):
            return _forbidden()
        return None

    @staticmethod
    def _make_key(name):
        from django.utils.text import slugify
        base = (slugify(name) or 'class').replace('-', '_')[:56] or 'class'
        key, n = base, 2
        while IngredientClass.objects.filter(key=key).exists():
            key = f'{base}_{n}'[:60]
            n += 1
        return key

    def create(self, request, *args, **kwargs):
        forbidden = self._guard_edit(request)
        if forbidden:
            return forbidden
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'detail': 'الاسم بالإنجليزية مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        if IngredientClass.objects.filter(name__iexact=name).exists():
            return Response({'detail': 'تصنيف بنفس الاسم موجود'}, status=status.HTTP_400_BAD_REQUEST)
        obj = IngredientClass.objects.create(
            key=(request.data.get('key') or '').strip() or self._make_key(name),
            name=name, name_ar=(request.data.get('name_ar') or '').strip(),
        )
        return Response(IngredientClassSerializer(obj).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        forbidden = self._guard_edit(request)
        if forbidden:
            return forbidden
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        p = getattr(request.user, 'staff_profile', None)
        if not (p and p.role == 'admin'):
            return _forbidden()
        obj = self.get_object()
        in_use = (obj.class_candidates.exists() or obj.ingredients.exists()
                  or obj.item_index.exists())
        if in_use:
            return Response({'detail': 'التصنيف مستخدم — لا يمكن حذفه'}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class SoftechIngredientRawViewSet(viewsets.ReadOnlyModelViewSet):
    """Verbatim SOFTECH activeingredients mirror (the 'before' snapshot)."""
    permission_classes = [IsAuthenticated]
    serializer_class   = SoftechIngredientRawSerializer
    pagination_class   = StandardPagination
    queryset           = SoftechIngredientRaw.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(ainame__icontains=q) | Q(aicode__icontains=q))
        if self.request.query_params.get('used_only'):
            qs = qs.filter(item_count__gt=0)
        return qs.order_by('ainame')


class IngredientParseCandidateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The parser's review queue. Filters:
      ?status=pending|needs_review|approved|rejected
      ?combos=1            only combination formulas
      ?placeholders=1      only junk/placeholder rows
      ?min_confidence=0.8
      ?molecule=amlodipine (matches proposed molecule OR raw name)
      ?q=...               free text over the raw name
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = IngredientParseCandidateSerializer
    pagination_class   = StandardPagination
    queryset           = IngredientParseCandidate.objects.select_related('raw').all()

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        status = p.get('status')
        if status:
            qs = qs.filter(status=status)
        if p.get('combos'):
            qs = qs.filter(is_combination=True)
        if p.get('placeholders'):
            qs = qs.filter(is_placeholder=True)
        mc = p.get('min_confidence')
        if mc:
            try:
                qs = qs.filter(confidence__gte=float(mc))
            except ValueError:
                pass
        molecule = p.get('molecule')
        if molecule:
            qs = qs.filter(
                Q(raw_ainame__icontains=molecule) |
                Q(parsed_components__icontains=molecule)
            )
        q = p.get('q')
        if q:
            qs = qs.filter(raw_ainame__icontains=q)
        return qs.order_by('-confidence', 'raw_ainame')

    # ── review write-actions (RBAC: catalog/edit) ────────────────────────────
    def _profile(self, request):
        return getattr(request.user, 'staff_profile', None)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        if not _can_edit(request):
            return _forbidden()
        cand = self.get_object()
        class_override = None
        cid = request.data.get('class_id')
        if cid:
            class_override = IngredientClass.objects.filter(pk=cid).first()
        approve_engine.approve_candidate(cand, self._profile(request), class_override)
        return Response(IngredientParseCandidateSerializer(cand).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        if not _can_edit(request):
            return _forbidden()
        cand = self.get_object()
        approve_engine.reject_candidate(cand, self._profile(request),
                                        notes=request.data.get('notes', ''))
        return Response(IngredientParseCandidateSerializer(cand).data)

    @action(detail=True, methods=['post'], url_path='non-drug')
    def non_drug(self, request, pk=None):
        if not _can_edit(request):
            return _forbidden()
        cand = self.get_object()
        approve_engine.mark_non_drug(cand, request.data.get('class_key', ''),
                                     self._profile(request))
        return Response(IngredientParseCandidateSerializer(cand).data)

    @action(detail=True, methods=['post'], url_path='set-class')
    def set_class(self, request, pk=None):
        if not _can_edit(request):
            return _forbidden()
        cand = self.get_object()
        approve_engine.set_class(cand, request.data.get('class_id'), self._profile(request))
        return Response(IngredientParseCandidateSerializer(cand).data)

    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        """Catalog items linked to this row's SOFTECH aicode (via itemsai)."""
        from apps.composition.models import SoftechItemAI
        from apps.catalog.models import Item
        cand = self.get_object()
        codes = list(SoftechItemAI.objects.filter(aicode=cand.raw_aicode)
                     .values_list('item_softech_id', flat=True))
        items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)}
        out = []
        for c in codes:
            it = items.get(c)
            out.append({
                'softech_id': c,
                'item_id': it.id if it else None,
                'name': it.name if it else '',
                'shape': ((it.shape_name_ar or it.shape_name) if it else ''),
            })
        return Response(out)

    @action(detail=True, methods=['post'])
    def edit(self, request, pk=None):
        """Clean the parsed components (rename molecules, fix strengths, keep/drop
        each) before approval. Reviewer-edited text becomes the canonical name."""
        if not _can_edit(request):
            return _forbidden()
        cand = self.get_object()
        cleaned = []
        for c in (request.data.get('components') or []):
            mol = (c.get('molecule') or '').strip().upper()
            if not mol:
                continue
            sval = c.get('strength_value')
            try:
                sval = float(sval) if sval not in (None, '') else None
            except (TypeError, ValueError):
                sval = None
            cleaned.append({
                'molecule': mol,
                'salt': (c.get('salt') or '').strip(),
                'strength_value': sval,
                'strength_unit': (c.get('strength_unit') or '').strip(),
                'include': bool(c.get('include', True)),
                'raw_fragment': c.get('raw_fragment', ''),
            })
        cand.parsed_components = cleaned
        included = [c for c in cleaned if c.get('include', True)]
        cand.is_combination = len(included) > 1
        cand.is_placeholder = (len(included) == 0)
        # refresh the class proposal from the primary kept molecule (only if unset)
        if included and not cand.proposed_class_id:
            from apps.composition.classify import classify
            key, rule, conf = classify(included[0]['molecule'])
            if key:
                k = IngredientClass.objects.filter(key=key).first()
                if k:
                    cand.proposed_class = k
                    cand.class_rule = f'{rule}[edit]'
                    cand.class_confidence = conf
        cand.save()
        return Response(IngredientParseCandidateSerializer(cand).data)

    @action(detail=False, methods=['get'])
    def molecule_groups(self, request):
        """Worklist grouped by proposed primary molecule — the dedup view.
        Returns top molecules with total/pending counts + item coverage."""
        q = (request.query_params.get('q') or '').upper()
        pending_only = request.query_params.get('pending') == '1'
        base = IngredientParseCandidate.objects.filter(is_placeholder=False)
        groups = defaultdict(lambda: {'total': 0, 'pending': 0, 'items': 0, 'aicodes': []})
        for c in base.only('parsed_components', 'status', 'raw_aicode'):
            mol = c.primary_molecule
            if not mol or (q and q not in mol):
                continue
            g = groups[mol]
            g['total'] += 1
            if c.status in (IngredientParseCandidate.STATUS_PENDING,
                            IngredientParseCandidate.STATUS_NEEDS_REVIEW):
                g['pending'] += 1
            if len(g['aicodes']) < 50:
                g['aicodes'].append(c.raw_aicode)
        rows = [{'molecule': m, **v} for m, v in groups.items()]
        if pending_only:
            rows = [r for r in rows if r['pending'] > 0]
        rows.sort(key=lambda r: (-r['total'], r['molecule']))
        return Response({'count': len(rows), 'groups': rows[:200]})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Dedup / cleanup overview for the reconciliation dashboard."""
        base = IngredientParseCandidate.objects.all()
        by_status = dict(
            base.values_list('status').annotate(n=Count('id')).values_list('status', 'n')
        )
        # Distinct proposed molecules across ALL components (each molecule in a
        # combination becomes its own canonical row) → the dedup target count.
        molecules = set()
        for comps in base.exclude(is_placeholder=True).values_list('parsed_components', flat=True):
            for c in (comps or []):
                if c.get('molecule'):
                    molecules.add(c['molecule'])
        raw_total   = SoftechIngredientRaw.objects.count()
        items_total = SoftechIngredientRaw.objects.aggregate(n=Sum('item_count'))['n'] or 0
        return Response({
            'raw_rows': raw_total,
            'candidates': base.count(),
            'by_status': by_status,
            'combinations': base.filter(is_combination=True).count(),
            'placeholders': base.filter(is_placeholder=True).count(),
            'distinct_proposed_molecules': len(molecules),
            'dedup_ratio': (
                round(1 - len(molecules) / raw_total, 3) if raw_total else 0.0),
            'item_links_covered': items_total,
        })


class IngredientSearchViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Track A search over the materialized item↔molecule index.

    list  ?molecule=amlodipine[&exact=1]  &strength_value=5&strength_unit=mg
          &dosage_form=قرص  &class_id=..|class_key=statins  &source=approved
          &q=free-text (molecule OR item name)
    Extra: /molecules/ (autocomplete w/ item counts) · /facets/ (dosage forms + classes).
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ItemMoleculeIndexSerializer
    pagination_class   = StandardPagination

    def get_queryset(self):
        qs = ItemMoleculeIndex.objects.select_related('ingredient_class', 'active_ingredient')
        p = self.request.query_params
        molecule = p.get('molecule')
        if molecule:
            qs = (qs.filter(molecule__iexact=molecule) if p.get('exact')
                  else qs.filter(molecule__icontains=molecule))
        sv = p.get('strength_value')
        if sv:
            try:
                qs = qs.filter(strength_value=Decimal(sv))
            except (InvalidOperation, ValueError):
                pass
        if p.get('strength_unit'):
            qs = qs.filter(strength_unit__iexact=p['strength_unit'])
        if p.get('dosage_form'):
            qs = qs.filter(dosage_form__icontains=p['dosage_form'])
        if p.get('class_id'):
            qs = qs.filter(ingredient_class_id=p['class_id'])
        if p.get('class_key'):
            qs = qs.filter(ingredient_class__key=p['class_key'])
        if p.get('source'):
            qs = qs.filter(source=p['source'])
        q = p.get('q')
        if q:
            qs = qs.filter(Q(molecule__icontains=q) | Q(item_name__icontains=q))
        return qs.order_by('molecule', 'item_name')

    @action(detail=False, methods=['get'])
    def molecules(self, request):
        """Molecule autocomplete with item counts (for the search box)."""
        q = (request.query_params.get('q') or '').strip()
        qs = ItemMoleculeIndex.objects.all()
        if q:
            qs = qs.filter(molecule__icontains=q)
        data = (qs.values('molecule')
                  .annotate(items=Count('item_softech_id', distinct=True))
                  .order_by('-items', 'molecule')[:50])
        return Response(list(data))

    @action(detail=False, methods=['get'])
    def facets(self, request):
        """Distinct dosage forms + classes + units present in the index."""
        forms = list(ItemMoleculeIndex.objects.exclude(dosage_form='')
                     .values_list('dosage_form', flat=True).distinct().order_by('dosage_form'))
        units = list(ItemMoleculeIndex.objects.exclude(strength_unit='')
                     .values_list('strength_unit', flat=True).distinct().order_by('strength_unit'))
        class_ids = (ItemMoleculeIndex.objects.exclude(ingredient_class__isnull=True)
                     .values_list('ingredient_class', flat=True).distinct())
        classes = list(IngredientClass.objects.filter(id__in=class_ids)
                       .values('id', 'key', 'name', 'name_ar').order_by('name'))
        return Response({'dosage_forms': forms, 'units': units, 'classes': classes})

    @action(detail=False, methods=['post'])
    def rebuild(self, request):
        """Rebuild the item↔molecule index from the current approvals (RBAC edit)."""
        if not _can_edit(request):
            return _forbidden()
        from django.core.management import call_command
        call_command('build_ingredient_search_index')
        base = ItemMoleculeIndex.objects.all()
        return Response({
            'rows': base.count(),
            'items': base.values('item_softech_id').distinct().count(),
            'molecules': base.values('molecule').distinct().count(),
            'approved': base.filter(source='approved').count(),
        })
