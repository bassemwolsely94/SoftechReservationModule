"""
Whisper queue status/controls (PBX settings tab) and transcript corrections.
"""
from datetime import time as dtime

from django.utils import timezone
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.callcenter.models import CallTranscript, WhisperQueueControl

MODEL_SIZES = ('small', 'medium', 'large-v3')


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class IsAdminOrSupervisor(BasePermission):
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.is_active and p.role in ('admin', 'supervisor'))


class CanCorrect(BasePermission):
    def has_permission(self, request, view):
        p = _profile(request)
        return bool(p and p.is_active and
                    p.role in ('admin', 'supervisor', 'call_center', 'quality_manager'))


def _control_data(c):
    from apps.callcenter import whisper
    return {
        'enabled': whisper.enabled(),
        'paused': c.paused, 'stop_requested': c.stop_requested,
        'window_start': c.window_start.strftime('%H:%M') if c.window_start else '',
        'window_end': c.window_end.strftime('%H:%M') if c.window_end else '',
        'model_size': c.model_size, 'cpu_threads': c.cpu_threads or whisper.default_threads(),
        'running': whisper.run_is_active(c),
        'run_started_at': c.run_started_at, 'run_finished_at': c.run_finished_at,
        'run_processed': c.run_processed, 'run_note': c.run_note,
    }


def _transcript_row(t, gemini_by_call):
    g = gemini_by_call.get(t.call_log_id)
    log = t.call_log
    return {
        'id': t.id, 'call_log': t.call_log_id, 'status': t.status,
        'phone': log.phone_number, 'customer_name': log.customer.name if log.customer else log.caller_name,
        'called_at': log.called_at, 'duration_seconds': log.duration_seconds,
        'whisper_text': t.text, 'gemini_text': g.text if g else '',
        'gemini_id': g.id if g else None,
        'corrected_text': t.corrected_text or (g.corrected_text if g else ''),
        'error': t.error, 'attempts': t.attempts,
        'processing_seconds': t.processing_seconds, 'audio_seconds': t.audio_seconds,
    }


class WhisperStatusView(APIView):
    """GET /api/callcenter/whisper/ — controls, queue stats, recent transcripts."""
    permission_classes = [IsAuthenticated, CanCorrect]

    def get(self, request):
        from apps.callcenter import whisper
        recent = list(CallTranscript.objects.filter(engine='whisper')
                      .exclude(status='pending').select_related('call_log__customer')
                      .order_by('-finished_at')[:30])
        gemini = {g.call_log_id: g for g in CallTranscript.objects.filter(
            engine='gemini', call_log_id__in=[t.call_log_id for t in recent])}
        return Response({
            'control': _control_data(WhisperQueueControl.get()),
            'stats': whisper.queue_stats(),
            'vocabulary_prompt': whisper.build_vocabulary_prompt(),
            'recent': [_transcript_row(t, gemini) for t in recent],
        })


class WhisperControlView(APIView):
    """
    POST /api/callcenter/whisper/control/
    {action: pause|resume|stop} and/or {window_start, window_end, model_size, cpu_threads}
    """
    permission_classes = [IsAuthenticated, IsAdminOrSupervisor]

    def post(self, request):
        from apps.audit.models import AuditLog
        c = WhisperQueueControl.get()
        before = _control_data(c)
        action = request.data.get('action')
        if action == 'pause':
            c.paused = True
        elif action == 'resume':
            c.paused, c.stop_requested = False, False
        elif action == 'stop':
            c.stop_requested = True
        elif action:
            return Response({'detail': 'إجراء غير معروف'}, status=400)

        for field in ('window_start', 'window_end'):
            if field in request.data:
                try:
                    h, m = (int(x) for x in str(request.data[field]).split(':'))
                    setattr(c, field, dtime(h, m))
                except (ValueError, TypeError):
                    return Response({'detail': f'وقت غير صحيح: {field}'}, status=400)
        if 'model_size' in request.data:
            if request.data['model_size'] not in MODEL_SIZES:
                return Response({'detail': 'حجم النموذج غير مدعوم'}, status=400)
            c.model_size = request.data['model_size']
        if 'cpu_threads' in request.data:
            try:
                c.cpu_threads = max(0, min(64, int(request.data['cpu_threads'])))
            except (ValueError, TypeError):
                return Response({'detail': 'عدد الأنوية غير صحيح'}, status=400)
        c.save()

        after = _control_data(c)
        AuditLog.log('whisper_control_changed', user=_profile(request),
                     changes={k: [before[k], after[k]] for k in after if before[k] != after[k]},
                     note=f'action={action or "settings"}')
        return Response(after)


class TranscriptCorrectView(APIView):
    """POST /api/callcenter/transcripts/{id}/correct/ {corrected_text}"""
    permission_classes = [IsAuthenticated, CanCorrect]

    def post(self, request, pk):
        from apps.audit.models import AuditLog
        try:
            t = CallTranscript.objects.get(pk=pk)
        except CallTranscript.DoesNotExist:
            return Response({'detail': 'غير موجود'}, status=404)
        text = str(request.data.get('corrected_text', '')).strip()
        if not text:
            return Response({'detail': 'النص المصحح مطلوب'}, status=400)
        old = t.corrected_text
        t.corrected_text, t.corrected_by, t.corrected_at = text, _profile(request), timezone.now()
        t.save(update_fields=['corrected_text', 'corrected_by', 'corrected_at'])
        AuditLog.log('transcript_corrected', user=_profile(request), obj=t,
                     changes={'corrected_text': [old, text]})
        return Response({'id': t.id, 'corrected_text': t.corrected_text})
