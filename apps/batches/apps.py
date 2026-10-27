from django.apps import AppConfig


class BatchesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.batches'
    verbose_name = 'إدارة الدفعات والصلاحية (FEFO)'

    def ready(self):
        self._register_approval_handlers()

    @staticmethod
    def _register_approval_handlers():
        """
        Register StockBatch with the approval outcome dispatcher so that
        a batch_quarantine ApprovalRequest automatically calls
        BatchService._apply_quarantine() on approval.
        Uses lazy string label — safe at startup.
        """
        try:
            from apps.approvals.signals import register_outcome_handler

            def _batch_quarantine_outcome(approval_request, outcome):
                """
                Called when a batch_quarantine ApprovalRequest closes.
                subject = StockBatch via GenericForeignKey on ApprovalRequest.
                """
                if approval_request.workflow.code != 'batch_quarantine':
                    return
                if outcome != 'approved':
                    return   # rejected → batch stays unquarantined

                try:
                    from apps.batches.models import StockBatch
                    from apps.batches.service import BatchService

                    batch = approval_request.subject
                    if not isinstance(batch, StockBatch):
                        return
                    reason = approval_request.context_data.get('reason', 'معتمد عبر نظام الموافقات')
                    BatchService._apply_quarantine(batch, reason)
                except Exception:
                    import logging
                    logging.getLogger('elrezeiky.batches').exception(
                        'Batch quarantine outcome handler failed for ApprovalRequest #%s',
                        approval_request.pk,
                    )

            register_outcome_handler('batches.stockbatch', _batch_quarantine_outcome)
        except Exception as exc:
            import logging
            logging.getLogger('elrezeiky.batches').warning(
                'Batch approval handler registration failed: %s', exc
            )
