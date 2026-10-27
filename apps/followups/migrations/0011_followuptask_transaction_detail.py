# Adds full transaction detail fields to FollowUpTask so each task
# carries the complete SOFTECH reference: docnumber, branch code,
# invoice total, item quantity, and unit price at time of sale.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('followups', '0010_followuptask_pin'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='source_softech_branch_code',
            field=models.CharField(
                blank=True,
                help_text='stktransm.branchcode — الكود الخام للفرع في SOFTECH',
                max_length=10,
                verbose_name='كود الفرع في ERP',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='source_total_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='stktransm.totalamount — إجمالي الفاتورة المصدر',
                max_digits=14,
                null=True,
                verbose_name='إجمالي الفاتورة',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='source_item_qty',
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                help_text='stktrans.qty — كمية هذا الصنف في الفاتورة المصدر',
                max_digits=12,
                null=True,
                verbose_name='الكمية المباعة',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='source_item_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                help_text='stktrans.unitprice — سعر البيع الفعلي في الفاتورة المصدر',
                max_digits=10,
                null=True,
                verbose_name='سعر الوحدة عند البيع',
            ),
        ),
        # Also update the existing source_erp_transaction help_text
        migrations.AlterField(
            model_name='followuptask',
            name='source_erp_transaction',
            field=models.CharField(
                blank=True,
                help_text='stktransm.docnumber — للبحث المباشر في SOFTECH',
                max_length=50,
                verbose_name='رقم المستند في ERP',
            ),
        ),
    ]
