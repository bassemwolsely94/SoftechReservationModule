"""
apps/portal/models.py

One row per magic link (security Batch 6, W-5). The link logs in ONCE: exchanging it stamps
`used_at` and opens the session the row now stands for. A session token carries the row's
`session_key`, so ending the row (logout, or staff via `revoke_all`) ends the session at once.
"""
import secrets

from django.db import models
from django.utils import timezone


def _key():
    return secrets.token_urlsafe(24)


class PortalLogin(models.Model):
    customer    = models.ForeignKey('customers.Customer', on_delete=models.CASCADE,
                                    related_name='portal_logins', verbose_name='العميل')
    nonce       = models.CharField(max_length=40, unique=True, default=_key)
    session_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    used_at     = models.DateTimeField(null=True, blank=True, verbose_name='استُخدم الرابط')
    revoked_at  = models.DateTimeField(null=True, blank=True, verbose_name='أُنهيت الجلسة')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'دخول بوابة العملاء'
        verbose_name_plural = 'دخول بوابة العملاء'

    def __str__(self):
        return f'{self.customer_id} · {self.created_at:%Y-%m-%d %H:%M}'

    @classmethod
    def redeem(cls, nonce: str, softech_pic: str):
        """Open the session for an unused link; None if the link was used, revoked or never sent."""
        key = _key()
        done = cls.objects.filter(nonce=nonce, customer__softech_pic=softech_pic,
                                  used_at__isnull=True, revoked_at__isnull=True
                                  ).update(used_at=timezone.now(), session_key=key)
        return cls.objects.select_related('customer').get(nonce=nonce) if done else None

    @classmethod
    def live_session(cls, session_key: str, softech_pic: str):
        return (cls.objects.select_related('customer')
                .filter(session_key=session_key, customer__softech_pic=softech_pic,
                        revoked_at__isnull=True).first())

    def revoke(self):
        PortalLogin.objects.filter(pk=self.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())

    @classmethod
    def revoke_all(cls, customer) -> int:
        """End every open session and unused link of a customer (lost phone, staff request)."""
        return cls.objects.filter(customer=customer, revoked_at__isnull=True).update(revoked_at=timezone.now())
