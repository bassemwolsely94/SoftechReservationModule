from django.apps import AppConfig


class HrConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hr'
    verbose_name = 'الموارد البشرية'

    def ready(self):
        self._register_approval_handlers()

    @staticmethod
    def _register_approval_handlers():
        """
        Register HR models with the approval outcome dispatcher.
        Each HR model that owns an ApprovalRequest gets a handler so
        HrService.on_approval_outcome() is called automatically when the
        ApprovalRequest closes.  Uses lazy string labels — safe at startup.
        """
        try:
            from apps.approvals.signals import register_outcome_handler

            def _hr_outcome(approval_request, outcome):
                from apps.hr.service import HrService
                HrService.on_approval_outcome(approval_request, outcome)

            for label in (
                'hr.leaverequest',
                'hr.overtimerequest',
                'hr.salaryadvance',
                'hr.expenseclaim',
                'hr.permit',
            ):
                register_outcome_handler(label, _hr_outcome)
        except Exception as exc:
            import logging
            logging.getLogger('elrezeiky.hr').warning(
                'HR approval handler registration failed: %s', exc
            )
