"""
management command: seed_holidays

Seeds the EgyptianHoliday table with known Egyptian official (national) holidays
and a placeholder set of 2024/2025/2026 Islamic holiday approximations.

Safe to re-run: uses update_or_create — no duplicates.
"""
from django.core.management.base import BaseCommand
from apps.cheques.models import EgyptianHoliday
from apps.cheques.engine import invalidate_holiday_cache


NATIONAL_HOLIDAYS = [
    # (month, day, name_ar, name_en)
    (1, 7,  'عيد الميلاد المجيد (الأرثوذكسي)',   'Coptic Christmas'),
    (1, 25, 'عيد ثورة يناير',                     'January 25 Revolution Day'),
    (4, 25, 'عيد تحرير سيناء',                    'Sinai Liberation Day'),
    (5, 1,  'عيد العمال',                         'Labour Day'),
    (7, 23, 'عيد ثورة يوليو',                     'July 23 Revolution Day'),
    (10, 6, 'عيد القوات المسلحة (تحرير أكتوبر)',  'Armed Forces Day'),
]

# Islamic holidays — approximate Gregorian dates per year
# Source: Egyptian Ministry of Religious Endowments approximate calendars
ISLAMIC_HOLIDAYS = [
    # 2024
    ('2024-04-08', 'الإسراء والمعراج',             'Isra and Mi\'raj'),
    ('2024-04-09', 'الإسراء والمعراج (إجازة)',     'Isra and Mi\'raj Holiday'),
    ('2024-04-10', 'شم النسيم / أول رمضان',       'Sham El Nessim / Ramadan start'),
    ('2024-04-11', 'شم النسيم',                   'Sham El Nessim'),
    ('2024-04-10', 'شم النسيم',                   'Sham El Nessim'),
    ('2024-04-06', 'شم النسيم',                   'Sham El Nessim 2024'),
    ('2024-04-08', 'عيد الفطر (الأول)',            'Eid Al-Fitr Day 1'),
    ('2024-04-09', 'عيد الفطر (الثاني)',           'Eid Al-Fitr Day 2'),
    ('2024-04-10', 'عيد الفطر (الثالث)',           'Eid Al-Fitr Day 3'),
    ('2024-06-15', 'عيد الأضحى (الأول)',           'Eid Al-Adha Day 1'),
    ('2024-06-16', 'عيد الأضحى (الثاني)',          'Eid Al-Adha Day 2'),
    ('2024-06-17', 'عيد الأضحى (الثالث)',          'Eid Al-Adha Day 3'),
    ('2024-07-07', 'رأس السنة الهجرية',            'Islamic New Year'),
    ('2024-09-15', 'المولد النبوي الشريف',         'Prophet\'s Birthday'),
    # 2025
    ('2025-03-28', 'عيد الفطر (الأول) 2025',       'Eid Al-Fitr 2025 Day 1'),
    ('2025-03-29', 'عيد الفطر (الثاني) 2025',      'Eid Al-Fitr 2025 Day 2'),
    ('2025-03-30', 'عيد الفطر (الثالث) 2025',      'Eid Al-Fitr 2025 Day 3'),
    ('2025-04-20', 'شم النسيم 2025',               'Sham El Nessim 2025'),
    ('2025-06-05', 'عيد الأضحى (الأول) 2025',      'Eid Al-Adha 2025 Day 1'),
    ('2025-06-06', 'عيد الأضحى (الثاني) 2025',     'Eid Al-Adha 2025 Day 2'),
    ('2025-06-07', 'عيد الأضحى (الثالث) 2025',     'Eid Al-Adha 2025 Day 3'),
    ('2025-06-26', 'رأس السنة الهجرية 2025',       'Islamic New Year 2025'),
    ('2025-09-04', 'المولد النبوي الشريف 2025',    'Prophet\'s Birthday 2025'),
    # 2026
    ('2026-03-17', 'عيد الفطر (الأول) 2026',       'Eid Al-Fitr 2026 Day 1'),
    ('2026-03-18', 'عيد الفطر (الثاني) 2026',      'Eid Al-Fitr 2026 Day 2'),
    ('2026-03-19', 'عيد الفطر (الثالث) 2026',      'Eid Al-Fitr 2026 Day 3'),
    ('2026-04-05', 'شم النسيم 2026',               'Sham El Nessim 2026'),
    ('2026-05-26', 'عيد الأضحى (الأول) 2026',      'Eid Al-Adha 2026 Day 1'),
    ('2026-05-27', 'عيد الأضحى (الثاني) 2026',     'Eid Al-Adha 2026 Day 2'),
    ('2026-05-28', 'عيد الأضحى (الثالث) 2026',     'Eid Al-Adha 2026 Day 3'),
    ('2026-06-16', 'رأس السنة الهجرية 2026',       'Islamic New Year 2026'),
    ('2026-08-25', 'المولد النبوي الشريف 2026',    'Prophet\'s Birthday 2026'),
]


class Command(BaseCommand):
    help = 'Seed Egyptian banking holidays (safe to re-run)'

    def handle(self, *args, **options):
        created_total = 0

        # National / annual holidays (years 2020-2030)
        from datetime import date as Date
        for year in range(2020, 2031):
            for month, day, name_ar, name_en in NATIONAL_HOLIDAYS:
                try:
                    d = Date(year, month, day)
                except ValueError:
                    continue
                _, created = EgyptianHoliday.objects.update_or_create(
                    date=d,
                    defaults=dict(
                        name_ar=name_ar,
                        name_en=name_en,
                        holiday_type='national',
                        is_annual=True,
                    ),
                )
                if created:
                    created_total += 1

        # Islamic holidays (specific dates)
        seen_dates = set()
        for date_str, name_ar, name_en in ISLAMIC_HOLIDAYS:
            if date_str in seen_dates:
                continue
            seen_dates.add(date_str)
            from datetime import datetime
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
            _, created = EgyptianHoliday.objects.update_or_create(
                date=d,
                defaults=dict(
                    name_ar=name_ar,
                    name_en=name_en,
                    holiday_type='islamic',
                    is_annual=False,
                ),
            )
            if created:
                created_total += 1

        invalidate_holiday_cache()
        self.stdout.write(
            self.style.SUCCESS(
                f'Holiday seeding complete. {created_total} new records created. '
                f'Total holidays in DB: {EgyptianHoliday.objects.count()}'
            )
        )
