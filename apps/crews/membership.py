"""
apps/crews/membership.py

The one crew-membership resolver (spec 2026-11-13 §6.4). Deterministic, no SOFTECH access.

Membership on day D = (employees whose assignment on D matches an active rule
                       ∪ manual includes active on D) − manual excludes active on D,
restricted to employees employed on D (start_date <= D <= end_date, blanks open).

Every public function loads the crew's rows, the relevant assignments and employees ONCE
(a fixed number of queries whatever the date range), then evaluates in memory. `members` and
`members_between` share `_timeline`, so a day's members always agree with the spans.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from functools import reduce
from operator import or_

from django.db.models import Q

from apps.hr.models import Employee, EmployeeAssignment

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Member:
    key: tuple                 # ('emp', id) | ('code', usercode) | ('ext', extension)
    employee_id: int | None
    name: str
    hr_number: str
    job_title: str
    branch_id: int | None
    softech_usercodes: tuple
    extensions: tuple
    staff_id: int | None
    off_payroll: bool
    source: str                # 'rule' | 'manual'


@dataclass(frozen=True)
class Identity:
    kind: str                  # 'softech_user' | 'extension' | 'staff'
    value: str
    valid_from: date
    valid_to: date
    member_key: tuple


@dataclass(frozen=True)
class _Rule:
    job_titles: frozenset
    branch_ids: frozenset
    departments: frozenset
    sections: frozenset
    valid_from: date
    valid_to: date | None

    def empty(self) -> bool:
        return not (self.job_titles or self.branch_ids or self.departments or self.sections)

    def matches(self, a) -> bool:
        return ((not self.job_titles or a.job_title in self.job_titles)
                and (not self.branch_ids or a.branch_id in self.branch_ids)
                and (not self.departments or a.department in self.departments)
                and (not self.sections or a.section in self.sections))

    def q(self) -> Q:
        q = Q()
        if self.job_titles:
            q &= Q(job_title__in=self.job_titles)
        if self.branch_ids:
            q &= Q(branch_id__in=self.branch_ids)
        if self.departments:
            q &= Q(department__in=self.departments)
        if self.sections:
            q &= Q(section__in=self.sections)
        return q


def _active(row, d: date) -> bool:
    return row.valid_from <= d and (row.valid_to is None or d <= row.valid_to)


def _employed(e, d: date) -> bool:
    return (e.start_date is None or e.start_date <= d) and (e.end_date is None or d <= e.end_date)


def _overlap_q(start: date, end: date) -> Q:
    return Q(valid_from__lte=end) & (Q(valid_to__isnull=True) | Q(valid_to__gte=start))


def _rule_from_row(r) -> _Rule:
    return _Rule(frozenset(r.job_titles or ()), frozenset(b.id for b in r.branches.all()),
                 frozenset(r.departments or ()), frozenset(r.sections or ()),
                 r.valid_from, r.valid_to)


def _rule_from_dict(spec: dict, d: date) -> _Rule:
    return _Rule(frozenset(spec.get('job_titles') or ()), frozenset(spec.get('branch_ids') or ()),
                 frozenset(spec.get('departments') or ()), frozenset(spec.get('sections') or ()),
                 d, None)


class _Data:
    """Everything one evaluation needs, loaded with a fixed number of queries."""

    def __init__(self, rules, manual, start: date, end: date):
        self.rules = [r for r in rules if not r.empty()]
        self.manual = manual
        manual_emp_ids = {x.employee_id for x in manual if x.employee_id}
        rule_q = reduce(or_, (r.q() for r in self.rules), Q(pk__in=[]))
        asg_q = (rule_q | Q(employee_id__in=manual_emp_ids)) & _overlap_q(start, end)
        self.assignments = {}       # employee_id -> rows sorted by valid_from
        for a in EmployeeAssignment.objects.filter(asg_q).order_by('employee_id', 'valid_from'):
            self.assignments.setdefault(a.employee_id, []).append(a)
        emp_ids = set(self.assignments) | manual_emp_ids
        self.employees = {e.id: e for e in Employee.objects.filter(id__in=emp_ids)} if emp_ids else {}
        self._starts = {k: [a.valid_from for a in v] for k, v in self.assignments.items()}

    def assignment(self, employee_id: int, d: date):
        rows = self.assignments.get(employee_id)
        if not rows:
            return None
        i = bisect_right(self._starts[employee_id], d) - 1
        if i >= 0 and (rows[i].valid_to is None or d <= rows[i].valid_to):
            return rows[i]
        return None

    def change_points(self, start: date, end: date) -> list:
        points = set()
        rows = [*self.rules, *self.manual, *(a for v in self.assignments.values() for a in v)]
        for r in rows:
            points.add(r.valid_from)
            if r.valid_to is not None:
                points.add(r.valid_to + ONE_DAY)
        for e in self.employees.values():
            if e.start_date:
                points.add(e.start_date)
            if e.end_date:
                points.add(e.end_date + ONE_DAY)
        return sorted(p for p in points if start < p <= end)


def _employee_member(data: _Data, e, d: date, source: str) -> Member:
    a = data.assignment(e.id, d)
    return Member(
        key=('emp', e.id), employee_id=e.id, name=e.name_ar, hr_number=e.hr_number,
        job_title=a.job_title if a else '', branch_id=a.branch_id if a else None,
        softech_usercodes=(e.softech_usercode,) if e.softech_usercode else (),
        extensions=tuple(e.pbx_extensions or ()), staff_id=e.staff_id,
        off_payroll=False, source=source)


def _bare_member(x) -> Member:
    if x.softech_usercode:
        key, codes, exts = ('code', x.softech_usercode), (x.softech_usercode,), ()
    else:
        key, codes, exts = ('ext', x.pbx_extension), (), (x.pbx_extension,)
    return Member(key=key, employee_id=None, name=x.label or key[1], hr_number='', job_title='',
                  branch_id=None, softech_usercodes=codes, extensions=exts, staff_id=None,
                  off_payroll=True, source='manual')


def _evaluate(data: _Data, d: date) -> dict:
    """key -> Member for day d."""
    out = {}
    rules = [r for r in data.rules if _active(r, d)]
    if rules:
        for emp_id in data.assignments:
            e = data.employees.get(emp_id)
            a = data.assignment(emp_id, d)
            if e and a and _employed(e, d) and any(r.matches(a) for r in rules):
                out[('emp', emp_id)] = _employee_member(data, e, d, 'rule')
    manual = [x for x in data.manual if _active(x, d)]
    for x in manual:
        if x.mode != 'include':
            continue
        if x.employee_id:
            e = data.employees.get(x.employee_id)
            if e and _employed(e, d) and ('emp', e.id) not in out:
                out[('emp', e.id)] = _employee_member(data, e, d, 'manual')
        else:
            mem = _bare_member(x)
            out.setdefault(mem.key, mem)
    for x in manual:
        if x.mode != 'exclude':
            continue
        if x.employee_id:
            out.pop(('emp', x.employee_id), None)
        if x.softech_usercode:
            out.pop(('code', x.softech_usercode), None)
            for k in [k for k, v in out.items()
                      if v.employee_id and x.softech_usercode in v.softech_usercodes]:
                del out[k]
        if x.pbx_extension:
            out.pop(('ext', x.pbx_extension), None)
    return out


def _timeline(data: _Data, start: date, end: date) -> list:
    """[(from, to, {key: Member})] covering [start, end] with constant membership per segment."""
    points = [start, *data.change_points(start, end)]
    bounds = points[1:] + [end + ONE_DAY]
    return [(p, nxt - ONE_DAY, _evaluate(data, p)) for p, nxt in zip(points, bounds)]


def _load(crew, start: date, end: date, extra_rules=None) -> _Data:
    if crew is None:
        rules, manual = [], []
    else:
        rules = [_rule_from_row(r) for r in crew.rules.filter(voided_at__isnull=True)
                 .filter(_overlap_q(start, end)).prefetch_related('branches')]
        manual = list(crew.manual_members.filter(voided_at__isnull=True).filter(_overlap_q(start, end)))
    if extra_rules is not None:
        rules = extra_rules
    return _Data(rules, manual, start, end)


def _sorted(members) -> list:
    return sorted(members, key=lambda x: (x.name, x.key))


def members(crew, d: date) -> list:
    data = _load(crew, d, d)
    return _sorted(_timeline(data, d, d)[0][2].values())


def _spans(timeline) -> dict:
    spans = {}
    for frm, to, snapshot in timeline:
        for key in snapshot:
            lst = spans.setdefault(key, [])
            if lst and lst[-1][1] + ONE_DAY == frm:
                lst[-1] = (lst[-1][0], to)
            else:
                lst.append((frm, to))
    return spans


def members_between(crew, start: date, end: date) -> dict:
    """key -> [(from, to)] inclusive spans clipped to [start, end], adjacent spans merged."""
    return _spans(_timeline(_load(crew, start, end), start, end))


def identities(crew, start: date, end: date) -> list:
    """The SOFTECH user codes, PBX extensions and login ids each member carried while a member,
    for report joins."""
    spans = {}
    for frm, to, snapshot in _timeline(_load(crew, start, end), start, end):
        for key, mem in snapshot.items():
            ids = ([('softech_user', c) for c in mem.softech_usercodes]
                   + [('extension', x) for x in mem.extensions]
                   + ([('staff', str(mem.staff_id))] if mem.staff_id else []))
            for kind, value in ids:
                lst = spans.setdefault((kind, value, key), [])
                if lst and lst[-1][1] + ONE_DAY == frm:
                    lst[-1] = (lst[-1][0], to)
                else:
                    lst.append((frm, to))
    return [Identity(kind, value, frm, to, key)
            for (kind, value, key), lst in spans.items() for frm, to in lst]


def preview(rules: list, d: date, crew=None) -> list:
    """Who unsaved rule dicts (job_titles, branch_ids, departments, sections) would match on d,
    plus the crew's manual rows active on d when a crew is given. Nothing is saved."""
    data = _load(crew, d, d, extra_rules=[_rule_from_dict(s, d) for s in rules])
    return _sorted(_evaluate(data, d).values())
