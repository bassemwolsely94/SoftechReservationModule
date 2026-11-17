"""Response shapes of the staff API. Branches always carry their names; devices never carry token material."""
from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import serializers

from .models import RpaDevice, RpaDocument, RpaJob, RpaLine, RpaRecipe, RpaRun, RpaScreen, RpaScreenshot

ONLINE_WINDOW = timedelta(minutes=2)


def is_online(device) -> bool:
    return bool(device.revoked_at is None and device.last_seen_at
                and device.last_seen_at >= timezone.now() - ONLINE_WINDOW)


def _staff_name(profile):
    return profile.full_name if profile is not None else ''


def _branch_name(branch):
    return (branch.name_ar or branch.name) if branch is not None else ''


class ScreenSerializer(serializers.ModelSerializer):
    class Meta:
        model = RpaScreen
        fields = ['key', 'title_ar', 'enabled', 'live']


class LineSerializer(serializers.ModelSerializer):
    item_name = serializers.SerializerMethodField()

    class Meta:
        model = RpaLine
        fields = ['id', 'row_no', 'itemcode', 'item_name', 'qty', 'expiry', 'status', 'message', 'warning']

    def get_item_name(self, line):
        return line.item.name if line.item_id else ''


class DocumentSerializer(serializers.ModelSerializer):
    lines = LineSerializer(many=True, read_only=True)

    class Meta:
        model = RpaDocument
        fields = ['id', 'seq', 'status', 'softech_docnumber', 'needs_person_reason', 'verify_result',
                  'claimed_at', 'lease_until', 'lines']


class JobListSerializer(serializers.ModelSerializer):
    screen = serializers.CharField(source='screen.key')
    screen_title = serializers.CharField(source='screen.title_ar')
    branch_name = serializers.SerializerMethodField()
    target_branch_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    documents_count = serializers.IntegerField(read_only=True, default=0)
    lines_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = RpaJob
        fields = ['id', 'screen', 'screen_title', 'branch', 'branch_name', 'target_branch', 'target_branch_name',
                  'store_code', 'filename', 'status', 'dry_run', 'created_by_name', 'approved_by_name',
                  'created_at', 'approved_at', 'documents_count', 'lines_count']

    def get_branch_name(self, job):
        return _branch_name(job.branch)

    def get_target_branch_name(self, job):
        return _branch_name(job.target_branch)

    def get_created_by_name(self, job):
        return _staff_name(job.created_by)

    def get_approved_by_name(self, job):
        return _staff_name(job.approved_by)


class JobDetailSerializer(JobListSerializer):
    documents = serializers.SerializerMethodField()
    recipe_version = serializers.SerializerMethodField()

    class Meta(JobListSerializer.Meta):
        fields = JobListSerializer.Meta.fields + ['recipe_version', 'documents']

    def get_documents(self, job):
        docs = job.documents.prefetch_related('lines__item').order_by('seq', 'id')
        return DocumentSerializer(docs, many=True).data

    def get_recipe_version(self, job):
        return job.recipe.version if job.recipe_id else None


class RunSerializer(serializers.ModelSerializer):
    device_label = serializers.CharField(source='device.label')
    recipe_version = serializers.IntegerField(source='recipe.version')
    screenshots = serializers.SerializerMethodField()

    class Meta:
        model = RpaRun
        fields = ['id', 'device_label', 'recipe_version', 'mode', 'started_at', 'finished_at', 'outcome', 'steps',
                  'screenshots']

    def get_screenshots(self, run):
        return [{'id': s.id, 'step_index': s.step_index, 'url': s.image.url, 'created_at': s.created_at}
                for s in run.shots.all()]


class DocumentDetailSerializer(DocumentSerializer):
    job_id = serializers.IntegerField(read_only=True)
    job_status = serializers.CharField(source='job.status')
    screen_title = serializers.CharField(source='job.screen.title_ar')
    branch_name = serializers.SerializerMethodField()
    target_branch_name = serializers.SerializerMethodField()
    runs = serializers.SerializerMethodField()

    class Meta(DocumentSerializer.Meta):
        fields = ['job_id', 'job_status', 'screen_title', 'branch_name', 'target_branch_name'] + \
                 DocumentSerializer.Meta.fields + ['runs']

    def get_branch_name(self, doc):
        return _branch_name(doc.job.branch)

    def get_target_branch_name(self, doc):
        return _branch_name(doc.job.target_branch)

    def get_runs(self, doc):
        runs = (doc.runs.select_related('device', 'recipe').order_by('-started_at', '-id')
                .prefetch_related(Prefetch('shots', queryset=RpaScreenshot.objects.order_by('step_index', 'id'))))
        return RunSerializer(runs, many=True).data


class RecipeSerializer(serializers.ModelSerializer):
    screen = serializers.CharField(source='screen.key')
    screen_title = serializers.CharField(source='screen.title_ar')
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RpaRecipe
        fields = ['id', 'screen', 'screen_title', 'version', 'status', 'window_title', 'cell_delay', 'form_delay',
                  'line_cells', 'save_keys', 'cancel_keys', 'source_filename', 'created_by_name',
                  'approved_by_name', 'approved_at']

    def get_created_by_name(self, recipe):
        return _staff_name(recipe.created_by)

    def get_approved_by_name(self, recipe):
        return _staff_name(recipe.approved_by)


class DeviceSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()
    online = serializers.SerializerMethodField()

    class Meta:
        model = RpaDevice
        fields = ['id', 'label', 'staff', 'staff_name', 'created_at', 'last_seen_at', 'revoked_at', 'online']

    def get_staff_name(self, device):
        return _staff_name(device.staff)

    def get_online(self, device):
        return is_online(device)
