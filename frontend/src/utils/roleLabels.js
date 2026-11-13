// Arabic role names, shared by the user screen and the SOFTECH-load labels.
// Every key in apps/users/models.py ROLE_CHOICES must be here: the user screen builds its role
// dropdown from this table, so a missing key is a role nobody can assign (roleLabels.test.js).
export const ROLE_LABELS = {
  admin:           'مدير النظام',
  call_center:     'كول سنتر',
  pharmacist:      'صيدلاني',
  salesperson:     'مندوب مبيعات',
  purchasing:      'مشتريات',
  delivery:        'توصيل',
  viewer:          'مشاهد فقط',
  supervisor:      'مشرف',
  quality_manager: 'مدير الجودة',
  accountant:      'محاسب',
}
