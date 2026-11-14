"""
apps/tests/factories.py

Shared test fixtures for the ElRezeiky test suite.
Creates Django + DRF test users and related models in a clean, reusable way.
No third-party factory_boy dependency — pure Django ORM.
"""
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.branches.models import Branch
from apps.users.models import StaffProfile
from apps.catalog.models import Item, Category
from apps.customers.models import Customer


# ── Branch ─────────────────────────────────────────────────────────────────────

def make_branch(name='فرع التجربة', softech_id='B01') -> Branch:
    """Look up by the unique softech_branch_id to avoid duplicate-key failures."""
    branch, _ = Branch.objects.get_or_create(
        softech_branch_id=softech_id,
        defaults={
            'name': name,
            'name_ar': name,
            'is_active': True,
        },
    )
    return branch


def make_hq(code='100', testcase=None) -> Branch:
    """The one HQ branch (kind hq) — code that reads HQ through hq_code() needs it. Any other hq row
    becomes retail. Drops the hq_code() cache now and, with ``testcase``, again at cleanup (a
    test-transaction rollback fires no signals)."""
    from apps.branches.models import _reset_hq_code_cache
    Branch.objects.filter(kind=Branch.KIND_HQ).exclude(softech_branch_id=code).update(kind=Branch.KIND_RETAIL)
    branch, _ = Branch.objects.update_or_create(
        softech_branch_id=code, defaults={'kind': Branch.KIND_HQ},
        create_defaults={'kind': Branch.KIND_HQ, 'name': 'HQ', 'name_ar': 'الرئيسي'})
    _reset_hq_code_cache()
    if testcase is not None:
        testcase.addCleanup(_reset_hq_code_cache)
    return branch


def make_branch2(name='فرع ثانٍ', softech_id='B02') -> Branch:
    branch, _ = Branch.objects.get_or_create(
        softech_branch_id=softech_id,
        defaults={
            'name': name,
            'name_ar': name,
            'is_active': True,
        },
    )
    return branch


# ── Staff users ────────────────────────────────────────────────────────────────

def make_user(username, role='pharmacist', branch=None, password='TestPass123',
              access_all=False) -> tuple:
    """Returns (django_user, staff_profile, api_client)."""
    if branch is None:
        branch = make_branch()

    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'first_name': username, 'is_active': True},
    )
    user.set_password(password)
    user.save()

    profile, _ = StaffProfile.objects.get_or_create(
        user=user,
        defaults={
            'role': role,
            'branch': branch,
            'is_active': True,
            'access_all_branches': access_all,
        },
    )
    profile.role = role
    profile.branch = branch
    profile.is_active = True
    profile.access_all_branches = access_all
    profile.save()

    client = APIClient()
    client.force_authenticate(user=user)
    return user, profile, client


def make_admin(username='admin_test') -> tuple:
    return make_user(username, role='admin', access_all=True)


def make_pharmacist(username='pharma_test', branch=None) -> tuple:
    return make_user(username, role='pharmacist', branch=branch)


def make_call_center(username='cc_test') -> tuple:
    return make_user(username, role='call_center', access_all=True)


def make_salesperson(username='sales_test', branch=None) -> tuple:
    return make_user(username, role='salesperson', branch=branch)


def make_supervisor(username='supervisor_test') -> tuple:
    return make_user(username, role='supervisor', access_all=True)


def make_quality_manager(username='qm_test') -> tuple:
    return make_user(username, role='quality_manager', access_all=True)


def make_viewer(username='viewer_test', branch=None) -> tuple:
    return make_user(username, role='viewer', branch=branch)


def make_anon_client() -> APIClient:
    return APIClient()


# ── Catalog ───────────────────────────────────────────────────────────────────

def make_category(name='اختبار') -> Category:
    return Category.objects.get_or_create(name=name)[0]


def make_item(name='باراسيتامول', softech_id='IT001') -> Item:
    """softech_id max_length=6 — keep to 5 chars to be safe."""
    cat = make_category()
    return Item.objects.get_or_create(
        softech_id=softech_id,
        defaults={
            'name': name,
            'category': cat,
            'is_active': True,
        }
    )[0]


# ── Customer ──────────────────────────────────────────────────────────────────

def make_customer(name='أحمد محمد', phone='01012345678') -> Customer:
    return Customer.objects.get_or_create(
        phone=phone,
        defaults={'name': name, 'is_guest': False},
    )[0]
