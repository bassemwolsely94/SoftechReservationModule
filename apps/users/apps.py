from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"

    def ready(self):
        # core.branch_scope memoises a profile's branch set; any change to a profile, its allowed /
        # restricted branches, a user's active flag or a branch must invalidate it (full audit PERF-4).
        from django.contrib.auth.models import User
        from django.db.models.signals import m2m_changed, post_delete, post_save

        from apps.branches.models import Branch
        from core.branch_scope import bump_generation
        from .models import StaffProfile

        for model in (StaffProfile, Branch, User):
            post_save.connect(bump_generation, sender=model, dispatch_uid=f'branch_scope_save_{model.__name__}')
            post_delete.connect(bump_generation, sender=model, dispatch_uid=f'branch_scope_del_{model.__name__}')
        for field in ('allowed_branches', 'restricted_branches'):
            m2m_changed.connect(bump_generation, sender=getattr(StaffProfile, field).through,
                                dispatch_uid=f'branch_scope_m2m_{field}')
