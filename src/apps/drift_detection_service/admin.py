from django.contrib import admin

from apps.drift_detection_service.models import DriftRun, DriftSignal


@admin.register(DriftRun)
class DriftRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject_user_id', 'scope', 'status', 'ga_triggered', 'started_at', 'finished_at')
    list_filter = ('scope', 'status', 'ga_triggered')
    search_fields = ('subject_user_id',)


@admin.register(DriftSignal)
class DriftSignalAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'drift_run',
        'subject_user_id',
        'signal_type',
        'severity',
        'score',
        'threshold',
        'detected_at',
    )
    list_filter = ('signal_type', 'severity', 'scope')
    search_fields = ('subject_user_id',)
