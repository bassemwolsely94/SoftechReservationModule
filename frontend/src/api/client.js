import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token to every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
api.interceptors.response.use(
  res => res,
  async err => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post('/api/auth/refresh/', { refresh })
          localStorage.setItem('access_token', data.access)
          original.headers.Authorization = `Bearer ${data.access}`
          return api(original)
        } catch {
          localStorage.clear()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(err)
  }
)

export default api

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (username, password, deviceToken) =>
    api.post('/auth/login/', { username, password, device_token: deviceToken || undefined }),
  me: () => api.get('/auth/me/'),

  // ── Two-factor (TOTP) ──
  verify2fa: (mfaToken, code, rememberDevice) =>
    api.post('/auth/2fa/verify/', { mfa_token: mfaToken, code, remember_device: !!rememberDevice }),
  setup2fa:  (mfaToken) => api.post('/auth/2fa/setup/',  mfaToken ? { mfa_token: mfaToken } : {}),
  enable2fa: (code, mfaToken) =>
    api.post('/auth/2fa/enable/', { code, ...(mfaToken ? { mfa_token: mfaToken } : {}) }),
  disable2fa:(password, code) => api.post('/auth/2fa/disable/', { password, code }),
  status2fa: () => api.get('/auth/2fa/status/'),
}

// ── Reservations ──────────────────────────────────────────────────────────────

