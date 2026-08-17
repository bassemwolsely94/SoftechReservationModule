from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html
from apps.pbx.models import AgentExtension, PBXQueue, CallSession, PBXEvent


@admin.register(AgentExtension)
class AgentExtensionAdmin(admin.ModelAdmin):
    list_display  = [
        'extension', 'extension_type', 'gateway_type_badge', 'staff_link',
        'registration_badge', 'last_ip', 'queue_name', 'is_active',
    ]
    list_editable  = ['extension_type', 'is_active']
    list_filter    = ['extension_type', 'gateway_type', 'is_active']
    search_fields  = ['extension', 'sip_peer', 'staff__user__first_name',
                      'staff__user__last_name', 'staff__user__username']
    raw_id_fields  = ['staff']
    readonly_fields = ['last_status', 'last_ip', 'created_at', 'updated_at']

    fieldsets = (
        ('التحويلة', {
            'fields': ('extension', 'extension_type', 'sip_peer', 'is_active'),
        }),
        ('المستخدم', {
            'fields': ('staff', 'queue_name'),
            'description': 'اربط هذه التحويلة بموظف من قائمة المستخدمين.',
        }),
        ('إعدادات البوابة الخارجية', {
            'fields': ('gateway_type', 'call_prefix', 'call_suffix'),
            'classes': ('collapse',),
            'description': (
                'هذه الحقول خاصة بالتحويلات من نوع "بوابة خارجية". '
                'حدّد نوع الخط (موبايل/أرضي) والبادئة/اللاحقة التي يضيفها الـ PBX '
                'للأرقام الواردة حتى يُزيلها الـ bridge تلقائياً.'
            ),
        }),
        ('حالة التسجيل (من AMI)', {
            'fields': ('last_status', 'last_ip', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ── custom URLs ──────────────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'map-staff/',
                self.admin_site.admin_view(self.map_staff_view),
                name='pbx_agentextension_map_staff',
            ),
        ]
        return custom + urls

    # ── bulk staff-mapping view ──────────────────────────────────────────────

    def map_staff_view(self, request):
        from apps.users.models import StaffProfile

        if request.method == 'POST':
            saved = self._process_map_post(request)
            if saved:
                messages.success(request, f'تم حفظ {saved} تغيير بنجاح.')
            else:
                messages.info(request, 'لم يتم إجراء أي تغييرات.')
            return redirect('.')

        # Build grouped extension list (exclude gateways)
        def _exts(type_val):
            return list(
                AgentExtension.objects.filter(
                    extension_type=type_val, is_active=True
                ).select_related('staff__user').order_by('extension')
            )

        groups = [
            {'label': 'عمال مركز الاتصال', 'css': 'agents',  'extensions': _exts('agent')},
            {'label': 'موظفون إداريون (المقر الرئيسي)', 'css': 'hq', 'extensions': _exts('hq')},
            {'label': 'تحويلات الفروع',    'css': 'branch', 'extensions': _exts('branch')},
            {'label': 'أخرى',              'css': 'other',  'extensions': _exts('other')},
        ]
        # Drop empty groups
        groups = [g for g in groups if g['extensions']]

        gateways = list(
            AgentExtension.objects.filter(
                extension_type='gateway', is_active=True
            ).order_by('extension')
        )

        # Staff list for the dropdown — wrap in a plain dict to avoid clashing
        # with StaffProfile.full_name @property (which has no setter)
        staff_list = []
        for sp in StaffProfile.objects.select_related('user').filter(
            user__is_active=True
        ).order_by('user__first_name', 'user__last_name'):
            staff_list.append({
                'pk':         sp.pk,
                'full_name':  sp.user.get_full_name() or sp.user.username,
                'role_label': sp.get_role_display() if hasattr(sp, 'get_role_display') else '',
            })

        context = {
            **self.admin_site.each_context(request),
            'title':                 'ربط التحويلات بالموظفين',
            'groups':                groups,
            'gateways':              gateways,
            'staff_list':            staff_list,
            'gateway_type_choices':  AgentExtension.GATEWAY_TYPE_CHOICES,
            'opts':                  AgentExtension._meta,
        }
        return TemplateResponse(
            request,
            'admin/pbx/agentextension/map_staff.html',
            context,
        )

    def _process_map_post(self, request):
        """Process POSTed staff assignments and gateway config."""
        from apps.users.models import StaffProfile

        saved = 0

        # ── staff assignments ──────────────────────────────────────────────
        # Fields named  ext_<pk>  = staff PK (or '')
        ext_pks = [
            k[4:] for k in request.POST if k.startswith('ext_')
        ]
        for pk_str in ext_pks:
            try:
                ext_obj  = AgentExtension.objects.get(pk=int(pk_str))
                staff_pk = request.POST.get(f'ext_{pk_str}', '').strip()

                new_staff_id = int(staff_pk) if staff_pk else None

                # Skip if nothing changed
                current_staff_id = ext_obj.staff_id  # None or int
                if new_staff_id == current_staff_id:
                    continue

                if new_staff_id:
                    sp = StaffProfile.objects.get(pk=new_staff_id)
                    # Release old extension assignment for this staff member
                    AgentExtension.objects.filter(staff=sp).exclude(pk=ext_obj.pk).update(
                        staff=None
                    )
                    ext_obj.staff = sp
                else:
                    ext_obj.staff = None

                ext_obj.save(update_fields=['staff', 'updated_at'])
                saved += 1
            except (AgentExtension.DoesNotExist, StaffProfile.DoesNotExist, ValueError):
                pass

        # ── gateway config ─────────────────────────────────────────────────
        gw_pks = set()
        for k in request.POST:
            if k.startswith('gw_type_') or k.startswith('gw_prefix_') or k.startswith('gw_suffix_'):
                parts = k.split('_')
                gw_pks.add(parts[-1])

        for pk_str in gw_pks:
            try:
                gw = AgentExtension.objects.get(pk=int(pk_str), extension_type='gateway')
                new_type   = request.POST.get(f'gw_type_{pk_str}',   '').strip()
                new_prefix = request.POST.get(f'gw_prefix_{pk_str}', '').strip()
                new_suffix = request.POST.get(f'gw_suffix_{pk_str}', '').strip()

                if (new_type == gw.gateway_type and
                        new_prefix == gw.call_prefix and
                        new_suffix == gw.call_suffix):
                    continue  # nothing changed — don't count it

                gw.gateway_type = new_type
                gw.call_prefix  = new_prefix
                gw.call_suffix  = new_suffix
                gw.save(update_fields=['gateway_type', 'call_prefix', 'call_suffix', 'updated_at'])
                saved += 1
            except (AgentExtension.DoesNotExist, ValueError):
                pass

        return saved

    # ── list display helpers ─────────────────────────────────────────────────

    @admin.display(description='الموظف')
    def staff_link(self, obj):
        if obj.staff:
            return format_html(
                '<a href="/admin/users/staffprofile/{}/change/">{}</a>',
                obj.staff.pk, obj.staff.full_name,
            )
        return format_html('<span style="color:#aaa">— غير مُعيَّن —</span>')

    @admin.display(description='التسجيل')
    def registration_badge(self, obj):
        if obj.last_status.startswith('OK'):
            return format_html(
                '<span style="color:green;font-weight:bold">&#9679; مسجّل</span>'
            )
        if 'UNREACHABLE' in obj.last_status:
            return format_html(
                '<span style="color:orange">&#9679; غير متاح</span>'
            )
        return format_html('<span style="color:#bbb">&#9675; غير معروف</span>')

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['map_staff_url'] = 'map-staff/'
        return super().changelist_view(request, extra_context=extra_context)

    @admin.display(description='نوع البوابة')
    def gateway_type_badge(self, obj):
        if obj.extension_type != 'gateway':
            return ''
        labels = {
            'mobile':   ('<span style="background:#fce4ec;color:#880e4f;'
                         'padding:2px 8px;border-radius:99px;font-size:.8em">'
                         '&#128241; موبايل</span>'),
            'landline': ('<span style="background:#e8eaf6;color:#283593;'
                         'padding:2px 8px;border-radius:99px;font-size:.8em">'
                         '&#128222; أرضي</span>'),
            'sip':      ('<span style="background:#e0f2f1;color:#004d40;'
                         'padding:2px 8px;border-radius:99px;font-size:.8em">'
                         'SIP</span>'),
        }
        html = labels.get(obj.gateway_type, '')
        if html:
            return format_html(html)
        return ''


@admin.register(PBXQueue)
class PBXQueueAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'branch', 'is_active']
    list_filter  = ['is_active']


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display  = ['caller_number', 'direction', 'state', 'agent',
                     'customer', 'talk_seconds', 'started_at']
    list_filter   = ['direction', 'state']
    search_fields = ['caller_number', 'caller_name', 'customer__name']
    raw_id_fields = ['agent', 'customer', 'call_log', 'queue']
    readonly_fields = ['unique_id', 'linked_id', 'wait_seconds', 'talk_seconds',
                       'started_at', 'answered_at', 'ended_at', 'call_log']


@admin.register(PBXEvent)
class PBXEventAdmin(admin.ModelAdmin):
    list_display  = ['event_type', 'caller_id_num', 'extension',
                     'queue_name', 'unique_id', 'received_at']
    list_filter   = ['event_type']
    search_fields = ['caller_id_num', 'unique_id']
    readonly_fields = [f.name for f in PBXEvent._meta.get_fields()
                       if hasattr(f, 'name')]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
