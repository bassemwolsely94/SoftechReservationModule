from django.db import models


class ActivityLog(models.Model):
    """
    Full activity log per reservation.
    Both branch staff and call center can log entries.
    """
    ACTIVITY_CHOICES = [
        # Call outcomes
        ('call_answered',        '📞 اتصل — رد العميل'),
        ('call_no_answer',       '📵 اتصل — لم يرد'),
        ('call_busy',            '🔴 اتصل — المشغول'),
        ('call_wrong_number',    '❌ رقم خاطئ'),
        ('call_callback_requested', '🔁 العميل طلب معاودة الاتصال'),
        # Customer responses
        ('customer_coming_today', '✅ العميل قادم اليوم'),
        ('customer_coming_date',  '📅 العميل حدد موعد'),
        ('customer_not_interested', '🚫 العميل غير مهتم'),
        ('customer_wants_alternative', '🔄 العميل يريد بديل'),
        # Stock & supply actions
        ('item_ordered_supplier', '🏭 تم طلب الصنف من المورد'),
        ('item_expected_date',    '📦 تاريخ وصول الصنف متوقع'),
        ('item_arrived',          '✅ وصل الصنف'),
        # Status updates
        ('status_updated',        '🔄 تم تحديث الحالة'),
        ('note_added',            '📝 ملاحظة'),
        ('follow_up_set',         '📅 تم تحديد موعد متابعة'),
    ]

    reservation = models.ForeignKey(
        'reservations.Reservation',
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    activity_type = models.CharField(max_length=40, choices=ACTIVITY_CHOICES)
    note = models.TextField(blank=True)
    logged_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        related_name='activity_logs'
    )
    # For call_callback_requested / customer_coming_date
    callback_datetime = models.DateTimeField(null=True, blank=True)
    # For item_expected_date
    expected_date = models.DateField(null=True, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_at']
        indexes = [
            models.Index(fields=['reservation', 'logged_at']),
        ]

    def __str__(self):
        return f"#{self.reservation_id} — {self.get_activity_type_display()} by {self.logged_by}"

    @property
    def logged_by_name(self):
        if self.logged_by:
            return f"{self.logged_by.full_name} ({self.logged_by.branch_name})"
        return 'النظام'

    @property
    def is_call_activity(self):
        return self.activity_type.startswith('call_')