export const reservationsApi = {
  list:         (params) => api.get('/reservations/', { params }),
  get:          (id) => api.get(`/reservations/${id}/`),
  create:       (data) => api.post('/reservations/', data),
  update:       (id, data) => api.patch(`/reservations/${id}/`, data),
  changeStatus: (id, status, note = '') =>
    api.post(`/reservations/${id}/change-status/`, { status, note }),
  dashboard:    (params) => api.get('/reservations/dashboard/', { params }),

  // Chatter — supports text, image attachment, and voice note (FormData or JSON)
  activities:   (id) => api.get(`/reservations/${id}/activities/`),
  logActivity:  (id, formData) => {
    const isFormData = formData instanceof FormData
    return api.post(`/reservations/${id}/log/`, formData, {
      headers: isFormData ? { 'Content-Type': 'multipart/form-data' } : {},
    })
  },

  // Downpayments
  getDownpayments: (id) => api.get(`/reservations/${id}/downpayments/`),
  addDownpayment:  (id, data) => api.post(`/reservations/${id}/downpayments/`, data),

  // Delete a chatter activity (soft-delete — tombstone stays)
  deleteActivity:  (id, activityId) => api.delete(`/reservations/${id}/activities/${activityId}/`),

  // Print receipt — returns structured data; frontend calls window.print()
  printReceipt:    (id) => api.get(`/reservations/${id}/print/`),

  // WhatsApp share — returns { message_text }; frontend opens wa.me
  shareWhatsapp:   (id) => api.post(`/reservations/${id}/share-whatsapp/`),

  // Extra images (multi-upload)
  getImages:    (id) => api.get(`/reservations/${id}/images/`),
  uploadImages: (id, formData) =>
    api.post(`/reservations/${id}/images/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  deleteImage:  (reservationId, imageId) =>
    api.delete(`/reservations/${reservationId}/images/${imageId}/delete/`),

  // ERP match verification (post-fulfillment — doccode 115 مبيعات نقدية)
  checkErpMatch: (id) => api.post(`/reservations/${id}/check-erp-match/`),

  // Reservation lines (basket)
  getLines:     (id) => api.get(`/reservations/${id}/lines/`),
  addLine:      (id, data) => api.post(`/reservations/${id}/lines/`, data),
  deleteLine:   (id, lineId) => api.delete(`/reservations/${id}/lines/${lineId}/delete/`),

  // Merge duplicate reservations
  merge:        (id, targetId) => api.post(`/reservations/${id}/merge/`, { target_id: targetId }),

  // Bulk actions (assign / change_status / export)
  bulk:         (data) => api.post('/reservations/bulk/', data, {
    responseType: data.action === 'export' ? 'blob' : 'json',
  }),

  // Analytics
  analytics:    (params) => api.get('/reservations/analytics/', { params }),

  // Customer reservation history (last 10 for same customer)
  customerHistory: (id) => api.get(`/reservations/${id}/customer-history/`),

  // Create with force (bypasses duplicate check)
  createForce:  (data) => api.post('/reservations/?force=true', data),
}

// ── Customers ─────────────────────────────────────────────────────────────────

export const customersApi = {
  list:       (params) => api.get('/customers/', { params }),
  get:        (id) => api.get(`/customers/${id}/`),
  create:     (data) => api.post('/customers/', data),
  update:     (id, data) => api.patch(`/customers/${id}/`, data),

  // purchases — pass doc_code param if filtering
  purchases:  (id, docCode) =>
    api.get(`/customers/${id}/purchases/`,
      docCode ? { params: { doc_code: docCode } } : {}),

  reservations: (id) => api.get(`/customers/${id}/reservations/`),
  unmetDemand:  (id) => api.get(`/customers/${id}/unmet-demand/`),
  topItems:     (id) => api.get(`/customers/${id}/top_items/`),
  addNote:      (id, note) => api.post(`/customers/${id}/notes/`, { note }),
  deleteNote:   (customerId, noteId) =>
    api.delete(`/customers/${customerId}/notes/${noteId}/`),
  updateConditions: (id, chronic_conditions) =>
    api.patch(`/customers/${id}/update_conditions/`, { chronic_conditions }),

  // 360° patient profile — aggregates chronic meds, timeline, purchases, etc.
  patientProfile:    (id)         => api.get(`/customers/${id}/patient-profile/`),
  timeline:          (id, limit = 50) => api.get(`/customers/${id}/timeline/`, { params: { limit } }),

  // Health profile (CustomerHealthProfile — structured chronic conditions)
  healthProfile:     (id)         => api.get(`/customers/${id}/health-profile/`),
  updateHealthProfile:(id, data)  => api.patch(`/customers/${id}/health-profile/`, data),
  refreshHealth:     (id)         => api.post(`/customers/${id}/refresh-health/`),

  // Intelligence
  recommendations:   (id, params) => api.get(`/customers/${id}/recommendations/`, { params }),
  churnAtRisk:       (params)     => api.get('/customers/churn-at-risk/', { params }),
}


// ── Items ─────────────────────────────────────────────────────────────────────

export const itemsApi = {
  list:  (params) => api.get('/items/', { params }),
  get:   (id) => api.get(`/items/${id}/`),
  stock: (id) => api.get(`/items/${id}/stock/`),

  /**
   * Wildcard-aware item search.
   * q supports SOFTECH-style wildcards: "pan*500", "*cillin", "amox*"
   * Optional: branch_id → includes qty_at_branch in results.
   */
  wildcardSearch: (q, branchId = null) =>
    api.get('/items/softech-search/', {
      params: { q, ...(branchId ? { branch_id: branchId } : {}) },
    }),

  /**
   * Returns all distinct filter dropdown options for the items catalog.
   * Response: { medicine_types, categories, suppliers, families,
   *             insurance_types, item_level_options, trans_options,
   *             nosale_classif_options, store_classif_options }
   */
  filterOptions: () => api.get('/items/filter-options/'),

  // Full intelligence aggregator (all modules in one call)
  fullIntel:     (softech_id)            => api.get(`/items/${softech_id}/intel/`),

  // Ingredient maps (chronic module write via catalog API)
  listIngredients:  (softech_id)         => api.get(`/items/${softech_id}/ingredients/`),
  addIngredient:    (softech_id, data)   => api.post(`/items/${softech_id}/ingredients/`, data),
  deleteIngredient: (softech_id, map_id) => api.delete(`/items/${softech_id}/ingredients/${map_id}/`),

  // Bundles
  listBundles:   (params) => api.get('/items/bundles/', { params }),
  getBundle:     (id)     => api.get(`/items/bundles/${id}/`),

  // Variant groups
  listVariantGroups: (params) => api.get('/items/variant-groups/', { params }),
}

// ── Branches ──────────────────────────────────────────────────────────────────

export const branchesApi = {
  list:    (params) => api.get('/branches/', { params }),
  listAll: ()       => api.get('/branches/', { params: { all: '1' } }),  // admin: includes inactive

  // Branch fields — admin only
  update:  (branchId, data) => api.patch(`/branches/${branchId}/`, data),

  // BranchSettings feature flags — admin only
  getSettings:    (branchId) => api.get(`/branches/${branchId}/settings/`),
  updateSettings: (branchId, data) => api.patch(`/branches/${branchId}/settings/`, data),
}

// ── Sync ──────────────────────────────────────────────────────────────────────

export const syncApi = {
  status:       () => api.get('/sync/status/'),
  trigger:      (full = false) => api.post('/sync/trigger/', { full }),
  logs:         () => api.get('/sync/logs/'),
  branchHealth: (probe = false) => api.get('/sync/branch-health/', probe ? { params: { probe: 1 } } : undefined),
  schedulerStatus: () => api.get('/sync/scheduler-status/'),
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export const dashboardApi = {
  summary:   (params) => api.get('/dashboard/summary/', { params }),
  followups: ()       => api.get('/dashboard/followups/'),
  purchasing:(days)   => api.get('/dashboard/purchasing/', { params: { days } }),
}


// ── Personal Dashboard (per-user SOFTECH identity claims + configurable widgets) ──

export const personalApi = {
  // Person search for claiming an identity — kind: 'supplier' | 'customer'
  searchPersons: (q, kind) => api.get('/personal/persons/search/', { params: { q, ...(kind ? { kind } : {}) } }),

  // Identity claims
  identities:       ()      => api.get('/personal/identities/'),
  claimIdentity:    (data)  => api.post('/personal/identities/', data),
  deleteIdentity:   (id)    => api.delete(`/personal/identities/${id}/`),
  // Admin review queue
  pendingIdentities:()      => api.get('/personal/identities/pending/'),
  reviewIdentity:   (id, action, note) =>
    api.post(`/personal/identities/${id}/review/`, { action, note }),

  // Widgets
  catalog:      ()          => api.get('/personal/widgets/catalog/'),
  widgets:      ()          => api.get('/personal/widgets/'),
  addWidget:    (data)      => api.post('/personal/widgets/', data),
  updateWidget: (id, data)  => api.patch(`/personal/widgets/${id}/`, data),
  deleteWidget: (id)        => api.delete(`/personal/widgets/${id}/`),
  layout:       (items)     => api.post('/personal/widgets/layout/', items),
  widgetData:   (id, refresh) =>
    api.get(`/personal/widgets/${id}/data/`, refresh ? { params: { refresh: 1 } } : {}),

  // Document remarks (stktransm.comments) — read rides in widgetData; this is the write
  capabilities:  ()     => api.get('/personal/me/capabilities/'),
  setComment:    (data) => api.post('/personal/documents/comment/', data),
  setChequeNote: (data) => api.post('/personal/cheques/note/', data),
  setRevision:   (data) => api.post('/personal/revision/', data),
}

// ── Notifications ─────────────────────────────────────────────────────────────

export const targetsApi = {
  list:   (params = {}) => api.get('/incentives/targets/', { params }),
  create: (data)        => api.post('/incentives/targets/', data),
  update: (id, data)    => api.patch(`/incentives/targets/${id}/`, data),
  remove: (id)          => api.delete(`/incentives/targets/${id}/`),
}

// Branch-KPI forecasting (doc 16)
export const kpiApi = {
  board: (params = {}) => api.get('/forecasting/kpi-board/', { params }),
}

// Forecast scenarios (doc 16, Phase 3)
export const forecastApi = {
  list:    (params = {}) => api.get('/forecasting/scenarios/', { params }),
  create:  (data)        => api.post('/forecasting/scenarios/', data),
  get:     (id)          => api.get(`/forecasting/scenarios/${id}/`),
  update:  (id, data)    => api.patch(`/forecasting/scenarios/${id}/`, data),
  remove:  (id)          => api.delete(`/forecasting/scenarios/${id}/`),
  factors: (id, rows)    => api.patch(`/forecasting/scenarios/${id}/factors/`, rows),
  generate:(id)          => api.post(`/forecasting/scenarios/${id}/generate/`),
  results: (id, params={})=> api.get(`/forecasting/scenarios/${id}/results/`, { params }),
  commit:  (id)          => api.post(`/forecasting/scenarios/${id}/commit/`),
  // backtest — model accuracy on history
  backtestList:  ()      => api.get('/forecasting/backtest/'),
  backtestRun:   (data={})=> api.post('/forecasting/backtest/run/', data),
}

// Narrative insights / automated audit (doc 18)
export const insightsApi = {
  reports:  (params = {}) => api.get('/insights/reports/', { params }),
  report:   (id)          => api.get(`/insights/reports/${id}/`),
  generate: (data = {})   => api.post('/insights/reports/generate/', data),
  scopes:   (id)          => api.get(`/insights/reports/${id}/scopes/`),
  scoped:   (id, params)  => api.get(`/insights/reports/${id}/scoped/`, { params }),
  rules:    ()            => api.get('/insights/rules/'),
  updateRule: (id, data)  => api.patch(`/insights/rules/${id}/`, data),
}

export const notificationsApi = {
  list:        (params = {}) => api.get('/notifications/', { params }),
  unreadCount: (params = {}) => api.get('/notifications/unread-count/', { params }),
  categoryCounts: ()         => api.get('/notifications/category-counts/'),
  markRead:    (id)          => api.post(`/notifications/${id}/read/`),
  markAllRead: (params = {}) => api.post('/notifications/mark-all-read/', null, { params }),
  deleteOne:   (id)          => api.delete(`/notifications/${id}/`),
  clearAll:    ()            => api.delete('/notifications/clear-all/'),
  deleteOld:   ()            => api.delete('/notifications/delete-old/'),

  // Snooze ("remind me later" on a notification)
  snooze:      (id, body)    => api.post(`/notifications/${id}/snooze/`, body),

  // Bulk actions (inbox): {ids, action: 'read'|'delete'|'snooze', minutes?}
  bulk:        (body)        => api.post('/notifications/bulk/', body),

  // Announcements / internal broadcast
  announcements:       ()        => api.get('/notifications/announcements/'),
  createAnnouncement:  (data)    => api.post('/notifications/announcements/', data),
  ackAnnouncement:     (id)      => api.post(`/notifications/announcements/${id}/ack/`),
  announcementStats:   (id)      => api.get(`/notifications/announcements/${id}/`),
  deleteAnnouncement:  (id)      => api.delete(`/notifications/announcements/${id}/`),

  // Personal reminders (private, lightweight)
  reminders:        (params = {}) => api.get('/notifications/reminders/', { params }),
  createReminder:   (data)        => api.post('/notifications/reminders/', data),
  deleteReminder:   (id)          => api.delete(`/notifications/reminders/${id}/`),

  // User notification preferences
  getPreferences:    ()       => api.get('/notifications/preferences/'),
  updatePreferences: (data)   => api.patch('/notifications/preferences/', data),

  // Web Push (VAPID) — browser push subscriptions
  vapidPublicKey:  ()          => api.get('/notifications/push/vapid-public-key/'),
  pushSubscribe:   (sub)       => api.post('/notifications/push/subscribe/', sub),
  pushUnsubscribe: (body)      => api.post('/notifications/push/unsubscribe/', body),

  // Chatter
  chatterList: (modelName, recordId, params = {}) =>
    api.get(`/notifications/chatter/${modelName}/${recordId}/`, { params }),
  chatterPost: (modelName, recordId, message) =>
    api.post(`/notifications/chatter/${modelName}/${recordId}/post/`, { message }),
  // files: { attachment?, voiceNote? } — voiceNote goes to the dedicated field so
  // an image AND a voice note can ride the same message.
  chatterPostWithFile: (modelName, recordId, message, files = {}) => {
    const { attachment, voiceNote } = files
    const fd = new FormData()
    if (message)    fd.append('message', message)
    if (attachment) fd.append('attachment', attachment)
    if (voiceNote)  fd.append('voice_note', voiceNote)
    return api.post(
      `/notifications/chatter/${modelName}/${recordId}/post/`,
      fd,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
  },
}

// ── QA branch inspections ───────────────────────────────────────────────────
export const qaApi = {
  templates: ()         => api.get('/qa/templates/'),
  list:      (params)   => api.get('/qa/inspections/', { params }),
  get:       (id)       => api.get(`/qa/inspections/${id}/`),
  create:    (data)     => api.post('/qa/inspections/', data),
  update:    (id, data) => api.patch(`/qa/inspections/${id}/`, data),
  submit:    (id, data) => api.post(`/qa/inspections/${id}/submit/`, data),
}

// ── Transfers ─────────────────────────────────────────────────────────────────

export const transfersApi = {
  // CRUD
  list:    (params) => api.get('/transfers/', { params }),
  get:     (id)     => api.get(`/transfers/${id}/`),
  create:  (data)   => api.post('/transfers/', data),
  update:  (id, data) => api.patch(`/transfers/${id}/`, data),
  delete:  (id)     => api.delete(`/transfers/${id}/`),

  // State machine actions
  submit:     (id)         => api.post(`/transfers/${id}/submit/`),
  approve:    (id, data)   => api.post(`/transfers/${id}/approve/`, data || {}),
  reject:     (id, data)   => api.post(`/transfers/${id}/reject/`, data),
  revision:   (id, data)   => api.post(`/transfers/${id}/revision/`, data),
  sendToERP:  (id, data)   => api.post(`/transfers/${id}/send-to-erp/`, data),
  complete:   (id, data)   => api.post(`/transfers/${id}/complete/`, data || {}),
  cancel:     (id)         => api.post(`/transfers/${id}/cancel/`),

  // Item management
  addItem:    (id, data)   => api.post(`/transfers/${id}/items/`, data),
  removeItem: (id, itemId) => api.delete(`/transfers/${id}/items/${itemId}/`),
  updateItem: (id, itemId, data) => api.patch(`/transfers/${id}/items/${itemId}/`, data),

  // Chatter — supports text, image, and voice note
  getMessages:  (id)       => api.get(`/transfers/${id}/messages/`),
  sendMessage:  (id, data) => {
    const isFormData = data instanceof FormData
    return api.post(`/transfers/${id}/messages/`, data, {
      headers: isFormData ? { 'Content-Type': 'multipart/form-data' } : {},
    })
  },

  // Stock lookup
  itemStock:  (itemId)     => api.get('/transfers/item_stock/', { params: { item_id: itemId } }),

  // Delivery dispatch — POST { delivery_person_name }
  dispatch: (id, data) => api.post(`/transfers/${id}/record-dispatch/`, data),

  // ERP stktrans reference validation — POST { doc_number }
  validateErpRef: (id, data) => api.post(`/transfers/${id}/validate-erp-ref/`, data),

  // Delete a chatter message (soft-delete — tombstone stays)
  deleteMessage:  (id, messageId) => api.delete(`/transfers/${id}/messages/${messageId}/`),

  // Print receipt — returns structured receipt data
  printReceipt:   (id) => api.get(`/transfers/${id}/print/`),

  // WhatsApp share — returns { message_text }
  shareWhatsapp:  (id) => api.post(`/transfers/${id}/share-whatsapp/`),

  // ERP match verification — admin/purchasing manual trigger
  checkErpMatch: (id) => api.post(`/transfers/${id}/check-erp-match/`),

  // Analytics & reporting
  analytics:         (params) => api.get('/transfers/analytics/', { params }),
  discrepancyReport: ()       => api.get('/transfers/discrepancy-report/'),
}




export const purchasingApi = {
  // Engine runs (audit log)
  runs:        (params)  => api.get('/purchasing/runs/', { params }),
  latestRun:   ()        => api.get('/purchasing/runs/latest/'),
  lastAttempt: ()        => api.get('/purchasing/runs/latest/', { params: { any: 1 } }),
  activeRun:   ()        => api.get('/purchasing/runs/active/'),

  // Trigger a new engine run.
  // data: { params?: { weight_30d, weight_90d, weight_365d, abc_a_threshold, abc_b_threshold } }
  // Omit data (or pass {}) to use the current saved EngineConfig defaults.
  triggerRun:  (data = {}) => api.post('/purchasing/trigger/', data),
  catchupSync: ()          => api.post('/purchasing/catchup/'),

  // Pre-computed summary stats for dashboard header cards (server-side aggregation)
  // Returns: { total_items, count_A/B/C/X, items_with_gap, total_gap_value, total_monthly_value, ... }
  summary:     ()        => api.get('/purchasing/summary/'),

  // Per-item × per-branch metrics
  // params: { branch, abc_class, needs_purchase, search, ordering, page, page_size }
  metrics:     (params)  => api.get('/purchasing/metrics/', { params }),

  // Cross-branch aggregated (ABC dashboard)
  // params: { abc_class, search, ordering, page, page_size }
  aggregated:  (params)  => api.get('/purchasing/aggregated/', { params }),

  // Export — returns file download (arraybuffer for xlsx, blob for csv)
  // params: { format: 'xlsx'|'csv', view: 'branch'|'network'|'aggregated'|'metrics'|'pivot', branch?, abc_class? }
  export:      (params)  => api.get('/purchasing/export/', {
    params,
    responseType: params.format === 'csv' ? 'blob' : 'arraybuffer',
  }),
  advancedExport: (params) => api.get('/purchasing/advanced-export/', { params, responseType: 'arraybuffer' }),
  advancedPivotExport: (params) => api.get('/purchasing/advanced-pivot-export/', { params, responseType: 'arraybuffer' }),

  // ── Market shortage detector (نواقص السوق) ─────────────────────────────────
  shortageCandidates: (params)      => api.get('/purchasing/shortage/candidates/', { params }),
  shortageDeltas:     ()            => api.get('/purchasing/shortage/deltas/'),
  shortageConfirmed:  (params)      => api.get('/purchasing/shortage/confirmed/', { params }),
  shortageDismissed:  ()            => api.get('/purchasing/shortage/dismissed/'),
  shortageMedTypes:   ()            => api.get('/purchasing/shortage/med-types/'),
  shortageSearch:     (q)           => api.get('/purchasing/shortage/search/', { params: { q } }),
  shortageFlag:       (data)        => api.post('/purchasing/shortage/flag/', data),
  shortageUnflag:     (itemId)      => api.post('/purchasing/shortage/unflag/', { item_id: itemId }),
  shortageDismiss:    (data)        => api.post('/purchasing/shortage/dismiss/', data),
  shortageRetrieve:   (itemId)      => api.post('/purchasing/shortage/retrieve/', { item_id: itemId }),
  shortageExport:     (params)      => api.get('/purchasing/shortage/export/', { params, responseType: 'arraybuffer' }),
  shortageWhatsapp:   (params)      => api.get('/purchasing/shortage/whatsapp/', { params }),
  shortageSuggestMatches: (itemId)  => api.get('/purchasing/shortage/suggest-matches/', { params: { item_id: itemId } }),
  shortageTrends:     ()            => api.get('/purchasing/shortage/trends/'),

  // EngineConfig singleton — GET returns current weights/thresholds; PATCH updates them (admin only)
  config:       ()       => api.get('/purchasing/config/'),
  updateConfig: (data)   => api.patch('/purchasing/config/', data),

  // ── Module 2 — Transfer recommendations ────────────────────────────────
  // Latest run metadata (linked to the latest demand run)
  transferRecRun:     ()       => api.get('/purchasing/transfer-recs/run/'),
  // Summary stats: counts, total value, by_abc, top_items
  transferRecSummary: ()       => api.get('/purchasing/transfer-recs/summary/'),
  // Filterable list: ?abc_class=A&status=pending&from_branch=&to_branch=&search=
  transferRecs:       (params) => api.get('/purchasing/transfer-recs/', { params }),
  // Approve / reject a single recommendation
  transferRecStatus:  (id, data) => api.patch(`/purchasing/transfer-recs/${id}/status/`, data),

  // Filter-options — distinct values for dropdown population
  // Returns: { medicine_types, supplier_codes, family_codes, categories }
  filterOptions: () => api.get('/purchasing/filter-options/'),

  // ── Module 13 — Lost Sales Intelligence ────────────────────────────────
  // Latest LostSalesRun audit record
  lostSalesRun:     ()       => api.get('/purchasing/lost-sales/run/'),
  // Summary KPIs: total_lost_revenue, top_items, root_cause_breakdown, avg_availability
  lostSalesSummary: ()       => api.get('/purchasing/lost-sales/summary/'),
}


export const demandApi = {
  // CRUD
  list:   (params) => api.get('/demand/', { params }),
  get:    (id)     => api.get(`/demand/${id}/`),
  create: (data)   => api.post('/demand/', data),
  update: (id, data) => api.patch(`/demand/${id}/`, data),

  // State machine
  assign:          (id, data) => api.post(`/demand/${id}/assign/`, data),
  followUp:        (id, data) => api.post(`/demand/${id}/follow-up/`, data),
  stockETA:        (id, data) => api.post(`/demand/${id}/stock-eta/`, data),
  suggestTransfer: (id, data) => api.post(`/demand/${id}/suggest-transfer/`, data),
  flagPurchasing:  (id, data) => api.post(`/demand/${id}/flag-purchasing/`, data),
  fulfill:         (id, data) => api.post(`/demand/${id}/fulfill/`, data),
  markLost:        (id, data) => api.post(`/demand/${id}/lost/`, data),
  cancel:          (id, data) => api.post(`/demand/${id}/cancel/`, data),

  // Items
  addItem:    (id, data)   => api.post(`/demand/${id}/items/`, data),
  removeItem: (id, itemId) => api.delete(`/demand/${id}/items/${itemId}/`),

  // Logs
  getLogs: (id)         => api.get(`/demand/${id}/logs/`),
  addLog:  (id, data)   => api.post(`/demand/${id}/logs/`, data),

  // Follow-ups
  getFollowups:      (id)         => api.get(`/demand/${id}/followups/`),
  scheduleFollowup:  (id, data)   => api.post(`/demand/${id}/schedule-followup/`, data),
  completeFollowup:  (id, taskId, data) => api.post(`/demand/${id}/followups/${taskId}/complete/`, data),

  // ERP
  enrichFromERP: (id)    => api.post(`/demand/${id}/enrich/`),
  erpLookup:     (params) => api.get('/demand/erp-lookup/', { params }),

  // Phase 3 — therapeutic substitution at capture
  substitutes:   (params) => api.get('/demand/substitutes/', { params }),

  // Recovery loop (Phase 1)
  recoveryQueue: (params)            => api.get('/demand/recovery-queue/', { params }),
  recoverItem:   (id, itemId, data) => api.post(`/demand/${id}/items/${itemId}/recover/`, data || {}),
  markNotified:  (id, itemId, data) => api.post(`/demand/${id}/items/${itemId}/notified/`, data || {}),
  optOutItem:    (id, itemId, data) => api.post(`/demand/${id}/items/${itemId}/opt-out/`, data || {}),
  disqualifyItem:(id, itemId, data) => api.post(`/demand/${id}/items/${itemId}/disqualify/`, data),
  requalifyItem: (id, itemId)       => api.post(`/demand/${id}/items/${itemId}/requalify/`),

  // Demand ↔ Reservation bridge (Phase 1b)
  itemToReservation: (id, itemId)   => api.post(`/demand/${id}/items/${itemId}/to-reservation/`),
  fromReservation:   (data)         => api.post('/demand/from-reservation/', data),

  // Dashboard
  dashboard: (params) => api.get('/demand/dashboard/', { params }),
  // Phase 2 — confirmed-vs-inferred lost value reconciliation
  reconciliation: () => api.get('/demand/lost-value-reconciliation/'),

  // Purchase suggestions (demand-driven reorder)
  purchaseSuggestions:     ()     => api.get('/demand/purchase-suggestions/'),
  pushPurchaseSuggestions: (data) => api.post('/demand/purchase-suggestions/push/', data || {}),
  // Capture leaderboard + bulk actions
  captureLeaderboard: (params) => api.get('/demand/capture-leaderboard/', { params }),
  bulkAction:         (data)   => api.post('/demand/bulk/', data),
  // Intelligence panels + shelf QR
  substitutionAnalytics: (params) => api.get('/demand/substitution-analytics/', { params }),
  priceObjections:       (params) => api.get('/demand/price-objections/', { params }),
  shelfQr:               (params) => api.get('/demand/shelf-qr/', { params }),
}

// ── Chronic Classifier ────────────────────────────────────────────────────────

// ── Invoices ──────────────────────────────────────────────────────────────────

export const invoicesApi = {
  // Invoice CRUD
  list:          (params)       => api.get('/invoices/invoices/', { params }),
  get:           (id)           => api.get(`/invoices/invoices/${id}/`),
  create:        (formData)     => api.post('/invoices/invoices/', formData, {
                                    headers: { 'Content-Type': 'multipart/form-data' },
                                  }),
  updateHeader:  (id, data)     => api.patch(`/invoices/invoices/${id}/update-header/`, data),

  // Line management
  addLine:       (id, data)     => api.post(`/invoices/invoices/${id}/add-line/`, data),
  updateLine:    (id, lid, data)=> api.patch(`/invoices/invoices/${id}/lines/${lid}/`, data),
  deleteLine:    (id, lid)      => api.delete(`/invoices/invoices/${id}/lines/${lid}/delete/`),
  lineMatches:   (id, lid)      => api.get(`/invoices/invoices/${id}/lines/${lid}/matches/`),
  learnMapping:  (id, lid, data = {}) => api.post(`/invoices/invoices/${id}/lines/${lid}/learn/`, data),

  // OCR
  runOcr:        (id)           => api.post(`/invoices/invoices/${id}/run-ocr/`),

  // Anomaly check — returns { count, anomalies: [{line_id, type, message, severity}] }
  anomalies:     (id)           => api.get(`/invoices/invoices/${id}/anomalies/`),

  // Status transitions
  confirm:       (id)           => api.post(`/invoices/invoices/${id}/confirm/`),
  reject:        (id)           => api.post(`/invoices/invoices/${id}/reject/`),

  // SOFTECH writeback (final purchase doc, doccode 10/120)
  pushPreview:   (id)           => api.post(`/invoices/invoices/${id}/push-preview/`),
  validateErp:   (id)           => api.post(`/invoices/invoices/${id}/validate/`),
  push:          (id, force)    => api.post(`/invoices/invoices/${id}/push/`, { force: !!force }),
  reconcile:     (id)           => api.post(`/invoices/invoices/${id}/reconcile/`),
  createReturn:  (id)           => api.post(`/invoices/invoices/${id}/create-return/`),

  // Exports
  exportExcel:   (id)           => api.get(`/invoices/invoices/${id}/export-excel/`, { responseType: 'arraybuffer' }),
  exportCsv:     (id)           => api.get(`/invoices/invoices/${id}/export-csv/`,   { responseType: 'blob' }),

  // Vendor profiles
  listVendors:   (params)       => api.get('/invoices/vendors/', { params }),
  mainVendors:   ()             => api.get('/invoices/vendors/main/'),
  createVendor:  (data)         => api.post('/invoices/vendors/', data),
}

// ── Vouchers ──────────────────────────────────────────────────────────────────

export const vouchersApi = {
  // ── Core CRUD ──────────────────────────────────────────────────────────────
  list:        (params)       => api.get('/vouchers/vouchers/', { params }),
  get:         (id)           => api.get(`/vouchers/vouchers/${id}/`),
  create:      (data)         => api.post('/vouchers/vouchers/', data),
  update:      (id, data)     => api.patch(`/vouchers/vouchers/${id}/`, data),
  cancel:      (id)           => api.post(`/vouchers/vouchers/${id}/cancel/`),

  // ── Eligibility & OTP ──────────────────────────────────────────────────────
  // Check if a customer (by phone) is eligible to use a voucher
  validateEligibility: (id, data) =>
    api.post(`/vouchers/vouchers/${id}/validate/`, data),

  // Generate OTP — returns { otp_id, expires_at, whatsapp_url }
  // data = { phone, order_amount? }
  generateOtp: (id, data)    => api.post(`/vouchers/vouchers/${id}/generate-otp/`, data),

  // Verify OTP — returns VoucherRedemptionDocument on success
  // data = { code, phone, order_amount? }
  verifyOtp:   (id, data)    => api.post(`/vouchers/vouchers/${id}/verify-otp/`, data),

  // ── Assignment (voucher_category='assigned') ───────────────────────────────
  // Assign a voucher to a customer phone
  assign:      (id, data)    => api.post(`/vouchers/vouchers/${id}/assign/`, data),

  // List all assignments for a voucher
  getAssignments: (id)       => api.get(`/vouchers/vouchers/${id}/assignments/`),

  // ── Audit / Reports ────────────────────────────────────────────────────────
  redemptions: (id)          => api.get(`/vouchers/vouchers/${id}/redemptions/`),

  // Aggregate report — params: { date_from?, date_to?, branch?, voucher_id? }
  report:      (params)      => api.get('/vouchers/vouchers/report/', { params }),

  // ── POS Redemption Documents ───────────────────────────────────────────────
  // Retrieve a document by its reference_code (POS lookup)
  getDocument: (refCode)     => api.get(`/vouchers/documents/${refCode}/`),

  // Mark a document as used — data = { order_amount?, notes? }
  markDocumentUsed: (refCode, data) =>
    api.post(`/vouchers/documents/${refCode}/mark-used/`, data),

  // Trigger WhatsApp share for a document — returns { message_text, whatsapp_url }
  documentWhatsapp: (refCode) =>
    api.post(`/vouchers/documents/${refCode}/whatsapp/`),

  // Fetch receipt data (authenticated), then caller renders HTML for window.print()
  documentPrint: (refCode) => api.get(`/vouchers/documents/${refCode}/print/`),
}

// ── Shortage ──────────────────────────────────────────────────────────────────

export const shortageApi = {
  // List CRUD
  list:         (params)       => api.get('/shortage/lists/', { params }),
  get:          (id)           => api.get(`/shortage/lists/${id}/`),
  create:       (data)         => api.post('/shortage/lists/', data),

  // Item management
  addItem:      (id, data)     => api.post(`/shortage/lists/${id}/add-item/`, data),
  updateItem:   (id, iid, data)=> api.patch(`/shortage/lists/${id}/items/${iid}/`, data),
  deleteItem:   (id, iid)      => api.delete(`/shortage/lists/${id}/items/${iid}/delete/`),

  // Matching — returns top-N candidates for a ShortageItem (default top=3)
  itemMatches:  (id, iid, params = {}) => api.get(`/shortage/lists/${id}/items/${iid}/matches/`, { params }),

  // Bulk text import — { lines: ['name qty unit', ...] }
  bulkImport:   (id, data)     => api.post(`/shortage/lists/${id}/bulk-import/`, data),

  // Voice import — { transcript: 'raw speech text' }
  voiceImport:  (id, data)     => api.post(`/shortage/lists/${id}/voice-import/`, data),

  // OCR — multipart/form-data with 'image' field
  // Returns { raw_text, lines: [...], line_count }
  ocrExtract:   (id, formData) =>
    api.post(`/shortage/lists/${id}/ocr/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),

  // Internal stock check — returns transfer suggestions per confirmed item
  stockCheck:   (id)           => api.get(`/shortage/lists/${id}/stock-check/`),

  // State transitions
  submit:       (id)           => api.post(`/shortage/lists/${id}/submit/`),
  resolve:      (id)           => api.post(`/shortage/lists/${id}/resolve/`),

  // Single-list Excel export — returns arraybuffer
  exportExcel:  (id)           => api.get(`/shortage/lists/${id}/export-excel/`, { responseType: 'arraybuffer' }),
  // Comprehensive supplier matrix (a code column per main distributor + sourcing guide)
  exportSupplierMatrix: (id)   => api.get(`/shortage/lists/${id}/export-supplier-matrix/`, { responseType: 'arraybuffer' }),
  // Single-supplier purchase order carrying that supplier's own item codes
  exportSupplierPo: (id, suppcode, name) =>
    api.get(`/shortage/lists/${id}/export-supplier-po/${suppcode}/`, { params: { name }, responseType: 'arraybuffer' }),

  // Legacy CSV export — returns blob
  exportCsv:    (id)           => api.get(`/shortage/lists/${id}/export/`, { responseType: 'blob' }),

  // Aggregated view — params: { branch_ids, status, date_from, date_to }
  aggregate:    (params)       => api.get('/shortage/lists/aggregate/', { params }),

  // Aggregated Excel export — same params, returns arraybuffer
  exportAggregated: (params)   =>
    api.get('/shortage/lists/export-aggregated/', { params, responseType: 'arraybuffer' }),
}

