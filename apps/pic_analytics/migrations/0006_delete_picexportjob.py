# Performance Stage 4: the PIC background export now uses apps.export_jobs.ExportJob.
# Its rows are kept 48 h at most and a deploy restarts the process that ran them, so nothing
# worth keeping is dropped with the table.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pic_analytics', '0005_pic_export_job'),
        ('export_jobs', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='PicExportJob'),
    ]
