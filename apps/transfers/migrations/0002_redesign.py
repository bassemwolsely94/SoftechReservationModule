"""
Migration: add TransferRequestItem and TransferRequestMessage tables,
and add new fields to TransferRequest.

This migration adds columns to the existing transferrequest table
and creates two new tables. Run after backing up.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0001_initial'),
        ('catalog', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        # ── Add new fields to TransferRequest ─────────────────────────────────
        migrations.AddField(
            model_name='transferrequest',
            name='request_number',
            field=models.CharField(blank=True, max_length=20, unique=True,
                                   verbose_name='رقم الطلب', default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='destination_branch',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='incoming_requests',
                to='branches.branch',
                verbose_name='الفرع المصدر',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='source_branch_new',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='outgoing_requests',
                to='branches.branch',
                verbose_name='الفرع الطالب',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='created_by_new',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='created_transfer_requests',
                to='users.staffprofile',
                verbose_name='أنشئ بواسطة',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_transfer_requests',
                to='users.staffprofile',
                verbose_name='راجع بواسطة',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='rejection_reason',
            field=models.TextField(blank=True, verbose_name='سبب الرفض'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='revision_notes',
            field=models.TextField(blank=True, verbose_name='ملاحظات التعديل'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='erp_reference',
            field=models.CharField(blank=True, max_length=100, verbose_name='مرجع الـ ERP'),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='sent_to_erp_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='sent_to_erp_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='erp_sent_requests',
                to='users.staffprofile',
                verbose_name='أُرسل للـ ERP بواسطة',
            ),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='submitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='transferrequest',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='transferrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'مسودة'),
                    ('pending', 'بانتظار الموافقة'),
                    ('approved', 'معتمد'),
                    ('rejected', 'مرفوض'),
                    ('needs_revision', 'يحتاج تعديل'),
                    ('sent_to_erp', 'تم الإرسال للـ ERP'),
                    ('completed', 'مكتمل'),
                    ('cancelled', 'ملغي'),
                ],
                db_index=True, default='draft', max_length=20, verbose_name='حالة الطلب'
            ),
        ),

        # ── TransferRequestItem ───────────────────────────────────────────────
        migrations.CreateModel(
            name='TransferRequestItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('quantity', models.DecimalField(decimal_places=3, max_digits=10,
                                                  verbose_name='الكمية المطلوبة')),
                ('notes', models.CharField(blank=True, max_length=255, verbose_name='ملاحظة')),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='transfer_request_items',
                    to='catalog.item', verbose_name='الصنف',
                )),
                ('request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='transfers.transferrequest', verbose_name='الطلب',
                )),
            ],
            options={
                'verbose_name': 'صنف في الطلب',
                'verbose_name_plural': 'أصناف الطلب',
                'unique_together': {('request', 'item')},
            },
        ),

        # ── TransferRequestMessage ────────────────────────────────────────────
        migrations.CreateModel(
            name='TransferRequestMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True)),
                ('message_type', models.CharField(
                    choices=[
                        ('message', '💬 رسالة'),
                        ('system', '⚙️ نظام'),
                        ('note', '📝 ملاحظة داخلية'),
                    ],
                    default='message', max_length=10,
                )),
                ('message', models.TextField(verbose_name='الرسالة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transfer_messages',
                    to='users.staffprofile', verbose_name='بواسطة',
                )),
                ('request', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='messages',
                    to='transfers.transferrequest', verbose_name='الطلب',
                )),
            ],
            options={
                'verbose_name': 'رسالة',
                'verbose_name_plural': 'رسائل الطلب',
                'ordering': ['created_at'],
            },
        ),
    ]