// ── Stock Count ───────────────────────────────────────────────────────────────

export const stockCountApi = {
  // Session CRUD
  list:         (params) => api.get('/stockcount/sessions/', { params }),
  get:          (id)     => api.get(`/stockcount/sessions/${id}/`),
  create:       (data)   => api.post('/stockcount/sessions/', data),
  update:       (id, data) => api.patch(`/stockcount/sessions/${id}/`, data),
  destroy:      (id)     => api.delete(`/stockcount/sessions/${id}/`),

  // Workflow actions
  // POST → returns { item_count, items: [{item_code, item_name, item_medicine, category_name, expected_qty}] }
  previewItems:      (id)  => api.post(`/stockcount/sessions/${id}/preview-items/`),

  // POST → captures immutable snapshot; returns { item_count, snapshot_at }
  generateSnapshot:  (id)  => api.post(`/stockcount/sessions/${id}/generate-snapshot/`),

  // GET  → downloads blank count sheet (xlsx/csv); returns blob
  exportSheet:       (id)  => api.get(`/stockcount/sessions/${id}/export-sheet/`, { responseType: 'blob' }),

  // POST → multipart/form-data with 'file'; returns variance summary
  uploadResults:     (id, formData) => api.post(
    `/stockcount/sessions/${id}/upload-results/`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  ),

  // GET  → JSON variance report; ?variance_type=surplus|deficit|ok|all
  varianceReport:    (id, params) => api.get(`/stockcount/sessions/${id}/variance-report/`, { params }),

  // GET  → downloads colour-coded adjustment sheet (xlsx/csv); returns blob
  adjustmentExport:  (id)  => api.get(`/stockcount/sessions/${id}/adjustment-export/`, { responseType: 'blob' }),

  // GET  → paginated snapshots list; ?variance_type, ?search, ?page
  snapshots:         (id, params) => api.get(`/stockcount/sessions/${id}/snapshots/`, { params }),

  // POST → live single-item count entry { item_code, counted_qty }; instant variance
  countItem:         (id, data)   => api.post(`/stockcount/sessions/${id}/count-item/`, data),

  // POST → close session
  close:             (id)  => api.post(`/stockcount/sessions/${id}/close/`),
}

// ── Config / Settings ─────────────────────────────────────────────────────────

export const configApi = {
  // System settings
  listSettings:   (params) => api.get('/config/settings/', { params }),
  updateSetting:  (id, value) => api.patch(`/config/settings/${id}/`, { value }),
  bulkUpdate:     (data)    => api.post('/config/settings/bulk_update/', data),
  byKey:          (keys)    => api.post('/config/settings/by_key/', { keys }),

  // Pharmacy profile
  pharmacyProfile: ()        => api.get('/config/pharmacy/'),
  updatePharmacy:  (data)    => api.patch('/config/pharmacy/', data),

  // Appearance / theme (GET is public; PUT is admin-only)
  getTheme:        ()        => api.get('/config/theme/'),
  updateTheme:     (data)    => api.put('/config/theme/', data),

  // Dropdown options
  listDropdowns:  (params)  => api.get('/config/dropdowns/', { params }),
  getDropdownKey: (key)     => api.get('/config/dropdowns/', { params: { key } }),
  groupedDropdowns: ()      => api.get('/config/dropdowns/grouped/'),
  dropdownKeys:   ()        => api.get('/config/dropdowns/keys/'),
  createDropdown: (data)    => api.post('/config/dropdowns/', data),
  updateDropdown: (id, data)=> api.patch(`/config/dropdowns/${id}/`, data),
  deleteDropdown: (id)      => api.delete(`/config/dropdowns/${id}/`),
  reorderDropdowns:(items)  => api.post('/config/dropdowns/reorder/', items),
}

// ── Incentives ────────────────────────────────────────────────────────────────

