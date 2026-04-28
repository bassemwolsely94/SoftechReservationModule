from django.db import models


class Branch(models.Model):
    softech_branch_id = models.CharField(max_length=10, unique=True)
    code = models.CharField(max_length=10, blank=True)
    name = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Branches'
        ordering = ['name']

    def __str__(self):
        return self.name_ar or self.name