export const incentivesApi = {
  // Programs
  listPrograms:   (params)       => api.get('/incentives/programs/', { params }),
  getProgram:     (id)           => api.get(`/incentives/programs/${id}/`),
  createProgram:  (data)         => api.post('/incentives/programs/', data),
  updateProgram:  (id, data)     => api.patch(`/incentives/programs/${id}/`, data),
  deleteProgram:  (id)           => api.delete(`/incentives/programs/${id}/`),

  // Calculate — body: { period_start, period_end, user_ids?, force? }
  // Returns 409 if period is finalized and force is not true
  calculate:      (id, data)     => api.post(`/incentives/programs/${id}/calculate/`, data),

  // Simulate (dry-run) — same body as calculate; never writes to DB
  simulate:       (id, data)     => api.post(`/incentives/programs/${id}/simulate/`, data),

  // Report (GET action on a program)
  report:         (id, params)   => api.get(`/incentives/programs/${id}/report/`, { params }),

  // Finalize (POST action on a program)
  finalize:       (id, data)     => api.post(`/incentives/programs/${id}/finalize/`, data),

  // Rules
  listRules:      (params)       => api.get('/incentives/rules/', { params }),
  getRule:        (id)           => api.get(`/incentives/rules/${id}/`),
  createRule:     (data)         => api.post('/incentives/rules/', data),
  updateRule:     (id, data)     => api.patch(`/incentives/rules/${id}/`, data),
  deleteRule:     (id)           => api.delete(`/incentives/rules/${id}/`),

  // Rule Items — multi-item management
  // Add / update one item (idempotent)
  addRuleItem:    (ruleId, data) => api.post(`/incentives/rules/${ruleId}/add-item/`, data),

  // Remove one item by item_code
  removeRuleItem: (ruleId, itemCode) =>
    api.delete(`/incentives/rules/${ruleId}/remove-item/`, { params: { item_code: itemCode } }),

  // Clear ALL items from a rule
  clearRuleItems: (ruleId)       => api.delete(`/incentives/rules/${ruleId}/clear-items/`),

  // Bulk-import items — JSON mode
  // data = { items: [{item_code, item_name?, incentive_override?},...], mode: 'replace'|'append' }
  importRuleItems: (ruleId, data) => api.post(`/incentives/rules/${ruleId}/import-items/`, data),

  // Bulk-import items — CSV mode (FormData with 'csv_file' + 'mode')
  importRuleItemsCsv: (ruleId, formData) =>
    api.post(`/incentives/rules/${ruleId}/import-items/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),

  // Transactions (read-only)
  listTransactions: (params)     => api.get('/incentives/transactions/', { params }),

  // Settlements
  listSettlements: (params)      => api.get('/incentives/settlements/', { params }),
  getSettlement:   (id)          => api.get(`/incentives/settlements/${id}/`),
  receipt:         (id)          => api.get(`/incentives/settlements/${id}/receipt/`),

  // Adjustment Entries — manual +/- corrections per user per period
  // params: { program, user, period_start, period_end }
  listAdjustments:  (params)     => api.get('/incentives/adjustments/', { params }),
  createAdjustment: (data)       => api.post('/incentives/adjustments/', data),
  updateAdjustment: (id, data)   => api.patch(`/incentives/adjustments/${id}/`, data),
  deleteAdjustment: (id)         => api.delete(`/incentives/adjustments/${id}/`),

  // Calculation Logs — audit trail for every calculate/simulate run
  // params: { program, mode }
  listLogs: (params) => api.get('/incentives/logs/', { params }),
  getLog:   (id)     => api.get(`/incentives/logs/${id}/`),

  // Near-Expiry Stock — live query from SOFTECH stkbalexpiry
  // params: { expiry_within_days?, branch_codes?, item_codes? }
  nearExpiryStock:  (params) => api.get('/incentives/near-expiry-stock/', { params }),

  // Near-Expiry Incentive Report — from IncentiveTransaction (post-calculation)
  // params: { period_start, period_end, user_id? }
  nearExpiryReport: (programId, params) =>
    api.get(`/incentives/programs/${programId}/near-expiry-report/`, { params }),

  // Feature 1 — Employee Live Progress Dashboard
  myProgress: () => api.get('/incentives/my-progress/'),

  // Feature 3 — Smart Item Suggestions
  // params: { expiry_within_days?, branch_code?, max_results?, include_tags? }
  suggestItems: (params) => api.get('/incentives/suggest-items/', { params }),

  // Feature 4 — Program Clone
  // data: { new_start_date, new_end_date, new_name? }
  cloneProgram: (id, data) => api.post(`/incentives/programs/${id}/clone/`, data),

  // Feature 6 — Excel Export (returns blob)
  // params: { period_start, period_end }
  exportSettlements: (id, params) =>
    api.get(`/incentives/programs/${id}/export-settlements/`, {
      params,
      responseType: 'blob',
    }),

  // Feature 10 — ROI Report
  // params: { period_start, period_end, comparison_days? }
  roiReport: (id, params) =>
    api.get(`/incentives/programs/${id}/roi-report/`, { params }),
}

// ── User Management & Permissions ─────────────────────────────────────────────

export const usersApi = {
  // Staff profile CRUD
  list:          (params)       => api.get('/users/staff/', { params }),
  get:           (id)           => api.get(`/users/staff/${id}/`),
  create:        (data)         => api.post('/users/staff/', data),
  update:        (id, data)     => api.patch(`/users/staff/${id}/`, data),
  delete:        (id)           => api.delete(`/users/staff/${id}/`),

  // Admin actions
  resetPassword: (id, newPassword) =>
    api.post(`/users/staff/${id}/reset-password/`, { new_password: newPassword }),
  toggleActive:  (id) => api.post(`/users/staff/${id}/toggle-active/`),
  activityLog:   (id) => api.get(`/users/staff/${id}/activity-log/`),

  // Self-service
  changePassword: (oldPassword, newPassword, confirmPassword) =>
    api.post('/auth/change-password/', {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),

  // ERP user lookup (for creation form validation)
  erpUsers:       (params) => api.get('/users/erp-users/', { params }),

  // Permissions matrix (admin only)
  getPermissions:  ()        => api.get('/users/permissions/'),
  savePermissions: (updates) => api.post('/users/permissions/', updates),

  // Current-user permissions (any role)
  myPermissions: () => api.get('/users/my-permissions/'),

  // SOFTECH permission inheritance (admin)
  erpMyPerms:     ()        => api.get('/users/erp-permissions/me/'),
  erpGroups:      ()        => api.get('/users/erp-permissions/groups/'),
  erpSystems:     ()        => api.get('/users/erp-permissions/systems/'),
  erpMap:         ()        => api.get('/users/erp-permissions/map/'),
  erpMapAdd:      (data)    => api.post('/users/erp-permissions/map/', data),
  erpMapDelete:   (id)      => api.delete(`/users/erp-permissions/map/${id}/`),
  erpRebuild:     (data={}) => api.post('/users/erp-permissions/rebuild/', data),
}

// ── Delivery Tracking ─────────────────────────────────────────────────────────

export const deliveryApi = {
  // Orders
  list:      (params)    => api.get('/delivery/', { params }),
  get:       (id)        => api.get(`/delivery/${id}/`),
  create:    (data)      => api.post('/delivery/', data),
  update:    (id, data)  => api.patch(`/delivery/${id}/`, data),
  summary:   ()          => api.get('/delivery/summary/'),
  dashboard: (params)    => api.get('/delivery/dashboard/', { params }),

  // Lifecycle transitions
  assign:      (id, data) => api.post(`/delivery/${id}/assign/`, data),
  accept:      (id, data) => api.post(`/delivery/${id}/accept/`, data),
  dispatch:    (id, data) => api.post(`/delivery/${id}/dispatch/`, data),
  complete:    (id, data) => api.post(`/delivery/${id}/complete/`, data),
  partial:     (id, data) => api.post(`/delivery/${id}/partial/`, data),
  unavailable: (id, data) => api.post(`/delivery/${id}/unavailable/`, data),
  fail:        (id, data) => api.post(`/delivery/${id}/fail/`, data),
  cancel:      (id, data) => api.post(`/delivery/${id}/cancel/`, data),
  return:      (id, data) => api.post(`/delivery/${id}/return/`, data),
  close:       (id, data) => api.post(`/delivery/${id}/close/`, data),
  collectCash: (id, data) => api.post(`/delivery/${id}/collect-cash/`, data),
  backfill:    (id, data) => api.post(`/delivery/${id}/backfill/`, data),
  getItems:    (id)       => api.get(`/delivery/${id}/items/`),
  whatsapp:    (id)       => api.get(`/delivery/${id}/whatsapp/`),
  trackingLink:(id)       => api.get(`/delivery/${id}/tracking-link/`),   // staff: shareable link
  submitCsat:  (id, data) => api.post(`/delivery/${id}/csat/`, data),           // F14

  // F4 — Free delivery threshold check
  checkThreshold: (params) => api.get('/delivery/threshold/', { params }),

  // F5 — Route plan
  routePlan:   (params) => api.get('/delivery/route-plan/', { params }),

  // F9 — Area fees
  listAreaFees:   (params)   => api.get('/delivery/area-fees/', { params }),
  createAreaFee:  (data)     => api.post('/delivery/area-fees/', data),
  updateAreaFee:  (id, data) => api.patch(`/delivery/area-fees/${id}/`, data),
  deleteAreaFee:  (id)       => api.delete(`/delivery/area-fees/${id}/`),

  // F10 — Driver performance
  driverPerformance: (params) => api.get('/delivery/driver-performance/', { params }),

  // F11 — Area heatmap
  areaHeatmap: (params) => api.get('/delivery/area-heatmap/', { params }),

  // F12 — Shift report
  shiftReport: (params) => api.get('/delivery/shift-report/', { params }),

  // F13 — Customer location memory
  customerProfile: (phone) => api.get('/delivery/customer-profile/', { params: { phone } }),

  // F14 — CSAT report
  csatReport: (params) => api.get('/delivery/csat-report/', { params }),

  // F6 — Driver App
  myOrders:    () => api.get('/delivery/app/my-orders/'),
  myRoute:     () => api.get('/delivery/app/my-route/'),
  updateGps:   (id, data) => api.post(`/delivery/app/orders/${id}/location/`, data),

  // Route batching (runs)
  listRoutes:    (params)   => api.get('/delivery/routes/', { params }),
  getRoute:      (id)       => api.get(`/delivery/routes/${id}/`),
  createRoute:   (data)     => api.post('/delivery/routes/', data),
  dispatchRoute: (id)       => api.post(`/delivery/routes/${id}/dispatch/`),
  // POD completion (multipart supports a photo)
  completeWithPod: (id, formData) => api.post(`/delivery/${id}/complete/`, formData),

  // Drivers
  listDrivers:  (params)   => api.get('/delivery/drivers/', { params }),
  getDriver:    (id)        => api.get(`/delivery/drivers/${id}/`),
  createDriver: (data)      => api.post('/delivery/drivers/', data),
  updateDriver: (id, data)  => api.patch(`/delivery/drivers/${id}/`, data),

  // Customer locations (multi-location v2)
  listLocations:   (customerId)        => api.get(`/delivery/customers/${customerId}/locations/`),
  createLocation:  (customerId, data)  => api.post(`/delivery/customers/${customerId}/locations/`, data),
  updateLocation:  (locId, data)       => api.patch(`/delivery/locations/${locId}/`, data),
  deleteLocation:  (locId)             => api.delete(`/delivery/locations/${locId}/`),

  // Legacy single-location compat (used by old views — maps to new list endpoint)
  getLocation:    (customerId)       => api.get(`/delivery/customers/${customerId}/locations/`),
  upsertLocation: (customerId, data) => api.post(`/delivery/customers/${customerId}/locations/`, data),
}

// ── Payment Tracking ──────────────────────────────────────────────────────────

export const paymentsApi = {
  list:    (params)   => api.get('/payments/', { params }),
  get:     (id)       => api.get(`/payments/${id}/`),
  create:  (data)     => api.post('/payments/', data),
  update:  (id, data) => api.patch(`/payments/${id}/`, data),
  summary: ()         => api.get('/payments/summary/'),

  // Actions
  confirm:    (id, data) => api.post(`/payments/${id}/confirm/`, data || {}),
  reconcile:  (id, data) => api.post(`/payments/${id}/reconcile/`, data),
  dispute:    (id, data) => api.post(`/payments/${id}/dispute/`, data),

  // Screenshot upload
  uploadScreenshot: (id, formData) =>
    api.post(`/payments/${id}/screenshot/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export const analyticsApi = {
  filterOptions:       ()            => api.get('/analytics/filter-options/'),
  sales:               (params)      => api.get('/analytics/sales/',          { params }),
  customers:           (params)      => api.get('/analytics/customers/',      { params }),
  performance:         (params)      => api.get('/analytics/performance/',    { params }),
  inventory:           (params)      => api.get('/analytics/inventory/',      { params }),
  customerSearch:      (q, limit=20) => api.get('/analytics/customer-search/', { params: { q, limit } }),
  churn:               (params = {}) => api.get('/analytics/churn/',               { params }),
  branchContribution:  (params = {}) => api.get('/analytics/branch-contribution/',  { params }),
  inventoryInvestment: (params = {}) => api.get('/analytics/inventory-investment/', { params }),
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export const tasksApi = {
  // CRUD
  list:   (params) => api.get('/tasks/', { params }),
  get:    (id)     => api.get(`/tasks/${id}/`),
  create: (data)   => api.post('/tasks/', data),
  update: (id, data) => api.patch(`/tasks/${id}/`, data),

  // Actions
  complete: (id, data) => api.post(`/tasks/${id}/complete/`, data || {}),
  reopen:   (id)       => api.post(`/tasks/${id}/reopen/`),

  // Assignments
  getAssignments:    (id)         => api.get(`/tasks/${id}/assignments/`),
  addAssignment:     (id, data)   => api.post(`/tasks/${id}/assignments/`, data),
  removeAssignment:  (id, asgId)  => api.delete(`/tasks/${id}/assignments/${asgId}/remove/`),

  // Checklist items
  getItems:    (id)             => api.get(`/tasks/${id}/items/`),
  addItem:     (id, data)       => api.post(`/tasks/${id}/items/`, data),
  updateItem:  (id, itemId, data) => api.patch(`/tasks/${id}/items/${itemId}/`, data),
  deleteItem:  (id, itemId)     => api.delete(`/tasks/${id}/items/${itemId}/`),

  // Messages / chatter
  getMessages:   (id)       => api.get(`/tasks/${id}/messages/`),
  sendMessage:   (id, body) => api.post(`/tasks/${id}/messages/`, { body }),
  deleteMessage: (id, msgId)=> api.delete(`/tasks/${id}/messages/${msgId}/delete/`),

  // Attachments
  getAttachments:    (id)         => api.get(`/tasks/${id}/attachments/`),
  uploadAttachment:  (id, formData) =>
    api.post(`/tasks/${id}/attachments/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  deleteAttachment:  (id, attId)  => api.delete(`/tasks/${id}/attachments/${attId}/delete/`),

  // Audit
  getAuditLogs: (id) => api.get(`/tasks/${id}/audit/`),

  // Special views
  myTasks:   (params) => api.get('/tasks/my/', { params }),
  dashboard: (params) => api.get('/tasks/dashboard/', { params }),
  options:   ()       => api.get('/tasks/options/'),

  // Schedules
  listSchedules:   (params) => api.get('/tasks/schedules/', { params }),
  getSchedule:     (id)     => api.get(`/tasks/schedules/${id}/`),
  createSchedule:  (data)   => api.post('/tasks/schedules/', data),
  updateSchedule:  (id, data) => api.patch(`/tasks/schedules/${id}/`, data),
  deleteSchedule:  (id)     => api.delete(`/tasks/schedules/${id}/`),
  runSchedule:     (id)     => api.post(`/tasks/schedules/${id}/run/`),
}

export const chronicApi = {
  // Medication Tags
  listTags:    (params)       => api.get('/chronic/tags/', { params }),
  createTag:   (data)         => api.post('/chronic/tags/', data),
  updateTag:   (id, data)     => api.patch(`/chronic/tags/${id}/`, data),
  deleteTag:   (id)           => api.delete(`/chronic/tags/${id}/`),

  // Active Ingredients
  listIngredients:    (params)     => api.get('/chronic/ingredients/', { params }),
  getIngredient:      (id)         => api.get(`/chronic/ingredients/${id}/`),
  createIngredient:   (data)       => api.post('/chronic/ingredients/', data),
  updateIngredient:   (id, data)   => api.patch(`/chronic/ingredients/${id}/`, data),
  deleteIngredient:   (id)         => api.delete(`/chronic/ingredients/${id}/`),
  addTag:             (id, tagId)  => api.post(`/chronic/ingredients/${id}/add_tag/`, { tag_id: tagId }),
  removeTag:          (id, tagId)  => api.delete(`/chronic/ingredients/${id}/remove_tag/`, { data: { tag_id: tagId } }),
  getIngredientItems: (id)         => api.get(`/chronic/ingredients/${id}/items/`),
  getProtocols:       (id)         => api.get(`/chronic/ingredients/${id}/protocols/`),
  addProtocol:        (id, data)   => api.post(`/chronic/ingredients/${id}/protocols/`, data),

  // Follow-Up Protocols
  listProtocols:   (params)     => api.get('/chronic/protocols/', { params }),
  updateProtocol:  (id, data)   => api.patch(`/chronic/protocols/${id}/`, data),
  deleteProtocol:  (id)         => api.delete(`/chronic/protocols/${id}/`),

  // Item ↔ Ingredient Maps
  listItemMaps:   (params)     => api.get('/chronic/item-maps/', { params }),
  createItemMap:  (data)       => api.post('/chronic/item-maps/', data),
  deleteItemMap:  (id)         => api.delete(`/chronic/item-maps/${id}/`),

  // Item Classifier (main module page)
  // stktransm.phcode = customer personcode — items are classified directly per-item
  listItems:     (params)     => api.get('/chronic/items/', { params }),
  getItem:       (id)         => api.get(`/chronic/items/${id}/`),
  classifyItem:  (id, data)   => api.post(`/chronic/items/${id}/classify/`, data),
  unclassifyItem:(id, params) => api.delete(`/chronic/items/${id}/unclassify/`, { params }),
  getItemSummary:()           => api.get('/chronic/items/summary/'),

  // Task Generator
  previewTasks:  (data)       => api.post('/chronic/task-generator/preview/', data),
  generateTasks: (data)       => api.post('/chronic/task-generator/generate/', data),
}

// ── Procurement Intelligence API ──────────────────────────────────────────────
export const procurementIntelApi = {
  // Dashboard + Overview (Module 1)
  dashboard:       (params)              => api.get('/procurement/dashboard/', { params }),
  overview:        (params)              => api.get('/procurement/overview/', { params }),
  snapshots:       (params)              => api.get('/procurement/snapshots/', { params }),

  // Supplier Performance (Module 2)
  listSuppliers:   (params)              => api.get('/procurement/suppliers/', { params }),
  getSupplier:     (supplierCode)        => api.get(`/procurement/suppliers/${supplierCode}/`),
  supplierHistory: (supplierCode, params) => api.get(`/procurement/suppliers/${supplierCode}/history/`, { params }),

  // Item Procurement + Mapping (Module 3 + 4)
  itemAnalysis:    (itemCode, params)    => api.get(`/procurement/items/${itemCode}/analysis/`, { params }),
  listMappings:    (params)              => api.get('/procurement/mappings/', { params }),

  // Margin Analysis (Module 5)
  margins:         (params)              => api.get('/procurement/margins/', { params }),

  // Return Analysis (Module 6)
  returns:         (params)              => api.get('/procurement/returns/', { params }),

  // Price Control (Module 8)
  priceControl:    (params)              => api.get('/procurement/price-control/', { params }),

  // Optimization (Module 9)
  optimization:    (params)              => api.get('/procurement/optimization/', { params }),

  // Buyer Performance (Module 10)
  listBuyers:      (params)              => api.get('/procurement/buyers/', { params }),

  // Branch Procurement (Module 11)
  branchProcurement: (params)            => api.get('/procurement/branches/', { params }),

  // Purchase Lines (drill-down)
  listLines:       (params)              => api.get('/procurement/lines/', { params }),

  // Engine Runs
  listRuns:        (params)              => api.get('/procurement/runs/', { params }),
  triggerEngine:   (data)                => api.post('/procurement/trigger/', data),

  // Alerts
  listAlerts:      (params)              => api.get('/procurement/alerts/', { params }),
  resolveAlert:    (id, data)            => api.patch(`/procurement/alerts/${id}/resolve/`, data),

  // v2/v3: Purchase History (enhanced with SOFTECH item-attribute + range filters)
  history:             (params)          => api.get('/procurement/history/', { params }),
  historySummary:      (params)          => api.get('/procurement/history/summary/', { params }),
  filterOptions:       ()               => api.get('/procurement/filter-options/'),

  // v2: Supplier Segmentation
  listSegments:        (params)          => api.get('/procurement/segments/', { params }),
  segmentsSummary:     (params)          => api.get('/procurement/segments/summary/', { params }),
  updateSegment:       (id, data)        => api.patch(`/procurement/segments/${id}/update/`, data),

  // v2: Enhanced Supplier Performance
  listSuppliersEnhanced: (params)        => api.get('/procurement/suppliers-enhanced/', { params }),

  // v2: FOC Analysis
  focAnalysis:         (params)          => api.get('/procurement/foc/', { params }),

  // v2: Expiry Returns
  expiryReturns:       (params)          => api.get('/procurement/expiry-returns/', { params }),

  // v2: Tax Burden
  taxBurden:           (params)          => api.get('/procurement/tax-burden/', { params }),

  // v3: Admin-managed supplier categories + classification rules
  listCategories:      (params)          => api.get('/procurement/categories/', { params }),
  createCategory:      (data)            => api.post('/procurement/categories/', data),
  updateCategory:      (id, data)        => api.patch(`/procurement/categories/${id}/`, data),
  deleteCategory:      (id)              => api.delete(`/procurement/categories/${id}/`),
  listRules:           (params)          => api.get('/procurement/classification-rules/', { params }),
  createRule:          (data)            => api.post('/procurement/classification-rules/', data),
  updateRule:          (id, data)        => api.patch(`/procurement/classification-rules/${id}/`, data),
  deleteRule:          (id)              => api.delete(`/procurement/classification-rules/${id}/`),
  reclassify:          ()               => api.post('/procurement/reclassify/', {}),
  personCodes:         (params)          => api.get('/procurement/person-codes/', { params }),
}

// ── Product Experience / Commerce Catalog API ─────────────────────────────────
export const productsApi = {
  // Catalog browsing
  list:             (params)             => api.get('/products/', { params }),
  search:           (params)             => api.get('/products/search/', { params }),
  filterOptions:    ()                   => api.get('/products/filter-options/'),

  // Product detail
  getBySlug:        (slug)               => api.get(`/products/slug/${slug}/`),
  getByBarcode:     (barcode)            => api.get(`/products/barcode/${barcode}/`),
  getDetail:        (id)                 => api.get(`/products/${id}/`),
  getCard:          (id)                 => api.get(`/products/${id}/card/`),
  getAvailability:  (id, params)         => api.get(`/products/${id}/availability/`, { params }),
  getShareCard:     (id)                 => api.get(`/products/${id}/share/`),

  // Tracking
  trackInteraction: (id, type)           => api.post(`/products/${id}/track/`, { type }),

  // Media management
  uploadMedia:      (id, formData)       => api.post(`/products/${id}/media/upload/`, formData, {
                                             headers: { 'Content-Type': 'multipart/form-data' },
                                           }),
  updateMedia:      (id, mediaId, data)  => api.patch(`/products/${id}/media/${mediaId}/`, data),
  deleteMedia:      (id, mediaId)        => api.delete(`/products/${id}/media/${mediaId}/`),

  // Content management
  getContent:       (id)                 => api.get(`/products/${id}/content/`),
  updateContent:    (id, data)           => api.put(`/products/${id}/content/`, data),
  patchContent:     (id, data)           => api.patch(`/products/${id}/content/`, data),

  // Attributes management
  getAttributes:    (id)                 => api.get(`/products/${id}/attributes/`),
  updateAttributes: (id, data)           => api.put(`/products/${id}/attributes/`, data),
  patchAttributes:  (id, data)           => api.patch(`/products/${id}/attributes/`, data),

  // SEO management
  getSeo:           (id)                 => api.get(`/products/${id}/seo/`),
  updateSeo:        (id, data)           => api.put(`/products/${id}/seo/`, data),
  patchSeo:         (id, data)           => api.patch(`/products/${id}/seo/`, data),

  // Similar items (same therapeutic class)
  getSimilar:       (id, params)         => api.get(`/products/${id}/similar/`, { params }),

  // Demand crosslink (open demands + shortages for an item)
  getDemand:        (id)                 => api.get(`/products/${id}/demand/`),

  // Price list export — returns a blob
  export:           (params)             => api.get('/products/export/', { params, responseType: 'blob' }),

  // Admin operations
  bulkInitialize:   ()                   => api.post('/products/bulk-initialize/'),
  // Note: backend URL is /api/products/bulk-initialize/ — placed before wildcard route
}

// ── Call Center ───────────────────────────────────────────────────────────────

export const callCenterApi = {
  // ── Calls CRUD ───────────────────────────────────────────────────────────────
  list:    (params) => api.get('/callcenter/calls/', { params }),
  get:     (id)     => api.get(`/callcenter/calls/${id}/`),
  create:  (data)   => api.post('/callcenter/calls/', data),
  update:  (id, data) => api.patch(`/callcenter/calls/${id}/`, data),

  // Phone lookup — returns all matching customers + 360 context for selected one.
  // Pass customer_id to load full context for a specific customer when multiple match.
  // '__unknown__' is a UI sentinel meaning "proceed without a customer" — never sent to the API.
  lookup:  (phone, customerId = null) =>
    api.get('/callcenter/calls/lookup/', {
      params: {
        phone,
        ...(customerId && customerId !== '__unknown__' ? { customer_id: customerId } : {}),
      },
    }),

  // Pending callbacks
  pendingCallbacks: () => api.get('/callcenter/calls/pending-callbacks/'),

  // Dashboard KPIs
  dashboard: ()     => api.get('/callcenter/calls/dashboard/'),

  // ── AI Summarization ────────────────────────────────────────────────────────
  summarize: (callId) => api.post(`/callcenter/calls/${callId}/summarize/`),

  // ── Attachments ─────────────────────────────────────────────────────────────
  getAttachments:    (callId)         => api.get(`/callcenter/calls/${callId}/attachments/`),
  uploadAttachment:  (callId, formData) =>
    api.post(`/callcenter/calls/${callId}/attachments/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  deleteAttachment:  (callId, attId)  => api.delete(`/callcenter/calls/${callId}/attachments/${attId}/`),

  // ── Case management from a call ─────────────────────────────────────────────
  createCase: (callId, data)  => api.post(`/callcenter/calls/${callId}/create-case/`, data),
  linkCase:   (callId, caseId) => api.patch(`/callcenter/calls/${callId}/link-case/`, { case_id: caseId }),

  // ── Follow-up creation from a call ──────────────────────────────────────────
  createFollowup: (callId, data) => api.post(`/callcenter/calls/${callId}/create-followup/`, data),

  // @mention autocomplete — call center staff list
  agents: () => api.get('/callcenter/calls/agents/'),

  // ── Quality scoring ──────────────────────────────────────────────────────────
  getQuality:    (callId)       => api.get(`/callcenter/calls/${callId}/quality/`),
  createQuality: (callId, data) => api.post(`/callcenter/calls/${callId}/quality/`, data),
  updateQuality: (callId, data) => api.patch(`/callcenter/calls/${callId}/quality/`, data),

  // ── Address change requests ──────────────────────────────────────────────────
  listAddressUpdates:  (params)  => api.get('/callcenter/address-updates/', { params }),
  applyAddressUpdate:  (id)      => api.post(`/callcenter/address-updates/${id}/apply/`),

  // Per-call address updates
  callAddressUpdates:  (callId)  => api.get(`/callcenter/calls/${callId}/address-updates/`),
  addCallAddressUpdate: (callId, data) =>
    api.post(`/callcenter/calls/${callId}/address-updates/`, data),
  applyCallAddressUpdate: (callId, updateId) =>
    api.post(`/callcenter/calls/${callId}/address-updates/${updateId}/apply/`),

  // ── Call Items (items discussed during a call) ──────────────────────────────
  getItems:    (callId)         => api.get(`/callcenter/calls/${callId}/items/`),
  addItem:     (callId, data)   => api.post(`/callcenter/calls/${callId}/items/`, data),
  removeItem:  (callId, itemId) => api.delete(`/callcenter/calls/${callId}/items/${itemId}/`),

  // Quick-convert call items → Reservation(s)
  // data: { branch_id, notes?, priority?, channel?, item_ids? }
  convertToReservation: (callId, data) =>
    api.post(`/callcenter/calls/${callId}/convert-to-reservation/`, data),

  // Quick-convert call items → TransferRequest
  // data: { requesting_branch_id, supplying_branch_id?, notes?, item_ids? }
  convertToTransfer: (callId, data) =>
    api.post(`/callcenter/calls/${callId}/convert-to-transfer/`, data),

  // ── Cases CRUD + state machine ───────────────────────────────────────────────
  cases:         {
    list:    (params) => api.get('/callcenter/cases/', { params }),
    get:     (id)     => api.get(`/callcenter/cases/${id}/`),
    create:  (data)   => api.post('/callcenter/cases/', data),
    update:  (id, data) => api.patch(`/callcenter/cases/${id}/`, data),

    // State machine
    assign:    (id, data) => api.post(`/callcenter/cases/${id}/assign/`, data),
    escalate:  (id, data) => api.post(`/callcenter/cases/${id}/escalate/`, data),
    resolve:   (id, data) => api.post(`/callcenter/cases/${id}/resolve/`, data),
    close:     (id)       => api.post(`/callcenter/cases/${id}/close/`),
    csat:      (id, data) => api.post(`/callcenter/cases/${id}/csat/`, data),

    // Events / chatter — supports JSON { message } OR FormData { message, attachment, attachment_type }
    addNote:   (id, messageOrFormData) => {
      const isFormData = messageOrFormData instanceof FormData
      return api.post(`/callcenter/cases/${id}/add-note/`, messageOrFormData, {
        headers: isFormData ? { 'Content-Type': 'multipart/form-data' } : {},
      })
    },
    events:    (id)           => api.get(`/callcenter/cases/${id}/events/`),

    // Views
    myQueue:   ()             => api.get('/callcenter/cases/my-queue/'),
    dashboard: ()             => api.get('/callcenter/cases/dashboard/'),
  },
}

// ── Audit & Abuse Flags ───────────────────────────────────────────────────────

export const auditApi = {
  // Audit logs (read-only)
  logs:      (params)     => api.get('/audit/logs/', { params }),
  logForObject: (model, id) => api.get('/audit/logs/for-object/', { params: { model, id } }),
  logForUser:   (staffId) => api.get('/audit/logs/for-user/', { params: { staff_id: staffId } }),

  // Abuse flags
  flags:      (params)    => api.get('/audit/flags/', { params }),
  flagSummary: ()         => api.get('/audit/flags/summary/'),

  // Review a flag — data: { status: 'reviewed'|'dismissed'|'escalated', note? }
  reviewFlag: (id, data)  => api.post(`/audit/flags/${id}/review/`, data),

  // Trigger abuse detection scan — window_hours defaults to 24
  runDetection: (windowHours = 24) =>
    api.post('/audit/flags/run-detection/', { window_hours: windowHours }),
}

// ── Follow-Up Tasks (Chronic Medications) ─────────────────────────────────────

export const followupsApi = {
  // Dashboard KPIs
  dashboard:    ()         => api.get('/followups/tasks/dashboard/'),

  // List tasks — full advanced filter params supported:
  // status, task_type, sales_channel (csv), favoured_only, branch, assigned_to,
  // indication, effect_code, medicine_type, item_search, customer_search,
  // segment, churn_segment, due_after, due_before, overdue_only, by_priority, ordering
  list:         (params)   => api.get('/followups/tasks/', { params }),

  // Single task detail (includes FBT + call_history)
  detail:       (id)       => api.get(`/followups/tasks/${id}/`),

  // Filter-meta dropdowns (channels, indications, medicine_types, segments, statuses)
  filterMeta:   ()         => api.get('/followups/tasks/filter-meta/'),

  // Full pipeline: generate new → auto-close ERP-confirmed → escalate overdue→missed
  generate:     (data)     => api.post('/followups/tasks/generate/', data),
  escalate:     (data)     => api.post('/followups/tasks/escalate/', data || {}),
  autoClose:    ()         => api.post('/followups/tasks/auto-close/'),
  backfillChannels:      ()           => api.post('/followups/tasks/backfill-channels/'),
  backfillTxDetail:      ()           => api.post('/followups/tasks/backfill-tx-detail/'),
  updatePriorityScores:  ()           => api.post('/followups/tasks/update-priority-scores/'),
  cleanupDead:           (data)       => api.post('/followups/tasks/cleanup-dead/', data || {}),
  autoCloseExtended:     (data)       => api.post('/followups/tasks/auto-close-extended/', data || {}),
  deduplicate:           (data)       => api.post('/followups/tasks/deduplicate/', data || {}),

  // Feature 9: Outcome presets
  outcomePresets:  ()                       => api.get('/followups/tasks/outcome-presets/'),
  applyOutcome:    (id, presetId, note='')  => api.post(`/followups/tasks/${id}/outcome/`, { preset_id: presetId, note }),

  // Feature 10: Bulk actions
  // action: 'mark_called'|'mark_done'|'mark_missed'|'apply_preset'|'assign'|'pin'|'unpin'|'cancel'
  bulkAction: (taskIds, action, opts = {}) => api.post('/followups/tasks/bulk-action/', {
    task_ids: taskIds, action, ...opts,
  }),

  // Feature 12: Phone flag
  flagPhone:   (id)  => api.post(`/followups/tasks/${id}/flag-phone/`),
  unflagPhone: (id)  => api.post(`/followups/tasks/${id}/unflag-phone/`),

  // Feature 7: My queue
  myQueue: ()        => api.get('/followups/tasks/my-queue/'),

  // Feature 3: Create campaign
  createCampaign: (data) => api.post('/followups/tasks/create-campaign/', data),

  // Feature 4: Upsell message
  upsellMessage: (id)    => api.get(`/followups/tasks/${id}/upsell-message/`),

  // Feature 6: Grouped by customer + multi-item WhatsApp
  grouped:       (params) => api.get('/followups/tasks/grouped/', { params }),
  multiWhatsapp: (taskIds, includeUpsell = false) => api.post('/followups/tasks/multi-whatsapp/', {
    task_ids: taskIds, include_upsell: includeUpsell,
  }),

  // Feature 23: Create demand record
  createDemand: (id, data) => api.post(`/followups/tasks/${id}/create-demand/`, data || {}),

  // Feature 24: Assign voucher
  assignVoucher: (id, voucherCode) => api.post(`/followups/tasks/${id}/assign-voucher/`, {
    voucher_code: voucherCode,
  }),

  // Pin / unpin — manual tracking (sends quiet notification to pinner only)
  pin:    (id)             => api.post(`/followups/tasks/${id}/pin/`),
  unpin:  (id)             => api.post(`/followups/tasks/${id}/unpin/`),

  // Assign — accepts any combination of: assignee_ids, role, branch_id, use_task_branch, replace
  // Examples:
  //   assign(id, { assignee_ids: [3, 7] })
  //   assign(id, { role: 'call_center' })
  //   assign(id, { role: 'pharmacist', branch_id: 5 })
  //   assign(id, { branch_id: 5 })
  //   assign(id, { use_task_branch: true })
  //   assign(id, { assignee_ids: [3], replace: false })  ← add without removing
  assign:           (id, data) => api.post(`/followups/tasks/${id}/assign/`, data),
  clearAssignments: (id)       => api.post(`/followups/tasks/${id}/clear-assignments/`),

  // State transitions
  call:   (id, note = '') => api.post(`/followups/tasks/${id}/call/`,   { note }),
  done:   (id, note = '') => api.post(`/followups/tasks/${id}/done/`,   { note }),
  missed: (id, note = '') => api.post(`/followups/tasks/${id}/missed/`, { note }),

  // WhatsApp: mark called + return pre-filled wa.me URL with Arabic message
  whatsapp: (id)           => api.post(`/followups/tasks/${id}/whatsapp/`),

  // Call center: create a CallLog linked to this task's customer + item
  // Body: { status: 'answered'|'no_answer'|..., notes: '...', mark_done?: bool }
  logCall:  (id, data)     => api.post(`/followups/tasks/${id}/log-call/`, data),

  // Direct task creation / update
  create:   (data)         => api.post('/followups/tasks/', data),
  update:   (id, data)     => api.patch(`/followups/tasks/${id}/`, data),

  // Chronic profiles
  listChronic:  (params)   => api.get('/followups/chronic/', { params }),
  inferFromErp: ()         => api.post('/followups/chronic/infer-from-erp/'),
}

// ── Finance Intelligence Platform ─────────────────────────────────────────────

export const financeApi = {
  // Dashboard — consolidated KPIs for the current or specified period
  dashboard:       (params)       => api.get('/finance/dashboard/', { params }),

  // Periods
  periods:         (params)       => api.get('/finance/periods/', { params }),

  // Chart of Accounts
  accounts:        (params)       => api.get('/finance/accounts/', { params }),
  accountTree:     ()             => api.get('/finance/accounts/tree/'),

  // Financial Snapshots (pre-computed KPIs)
  snapshots:       (params)       => api.get('/finance/snapshots/', { params }),

  // P&L Statement
  pnl:             (params)       => api.get('/finance/pnl/', { params }),

  // Journal Entries
  journal:         (params)       => api.get('/finance/journal/', { params }),
  journalDetail:   (id)           => api.get(`/finance/journal/${id}/`),

  // Trial Balance
  trialBalance:    (params)       => api.get('/finance/trial-balance/', { params }),
  accountBalances: (params)       => api.get('/finance/account-balances/', { params }),

  // Treasury / Cash Flow
  treasury:        (params)       => api.get('/finance/treasury/', { params }),
  cashFlow:        (params)       => api.get('/finance/cash-flow/', { params }),

  // Expenses
  expenses:            (params) => api.get('/finance/expenses/', { params }),
  expenseBreakdown:    (params) => api.get('/finance/expenses/breakdown/', { params }),
  expenseSubcategories:(params) => api.get('/finance/expenses/subcategories/', { params }),

  // Schema Dictionary (Phase 0)
  schema:          (params)       => api.get('/finance/schema/', { params }),
  schemaDetail:    (id)           => api.get(`/finance/schema/${id}/`),
  updateSchema:    (id, data)     => api.patch(`/finance/schema/${id}/`, data),

  // ETL Triggers (admin/pharmacist only)
  triggerDiscover: ()             => api.post('/finance/trigger-discover/'),
  triggerSync:     (data)         => api.post('/finance/trigger-sync/', data),

  // Sync Run History
  syncRuns:        (params)       => api.get('/finance/sync-runs/', { params }),
}

// ── Recommendations / FBT API ─────────────────────────────────────────────────
export const recommendationsApi = {
  latestRun:    ()                    => api.get('/recommendations/run/'),
  runsHistory:  (params)              => api.get('/recommendations/runs/', { params }),
  trigger:      (data={})             => api.post('/recommendations/trigger/', data),
  fbtList:      (params)              => api.get('/recommendations/fbt/', { params }),
  fbtForItem:   (itemId, limit=6)     =>
    api.get('/recommendations/fbt/for-item/', { params: { item_id: itemId, limit } }),
  customerRecs: (customerId, limit=8) =>
    api.get('/recommendations/customer/', { params: { customer_id: customerId, limit } }),
}

// ── Cheque Planning + Treasury API ───────────────────────────────────────────
export const chequesApi = {
  // Calendar
  holidays:    (params)  => api.get('/cheques/holidays/', { params }),

  // Preview (no DB write)
  preview:     (data)    => api.post('/cheques/preview/', data),

  // Treasury dashboard
  treasury:    ()        => api.get('/cheques/treasury/'),

  // Plans CRUD
  plans:       (params)  => api.get('/cheques/plans/', { params }),
  createPlan:  (data)    => api.post('/cheques/plans/', data),
  planDetail:  (id)      => api.get(`/cheques/plans/${id}/`),
  updatePlan:  (id, data) => api.patch(`/cheques/plans/${id}/`, data),
  deletePlan:  (id)      => api.delete(`/cheques/plans/${id}/`),

  // Workflow
  activate:    (id)      => api.post(`/cheques/plans/${id}/activate/`),
  cancelPlan:  (id)      => api.post(`/cheques/plans/${id}/cancel/`),

  // Instalment update
  updateInstalment: (planId, instId, data) =>
    api.patch(`/cheques/plans/${planId}/instalments/${instId}/`, data),
}

// ── WhatsApp Campaign API ─────────────────────────────────────────────────────
export const campaignsApi = {
  // List + create
  list:   (params) => api.get('/campaigns/', { params }),
  create: (data)   => api.post('/campaigns/', data),

  // Detail
  get:    (id)     => api.get(`/campaigns/${id}/`),
  update: (id, data) => api.patch(`/campaigns/${id}/`, data),
  delete: (id)     => api.delete(`/campaigns/${id}/`),

  // Audience preview (returns {total_customers, has_phone, sample_names})
  previewAudience: (id, targetFilter) =>
    api.post(`/campaigns/${id}/preview-audience/`, { target_filter: targetFilter }),

  // Approval workflow
  requestApproval: (id)           => api.post(`/campaigns/${id}/request-approval/`),
  approve:         (id)           => api.post(`/campaigns/${id}/approve/`),
  reject:          (id, reason)   => api.post(`/campaigns/${id}/reject/`, { reason }),
  queue:           (id, data={})  => api.post(`/campaigns/${id}/queue/`, data),
  cancel:          (id)           => api.post(`/campaigns/${id}/cancel/`),

  // Messages
  messages:            (id, params) => api.get(`/campaigns/${id}/messages/`, { params }),
  updateMessageStatus: (id, msgId, data) =>
    api.patch(`/campaigns/${id}/messages/${msgId}/status/`, data),

  // Stats
  stats: (id) => api.get(`/campaigns/${id}/stats/`),
}

// ── Catalog Enrichment API ────────────────────────────────────────────────────
export const enrichmentApi = {
  // Item queue — sorted by completeness_score ASC
  // params: { q, score_lt, score_gte, category, is_published, has_pending, ordering, page, page_size }
  queue:       (params)       => api.get('/enrichment/enrichments/', { params }),

  // Full enrichment record for one item
  get:         (id)           => api.get(`/enrichment/enrichments/${id}/`),
  patch:       (id, data)     => api.patch(`/enrichment/enrichments/${id}/`, data),

  // Item detail — enrichment record + pending suggestions + SOFTECH snapshot
  itemDetail:  (itemPk)       => api.get(`/enrichment/items/${itemPk}/`),

  // Generate suggestions for a single item on demand
  generate:    (itemPk, overwrite = false) =>
    api.post(`/enrichment/items/${itemPk}/generate/`, { overwrite }),

  // Suggestions list — params: { item, status, field, batch }
  suggestions: (params)       => api.get('/enrichment/suggestions/', { params }),

  // Approve — pass edited value or omit to use suggested_value
  approve:     (id, value)    => api.post(`/enrichment/suggestions/${id}/approve/`, { value }),

  // Reject
  reject:      (id, notes)    => api.post(`/enrichment/suggestions/${id}/reject/`, { notes: notes || '' }),

  // Bulk-approve pending suggestions above a confidence threshold
  bulkApprove: (itemId, minConfidence = 0.8) =>
    api.post('/enrichment/suggestions/bulk-approve/', {
      item_id: itemId, min_confidence: minConfidence,
    }),

  // Batch processing
  batches:      (params)      => api.get('/enrichment/batches/', { params }),
  batchDetail:  (id)          => api.get(`/enrichment/batches/${id}/`),
  createBatch:  (data)        => api.post('/enrichment/batches/', data),
  cancelBatch:  (id)          => api.post(`/enrichment/batches/${id}/cancel/`),

  // Aggregate completeness stats
  report:       ()            => api.get('/enrichment/report/'),

  // Trigger full score recompute in background
  recomputeScores: ()         => api.post('/enrichment/recompute-scores/'),
}

// ── Catalog Intelligence API ──────────────────────────────────────────────────
export const catalogIntelApi = {
  // Variant groups
  variantGroups:      (params)         => api.get('/items/variant-groups/', { params }),
  createVariantGroup: (data)           => api.post('/items/variant-groups/', data),
  variantGroupDetail: (id)             => api.get(`/items/variant-groups/${id}/`),
  updateVariantGroup: (id, data)       => api.patch(`/items/variant-groups/${id}/`, data),
  deleteVariantGroup: (id)             => api.delete(`/items/variant-groups/${id}/`),
  addVariantMember:   (groupId, data)  => api.post(`/items/variant-groups/${groupId}/members/`, data),
  removeVariantMember:(groupId, mId)   => api.delete(`/items/variant-groups/${groupId}/members/${mId}/`),

  // Bundles
  bundles:      (params)         => api.get('/items/bundles/', { params }),
  createBundle: (data)           => api.post('/items/bundles/', data),
  bundleDetail: (id)             => api.get(`/items/bundles/${id}/`),
  updateBundle: (id, data)       => api.patch(`/items/bundles/${id}/`, data),
  deleteBundle: (id)             => api.delete(`/items/bundles/${id}/`),
  addBundleItem:   (bundleId, data)  => api.post(`/items/bundles/${bundleId}/items/`, data),
  removeBundleItem:(bundleId, biId)  => api.delete(`/items/bundles/${bundleId}/items/${biId}/`),
}

// ── Image Acquisition API ─────────────────────────────────────────────────────
export const imageApi = {
  // Jobs
  jobs:         (params)    => api.get('/images/jobs/', { params }),
  jobDetail:    (id)        => api.get(`/images/jobs/${id}/`),
  createJob:    (data)      => api.post('/images/jobs/', data),
  bulkJobs:     (data)      => api.post('/images/jobs/bulk/', data),
  cancelJob:    (id)        => api.post(`/images/jobs/${id}/cancel/`),

  // Candidates
  candidates:   (params)    => api.get('/images/candidates/', { params }),
  reviewCandidate: (id, data) => api.post(`/images/candidates/${id}/review/`, data),
  redownload:   (id)        => api.post(`/images/candidates/${id}/redownload/`),

  // Stats
  report:       ()          => api.get('/images/report/'),
  reviewQueue:  (params)    => api.get('/images/review-queue/', { params }),
  filterMeta:   ()          => api.get('/images/filter-meta/'),
  reviseAll:    (data)      => api.post('/images/jobs/revise-all/', data),
  insights:     ()          => api.get('/images/insights/'),

  // Product gallery
  productSearch:(params)              => api.get('/images/products/search/', { params }),
  gallery:      (itemId)              => api.get(`/images/products/${itemId}/gallery/`),
  itemCandidates:(itemId, params)     => api.get(`/images/products/${itemId}/candidates/`, { params }),
  uploadImage:  (itemId, formData)    => api.post(`/images/products/${itemId}/upload/`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  setPrimary:   (itemId, mediaId)     => api.post(`/images/products/${itemId}/set-primary/${mediaId}/`),
  reorderImages:(itemId, orderList)   => api.patch(`/images/products/${itemId}/reorder/`, { order: orderList }),
  deleteImage:  (itemId, mediaId)     => api.delete(`/images/products/${itemId}/images/${mediaId}/`),
}

// ── Insurance Claims ───────────────────────────────────────────────────────────
export const insuranceApi = {
  // Clients
  clients:            (params)       => api.get('/insurance/clients/', { params }),
  clientDetail:       (id)           => api.get(`/insurance/clients/${id}/`),
  createClient:       (data)         => api.post('/insurance/clients/', data),
  updateClient:       (id, data)     => api.patch(`/insurance/clients/${id}/`, data),
  personsFromSoftech: ()             => api.get('/insurance/clients/persons-from-softech/'),

  // Subclients
  subclients:         (params)       => api.get('/insurance/subclients/', { params }),
  createSubclient:    (data)         => api.post('/insurance/subclients/', data),
  updateSubclient:    (id, data)     => api.patch(`/insurance/subclients/${id}/`, data),

  // Contracts
  contracts:          (params)       => api.get('/insurance/contracts/', { params }),
  createContract:     (data)         => api.post('/insurance/contracts/', data),
  updateContract:     (id, data)     => api.patch(`/insurance/contracts/${id}/`, data),

  // Claims
  claims:             (params)       => api.get('/insurance/claims/', { params }),
  claimDetail:        (id)           => api.get(`/insurance/claims/${id}/`),
  createAndImport:    (data)         => api.post('/insurance/claims/create-and-import/', data),
  listMotalbas:       (subclient_id) => api.get('/insurance/claims/list-motalbas/', { params: { subclient_id } }),
  discoverMotalbas:   (params)       => api.get('/insurance/claims/discover-motalbas/', { params }),
  bulkImport:         (items)        => api.post('/insurance/claims/bulk-import/', { items }),
  reimport:           (id, data)     => api.post(`/insurance/claims/${id}/import-from-softech/`, data),
  changeStatus:       (id, data)     => api.post(`/insurance/claims/${id}/change-status/`, data),

  // Prescriptions — lines (lazy) + adjustments & exclusions
  prescriptionLines:  (claimId, rxId)       => api.get(`/insurance/claims/${claimId}/prescriptions/${rxId}/lines/`),
  editLine:           (claimId, rxId, lineId, data) => api.patch(`/insurance/claims/${claimId}/prescriptions/${rxId}/lines/${lineId}/`, data),
  resetLine:          (claimId, rxId, lineId) => api.post(`/insurance/claims/${claimId}/prescriptions/${rxId}/lines/${lineId}/reset/`),
  adjustRx:           (claimId, rxId, data) => api.post(`/insurance/claims/${claimId}/prescriptions/${rxId}/adjust/`, data),
  removeAdjustment:   (claimId, rxId)       => api.delete(`/insurance/claims/${claimId}/prescriptions/${rxId}/adjust/`),
  excludeRx:          (claimId, rxId, data) => api.post(`/insurance/claims/${claimId}/prescriptions/${rxId}/exclude/`, data),
  includeRx:          (claimId, rxId)       => api.delete(`/insurance/claims/${claimId}/prescriptions/${rxId}/exclude/`),

  // Manual Rx
  lookupRx:           (claimId, docnumber)  => api.get(`/insurance/claims/${claimId}/lookup-rx/`, { params: { docnumber } }),
  addManualRx:        (claimId, data)       => api.post(`/insurance/claims/${claimId}/manual-rx/`, data),
  updateManualRx:     (claimId, mrxId, data) => api.patch(`/insurance/claims/${claimId}/manual-rx/${mrxId}/`, data),
  removeManualRx:     (claimId, mrxId)      => api.delete(`/insurance/claims/${claimId}/manual-rx/${mrxId}/`),

  // Supplements
  supplements:        (claimId)             => api.get(`/insurance/claims/${claimId}/supplements/`),
  addSupplement:      (claimId, data)       => api.post(`/insurance/claims/${claimId}/supplements/`, data),
  updateSupplement:   (claimId, supId, data) => api.patch(`/insurance/claims/${claimId}/supplements/${supId}/`, data),
  deleteSupplement:   (claimId, supId)      => api.delete(`/insurance/claims/${claimId}/supplements/${supId}/`),

  // Payments & Deductions
  payments:           (claimId)             => api.get(`/insurance/claims/${claimId}/payments/`),
  addPayment:         (claimId, data)       => api.post(`/insurance/claims/${claimId}/payments/`, data),
  deductions:         (claimId)             => api.get(`/insurance/claims/${claimId}/deductions/`),
  addDeduction:       (claimId, data)       => api.post(`/insurance/claims/${claimId}/deductions/`, data),

  // Invoice data + export
  invoiceDataset:     (claimId)             => api.get(`/insurance/claims/${claimId}/invoice-dataset/`),
  exportExcel:        (claimId, template, opts) => api.get(`/insurance/claims/${claimId}/export/excel/`, {
    params: { template, ...(opts || {}) },   // opts: { layout, sort_by, sort_dir }
    responseType: 'blob',
  }),

  // Cache sync (motalba + companiesitems)
  cacheStats:         ()                    => api.get('/insurance/sync-cache/'),
  syncCache:          ()                    => api.post('/insurance/sync-cache/'),

  // Parent clients (عميل أب)
  parentClients:      (params)              => api.get('/insurance/parent-clients/', { params }),
  createParentClient: (data)                => api.post('/insurance/parent-clients/', data),
  updateParentClient: (id, data)            => api.patch(`/insurance/parent-clients/${id}/`, data),
  deleteParentClient: (id)                  => api.delete(`/insurance/parent-clients/${id}/`),

  // Billing groups (تقسيم المطالبة إلى فئات)
  billingGroups:      (claimId)             => api.get('/insurance/billing-groups/', { params: { claim_id: claimId } }),
  createBillingGroup: (data)                => api.post('/insurance/billing-groups/', data),
  updateBillingGroup: (id, data)            => api.patch(`/insurance/billing-groups/${id}/`, data),
  deleteBillingGroup: (id)                  => api.delete(`/insurance/billing-groups/${id}/`),
  autoAssignGroup:    (id)                  => api.post(`/insurance/billing-groups/${id}/auto-assign/`),
  assignRxToGroup:    (id, ids, manualIds, supIds)  => api.post(`/insurance/billing-groups/${id}/assign-rx/`, { prescription_ids: ids || [], manual_rx_ids: manualIds || [], supplement_ids: supIds || [] }),
  unassignRxFromGroup:(id, ids, manualIds, supIds)  => api.post(`/insurance/billing-groups/${id}/unassign-rx/`, { prescription_ids: ids || [], manual_rx_ids: manualIds || [], supplement_ids: supIds || [] }),
  refreshGroups:      (claimId)             => api.post('/insurance/billing-groups/refresh-all/', { claim_id: claimId }),
  exportGroup:        (id, template)        => api.get(`/insurance/billing-groups/${id}/export/`, {
    params: { template },
    responseType: 'blob',
  }),

  // Pre-flight readiness validation (before issuing)
  readiness:          (claimId)             => api.get(`/insurance/claims/${claimId}/readiness/`),
  omissions:          (claimId)             => api.get(`/insurance/claims/${claimId}/omissions/`),

  // Official cover letter (Word) + submission package (ZIP)
  coverLetter:        (claimId)             => api.get(`/insurance/claims/${claimId}/cover-letter/`, { responseType: 'blob' }),
  submissionPackage:  (claimId)             => api.get(`/insurance/claims/${claimId}/submission-package/`, { responseType: 'blob' }),

  // Print/export profiles (تخصيص الطباعة)
  exportProfiles:        (params)           => api.get('/insurance/export-profiles/', { params }),
  createExportProfile:   (data, cfg)        => api.post('/insurance/export-profiles/', data, cfg),
  updateExportProfile:   (id, data, cfg)    => api.patch(`/insurance/export-profiles/${id}/`, data, cfg),
  deleteExportProfile:   (id)               => api.delete(`/insurance/export-profiles/${id}/`),

  // Value discrepancy (frozen vs current master classification + price)
  discrepancy:        (claimId)             => api.get(`/insurance/claims/${claimId}/discrepancy/`),
  discrepancyExport:  (claimId)             => api.get(`/insurance/claims/${claimId}/discrepancy-export/`, {
    responseType: 'blob',
  }),
  applyCurrentMaster: (claimId, opts)       => api.post(`/insurance/claims/${claimId}/apply-current-master/`, opts || {}),
  applyHistory:       (claimId)             => api.get(`/insurance/claims/${claimId}/apply-history/`),
  revertApplyRun:     (claimId, runId)      => api.post(`/insurance/claims/${claimId}/apply-runs/${runId}/revert/`),

  // Item classification corrections (تصويبات تصنيف الأصناف)
  itemOverrides:       (params)             => api.get('/insurance/item-overrides/', { params }),
  createItemOverride:  (data)               => api.post('/insurance/item-overrides/', data),
  updateItemOverride:  (id, data)           => api.patch(`/insurance/item-overrides/${id}/`, data),
  deleteItemOverride:  (id)                 => api.delete(`/insurance/item-overrides/${id}/`),
  itemOverrideLookup:  (code)               => api.get('/insurance/item-overrides/catalog-lookup/', { params: { code } }),
  itemOverrideAffected:(id)                 => api.get(`/insurance/item-overrides/${id}/affected-claims/`),
  overridesPreview:    (claimId)            => api.get(`/insurance/claims/${claimId}/overrides-preview/`),
  applyOverrides:      (claimId)            => api.post(`/insurance/claims/${claimId}/apply-overrides/`),
  claimItems:          (claimId)            => api.get(`/insurance/claims/${claimId}/claim-items/`),
  reviewItems:         (claimId)            => api.get(`/insurance/claims/${claimId}/review-items/`),
  applyReviewDecision: (claimId, item_code, category) => api.post(`/insurance/claims/${claimId}/apply-review-decision/`, { item_code, category }),

  // Pivot / cross-tab analysis
  pivotConfig:        (source)              => api.get('/insurance/claims/pivot-config/', { params: { source } }),
  pivot:              (params)              => api.get('/insurance/claims/pivot/', { params }),
  pivotTemplates:     ()                    => api.get('/insurance/pivot-templates/'),
  savePivotTemplate:  (data)               => api.post('/insurance/pivot-templates/', data),
  deletePivotTemplate:(id)                  => api.delete(`/insurance/pivot-templates/${id}/`),
  pivotExport:        (params)              => api.get('/insurance/claims/pivot-export/', {
    params,
    responseType: 'blob',
  }),
}


export const pricingApprovalsApi = {
  list:          (params)         => api.get('/pricing-approvals/', { params }),
  get:           (id)             => api.get(`/pricing-approvals/${id}/`),
  create:        (data)           => api.post('/pricing-approvals/', data),
  approve:       (id, notes = '') => api.post(`/pricing-approvals/${id}/approve/`, { notes }),
  reject:        (id, notes = '') => api.post(`/pricing-approvals/${id}/reject/`, { notes }),
  itemPrices:    (softechId)      => api.get(`/pricing-approvals/items/${softechId}/prices/`),
  // Live preview: { pack_price, pack_qty, sale_tax_pct } → { unit_price, pack_price_tax }
  preview:       (params)         => api.get('/pricing-approvals/preview/', { params }),
  approverInfo:  ()               => api.get('/pricing-approvals/approver-info/'),
  pendingCount:  ()               => api.get('/pricing-approvals/pending-count/'),
  // Discount-alignment audit
  alignmentScan:     (params)     => api.get('/pricing-approvals/alignment/', { params }),
  alignmentPolicies: ()           => api.get('/pricing-approvals/alignment/policies/'),
  savePolicy:        (data)       => api.post('/pricing-approvals/alignment/policies/', data),
  alignmentTiers:    ()           => api.get('/pricing-approvals/alignment/tiers/'),
  alignmentApply:    (data)       => api.post('/pricing-approvals/alignment/apply/', data),
  tierPreview:       (params)     => api.get('/pricing-approvals/alignment/tier-preview/', { params }),
  tierCreate:        (data)       => api.post('/pricing-approvals/alignment/tier-create/', data),

  // Replication status / repair (#2, #12)
  replication:       (id)            => api.get(`/pricing-approvals/${id}/replication/`),
  forceReplication:  (id, mode='restamp') => api.post(`/pricing-approvals/${id}/force-replication/`, { mode }),
  itemReplication:   (softechId)     => api.get(`/pricing-approvals/replication/item/${softechId}/`),

  // SLA dashboard (#9)
  sla:               ()              => api.get('/pricing-approvals/sla/'),

  // Rollback (#10)
  rollback:          (id)            => api.post(`/pricing-approvals/${id}/rollback/`, {}),

  // CSV/Excel import (#11)
  import:            (formData)      => api.post('/pricing-approvals/import/', formData, {
                                          headers: { 'Content-Type': 'multipart/form-data' } }),

  // Replication audit (#7/#8)
  runScan:           (days=30)       => api.post('/pricing-approvals/replication/scan/', { days }),
  scans:             ()              => api.get('/pricing-approvals/replication/scans/'),
  scanDetail:        (id, params)    => api.get(`/pricing-approvals/replication/scans/${id}/`, { params }),
  repair:            (data)          => api.post('/pricing-approvals/replication/repair/', data),

  // Insights & policy (#4 / #5 / #8 / #10 / #11)
  branchHealth:      ()              => api.get('/pricing-approvals/branch-health/'),
  whoChangedWhat:    (days=30)       => api.get('/pricing-approvals/who-changed-what/', { params: { days } }),
  discountImpact:    (window=30)     => api.get('/pricing-approvals/discount-impact/', { params: { window } }),
  policyGet:         ()              => api.get('/pricing-approvals/policy/'),
  policySet:         (data)          => api.post('/pricing-approvals/policy/', data),
  priceHistory:      (softechId)     => api.get(`/pricing-approvals/history/${softechId}/`),
}


export const loyaltyApi = {
  tiers:              ()                  => api.get('/loyalty/tiers/'),
  rewards:            ()                  => api.get('/loyalty/rewards/'),
  account:            (customerId)        => api.get(`/loyalty/customers/${customerId}/account/`),
  transactions:       (customerId, p)     => api.get(`/loyalty/customers/${customerId}/transactions/`, { params: p }),
  adjust:             (customerId, data)  => api.post(`/loyalty/customers/${customerId}/adjust/`, data),
  redeem:             (customerId, data)  => api.post(`/loyalty/customers/${customerId}/redeem/`, data),
  redemptions:        (customerId)        => api.get(`/loyalty/customers/${customerId}/redemptions/`),
  approveRedemption:  (id)               => api.post(`/loyalty/redemptions/${id}/approve/`),
  softechBalance:     (customerId)        => api.get(`/loyalty/customers/${customerId}/softech-balance/`),
  softechLog:         (customerId)        => api.get(`/loyalty/customers/${customerId}/softech-log/`),
}

export const referralApi = {
  myCode:         ()                  => api.get('/referral/my-code/'),
  customerCode:   (customerId)        => api.get(`/referral/customers/${customerId}/code/`),
  submitLead:     (customerId, data)  => api.post(`/referral/customers/${customerId}/leads/`, data),
  customerLeads:  (customerId, p)     => api.get(`/referral/customers/${customerId}/leads/list/`, { params: p }),
  leads:          (p)                 => api.get('/referral/leads/', { params: p }),
  leadDetail:     (id)                => api.get(`/referral/leads/${id}/`),
  leadEvents:     (id)                => api.get(`/referral/leads/${id}/events/`),
  validate:       (id, data)          => api.post(`/referral/leads/${id}/validate/`, data),
  invite:         (id)                => api.post(`/referral/leads/${id}/invite/`),
}

export const whatsappApi = {
  conversations:  (p)           => api.get('/whatsapp/conversations/', { params: p }),
  conversation:   (id)          => api.get(`/whatsapp/conversations/${id}/`),
  messages:       (cid, p)      => api.get(`/whatsapp/conversations/${cid}/messages/`, { params: p }),
  sendText:       (cid, data)   => api.post(`/whatsapp/conversations/${cid}/send/`, data),
  sendTemplate:   (cid, data)   => api.post(`/whatsapp/conversations/${cid}/send-template/`, data),
  templates:      ()             => api.get('/whatsapp/templates/'),
}

// ── Omni — unified omnichannel inbox (doc 15) ─────────────────────────────────
export const omniApi = {
  conversations: (p)          => api.get('/omni/conversations/', { params: p }),
  conversation:  (id)         => api.get(`/omni/conversations/${id}/`),
  update:        (id, data)   => api.patch(`/omni/conversations/${id}/`, data),
  timeline:      (id, p)      => api.get(`/omni/conversations/${id}/timeline/`, { params: p }),
  reply:         (id, data)   => api.post(`/omni/conversations/${id}/reply/`, data),
  accounts:      (p)          => api.get('/omni/accounts/', { params: p }),
  createAccount: (data)       => api.post('/omni/accounts/', data),
  updateAccount: (id, data)   => api.patch(`/omni/accounts/${id}/`, data),
  accountHealth: (id)         => api.get(`/omni/accounts/${id}/health/`),
  wallboard:     ()           => api.get('/omni/wallboard/'),
  transcribe:    (eventId)    => api.post(`/omni/events/${eventId}/transcribe/`),
  aiAssist:      (id)         => api.post(`/omni/conversations/${id}/ai-assist/`),
  analytics:     (p)          => api.get('/omni/analytics/', { params: p }),
  automations:   ()           => api.get('/omni/automations/'),
  createAutomation: (data)    => api.post('/omni/automations/', data),
  updateAutomation: (id, d)   => api.patch(`/omni/automations/${id}/`, d),
  deleteAutomation: (id)      => api.delete(`/omni/automations/${id}/`),
  automationRuns:   (p)       => api.get('/omni/automation-runs/', { params: p }),
}

export const pbxApi = {
  agents:         ()        => api.get('/pbx/agents/'),
  myExtension:    ()        => api.get('/pbx/my-extension/'),
  queues:         ()        => api.get('/pbx/queues/'),
  sessions:       (p)       => api.get('/pbx/sessions/', { params: p }),
  session:        (id)      => api.get(`/pbx/sessions/${id}/`),
  live:           ()        => api.get('/pbx/live/'),
  spy:            (data)    => api.post('/pbx/spy/', data),   // {target_ext, mode: listen|whisper}
}

// ── Approvals ─────────────────────────────────────────────────────────────────
export const approvalsApi = {
  // Workflows (admin setup)
  workflows:       (params)      => api.get('/approvals/workflows/', { params }),
  getWorkflow:     (id)          => api.get(`/approvals/workflows/${id}/`),

  // Approval Requests
  requests:        (params)      => api.get('/approvals/requests/', { params }),
  getRequest:      (id)          => api.get(`/approvals/requests/${id}/`),

  // Decision — data: { decision: 'approved'|'rejected', notes? }
  decide:          (id, data)    => api.post(`/approvals/requests/${id}/decide/`, data),

  // Awaiting MY decision; optional { category: 'operational'|'hr'|'finance' }
  pending:         (params)      => api.get('/approvals/requests/pending/', { params }),

  // My pending — shorthand for requests?status=pending&assigned_to_me=true
  myPending:       ()            => api.get('/approvals/requests/', { params: { status: 'pending', assigned_to_me: 'true' } }),
}

// ── Batches / FEFO ────────────────────────────────────────────────────────────
export const batchesApi = {
  // Batch list + detail
  list:            (params)      => api.get('/batches/', { params }),
  get:             (id)          => api.get(`/batches/${id}/`),

  // FEFO recommendation: ?item=&branch=
  fefo:            (itemId, branchId) =>
    api.get('/batches/fefo/', { params: { item: itemId, branch: branchId } }),

  // Near-expiry KPI summary: ?branch=&days=
  nearExpirySummary: (params)    => api.get('/batches/near-expiry/', { params }),

  // Active NearExpiryAlert list: ?branch=&threshold=
  alerts:          (params)      => api.get('/batches/alerts/', { params }),

  // Quarantine a batch — data: { reason }
  quarantine:      (id, reason)  => api.post(`/batches/${id}/quarantine/`, { reason }),

  // ── Purchase-Expiry Physical Audit ──────────────────────────────────────────
  // Candidate worklist: body { from, to, branches?, categories?, only_in_stock?, min_qty? }
  purchaseExpiryCandidates: (body) => api.post('/batches/purchase-expiry/candidates/', body),
  // Export the displayed rows to xlsx: body { items, from, to, branch_label }
  purchaseExpiryExport:     (body) => api.post('/batches/purchase-expiry/export/', body, { responseType: 'blob' }),
  // Supplier dating scorecard: params { months_back?, short_dated_months?, categories? }
  purchaseExpirySupplierScorecard: (params) => api.get('/batches/purchase-expiry/supplier-scorecard/', { params }),
  // Inter-branch rebalancing suggestion: body { item_code, from_branch?, days_to_expiry }
  purchaseExpiryRebalanceSuggest: (body) => api.post('/batches/purchase-expiry/rebalance-suggest/', body),
  // Expiry-prone items (procurement feedback): params { months_back?, short_dated_months?, min_short_pct? }
  purchaseExpiryProneItems: (params) => api.get('/batches/purchase-expiry/expiry-prone/', { params }),
  // A5.2 request a near-expiry markdown (pending discount-approval): body { item_code, discount_pct, days_to_expiry?, branch? }
  purchaseExpiryRequestMarkdown: (body) => api.post('/batches/purchase-expiry/request-markdown/', body),
  // Live stock-expiry (stkbalexpiry mirror across all nodes)
  stockExpirySummary: (params) => api.get('/batches/stock-expiry/summary/', { params }),
  stockExpiryReport:  (params) => api.get('/batches/stock-expiry/report/', { params }),
  stockExpiryStores:  (params) => api.get('/batches/stock-expiry/stores/', { params }),
  stockExpiryRuns:    ()       => api.get('/batches/stock-expiry/runs/'),
  stockExpirySync:    (body)   => api.post('/batches/stock-expiry/sync/', body || {}),
  stockExpiryExport:  (body)   => api.post('/batches/stock-expiry/export/', body, { responseType: 'blob' }),
  stockExpirySpawnCount: (body) => api.post('/batches/stock-expiry/spawn-count/', body),
  // Disposal / return workflow (expired backlog)
  expiryDisposalList:   (params) => api.get('/batches/stock-expiry/disposal/', { params }),
  expiryDisposalCreate: (body)   => api.post('/batches/stock-expiry/disposal/', body),
  expiryDisposalStatus: (id, body) => api.post(`/batches/stock-expiry/disposal/${id}/status/`, body),
  expiryDisposalExport: (body)   => api.post('/batches/stock-expiry/disposal/export/', body, { responseType: 'blob' }),
  // Backfill runs (status)
  purchaseExpiryRuns:       (params) => api.get('/batches/purchase-expiry/runs/', { params }),
  // Trigger a backfill (admin): body { years?|from?|to?, branch?, categories? }
  purchaseExpirySync:       (body) => api.post('/batches/purchase-expiry/sync/', body || {}),
  // Spawn a physical count session: body { branch, from, to, item_codes?, categories?, name? }
  purchaseExpirySpawnCount: (body) => api.post('/batches/purchase-expiry/spawn-count/', body),
}

// ── HR Workflow ───────────────────────────────────────────────────────────────
export const hrApi = {
  // Leave types + balances
  leaveTypes:      (params)      => api.get('/hr/leave-types/', { params }),
  leaveBalances:   (params)      => api.get('/hr/leave-balances/', { params }),

  // Leave requests — creation goes through the `submit/` action, not a bare collection POST
  leaveRequests:   (params)      => api.get('/hr/leave-requests/', { params }),
  getLeaveRequest: (id)          => api.get(`/hr/leave-requests/${id}/`),
  submitLeave:     (data)        => api.post('/hr/leave-requests/submit/', data),
  cancelLeave:     (id)          => api.post(`/hr/leave-requests/${id}/cancel/`),

  // Overtime requests
  overtimeList:    (params)      => api.get('/hr/overtime/', { params }),
  submitOvertime:  (data)        => api.post('/hr/overtime/submit/', data),
  cancelOvertime:  (id)          => api.post(`/hr/overtime/${id}/cancel/`),

  // Salary advances
  advanceList:     (params)      => api.get('/hr/salary-advances/', { params }),
  submitAdvance:   (data)        => api.post('/hr/salary-advances/submit/', data),
  cancelAdvance:   (id)          => api.post(`/hr/salary-advances/${id}/cancel/`),

  // Geofenced attendance (clock in/out)
  attendanceStatus:   ()       => api.get('/hr/attendance/status/'),
  attendanceList:     (params) => api.get('/hr/attendance/', { params }),
  attendanceCheckIn:  (data)   => api.post('/hr/attendance/check-in/', data),
  attendanceCheckOut: (data)   => api.post('/hr/attendance/check-out/', data),

  // Expense claims
  expenseList:     (params)      => api.get('/hr/expense-claims/', { params }),
  submitExpense:   (data)        => api.post('/hr/expense-claims/submit/', data),
  cancelExpense:   (id)          => api.post(`/hr/expense-claims/${id}/cancel/`),

  // Permits (اذن مأمورية / اذن تعديل شيفت)
  permitList:      (params)      => api.get('/hr/permits/', { params }),
  submitPermit:    (data)        => api.post('/hr/permits/submit/', data),
  cancelPermit:    (id)          => api.post(`/hr/permits/${id}/cancel/`),

  // Shifts
  shifts:          (params)      => api.get('/hr/shifts/', { params }),
  shiftAssignments:(params)      => api.get('/hr/shift-assignments/', { params }),
}

// ── Payment Audit ─────────────────────────────────────────────────────────────
export const paymentAuditApi = {
  // Bank statement imports
  statements:      (params)      => api.get('/payments/audit/statements/', { params }),
  getStatement:    (id)          => api.get(`/payments/audit/statements/${id}/`),
  uploadStatement: (formData)    => api.post('/payments/audit/statements/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  runMatching:     (id)          => api.post(`/payments/audit/statements/${id}/run-matching/`),

  // Statement lines
  lines:           (params)      => api.get('/payments/audit/stmt-lines/', { params }),
  manualMatch:     (id, data)    => api.post(`/payments/audit/stmt-lines/${id}/manual-match/`, data),

  // Payment exceptions
  exceptions:      (params)      => api.get('/payments/audit/exceptions/', { params }),
  resolveException:(id, data)    => api.post(`/payments/audit/exceptions/${id}/resolve/`, data),
  dismissException:(id)          => api.post(`/payments/audit/exceptions/${id}/dismiss/`),
  assignException: (id, data)    => api.post(`/payments/audit/exceptions/${id}/assign/`, data),
}

// ── Forecasting ───────────────────────────────────────────────────────────────
export const forecastingApi = {
  // Seasonality indices
  seasonality:       (params)    => api.get('/forecasting/seasonality/', { params }),
  computeSeasonality:()          => api.post('/forecasting/seasonality/compute/'),

  // Forecast runs (audit log)
  runs:              (params)    => api.get('/forecasting/runs/', { params }),
  triggerForecast:   ()          => api.post('/forecasting/runs/trigger/'),

  // Forecast accuracy
  accuracy:          (params)    => api.get('/forecasting/accuracy/', { params }),
  updateActual:      (id, data)  => api.post(`/forecasting/accuracy/${id}/update-actual/`, data),
}

// ── Transfers In Transit ──────────────────────────────────────────────────────

export const transitsApi = {
  list:         (params)  => api.get('/transits/', { params }),
  get:          (id)      => api.get(`/transits/${id}/`),
  exportPicking:      (id)  => api.get(`/transits/${id}/export-picking/`, { responseType: 'blob' }),
  exportPickingBulk:  (ids) => api.post('/transits/export-picking/', { ids }, { responseType: 'blob' }),
  exportStocking:     (id)  => api.get(`/transits/${id}/export-stocking/`, { responseType: 'blob' }),
  exportStockingBulk: (ids) => api.post('/transits/export-stocking/', { ids }, { responseType: 'blob' }),
  markReceived: (id, data) => api.post(`/transits/${id}/mark-received/`, data || {}),
  addNote:      (id, body) => api.post(`/transits/${id}/add-note/`, { body }),
  forceClose:   (id, reason) => api.post(`/transits/${id}/force-close/`, { reason }),
  sync:         ()        => api.post('/transits/sync/'),
  dashboard:    (params)  => api.get('/transits/dashboard/', { params }),
  analytics:    (params)  => api.get('/transits/analytics/', { params }),
  scorecard:    (params)  => api.get('/transits/scorecard/', { params }),
}

// ── Pick zones (replenishment picking-sheet classification) ───────────────────

export const pickZonesApi = {
  // zones — pass { branch: '' } for the default config, { branch: id } for a warehouse config
  listZones:    (params)    => api.get('/transits/pick-zones/', { params }),
  createZone:   (data)      => api.post('/transits/pick-zones/', data),
  updateZone:   (id, data)  => api.patch(`/transits/pick-zones/${id}/`, data),
  deleteZone:   (id)        => api.delete(`/transits/pick-zones/${id}/`),
  seedDefaults: ()          => api.post('/transits/pick-zones/seed-defaults/'),
  copyDefaults: (branch, purpose) => api.post('/transits/pick-zones/copy-defaults/', { branch, purpose }),
  // settings (price threshold — global)
  getSettings:  ()          => api.get('/transits/pick-zones/settings/'),
  saveSettings: (data)      => api.post('/transits/pick-zones/settings/', data),
  // live tester
  preview:      (data)      => api.post('/transits/pick-zones/preview/', data),
  // uncategorized catalog items
  uncategorized:(params)    => api.get('/transits/pick-zones/uncategorized/', { params }),
  // item-master column values (rule dropdowns)
  fieldValues:  (field)     => api.get('/transits/pick-zones/field-values/', { params: { field } }),
  // bulk classification (products-table column)
  classifyItems:(codes, branch) => api.post('/transits/pick-zones/classify-items/', { codes, branch: branch || null }),
  // rules
  listRules:    (params)    => api.get('/transits/pick-rules/', { params }),
  createRule:   (data)      => api.post('/transits/pick-rules/', data),
  updateRule:   (id, data)  => api.patch(`/transits/pick-rules/${id}/`, data),
  deleteRule:   (id)        => api.delete(`/transits/pick-rules/${id}/`),
  reorderRules: (ids)       => api.post('/transits/pick-rules/reorder/', { ordered_ids: ids }),
  // per-item overrides
  listOverrides:  (params)      => api.get('/transits/item-overrides/', { params }),
  createOverride: (data)        => api.post('/transits/item-overrides/', data),
  updateOverride: (id, data)    => api.patch(`/transits/item-overrides/${id}/`, data),
  deleteOverride: (id)          => api.delete(`/transits/item-overrides/${id}/`),
}
