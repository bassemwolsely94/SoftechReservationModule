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
  login: (username, password) => api.post('/auth/login/', { username, password }),
  me: () => api.get('/auth/me/'),
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

  // Chatter
  activities:   (id) => api.get(`/reservations/${id}/activities/`),
  logActivity:  (id, formData) =>
    api.post(`/reservations/${id}/log/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
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
  topItems:     (id) => api.get(`/customers/${id}/top_items/`),
  addNote:      (id, note) => api.post(`/customers/${id}/notes/`, { note }),
  deleteNote:   (customerId, noteId) =>
    api.delete(`/customers/${customerId}/notes/${noteId}/`),
  updateConditions: (id, chronic_conditions) =>
    api.patch(`/customers/${id}/update_conditions/`, { chronic_conditions }),
}


// ── Items ─────────────────────────────────────────────────────────────────────

export const itemsApi = {
  list:  (params) => api.get('/items/', { params }),
  get:   (id) => api.get(`/items/${id}/`),
  stock: (id) => api.get(`/items/${id}/stock/`),
}

// ── Branches ──────────────────────────────────────────────────────────────────

export const branchesApi = {
  list: () => api.get('/branches/'),
}

// ── Sync ──────────────────────────────────────────────────────────────────────

export const syncApi = {
  status:  () => api.get('/sync/status/'),
  trigger: (full = false) => api.post('/sync/trigger/', { full }),
  logs:    () => api.get('/sync/logs/'),
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export const dashboardApi = {
  summary:   (params) => api.get('/dashboard/summary/', { params }),
  followups: ()       => api.get('/dashboard/followups/'),
  purchasing:(days)   => api.get('/dashboard/purchasing/', { params: { days } }),
}


// ── Notifications ─────────────────────────────────────────────────────────────

export const notificationsApi = {
  list:        (params = {}) => api.get('/notifications/', { params }),
  unreadCount: ()            => api.get('/notifications/unread-count/'),
  markRead:    (id)          => api.post(`/notifications/${id}/read/`),
  markAllRead: ()            => api.post('/notifications/mark-all-read/'),
  deleteOne:   (id)          => api.delete(`/notifications/${id}/`),
  clearAll:    ()            => api.delete('/notifications/clear-all/'),
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
  approve:    (id)         => api.post(`/transfers/${id}/approve/`),
  reject:     (id, data)   => api.post(`/transfers/${id}/reject/`, data),
  revision:   (id, data)   => api.post(`/transfers/${id}/revision/`, data),
  sendToERP:  (id, data)   => api.post(`/transfers/${id}/send-to-erp/`, data),
  complete:   (id)         => api.post(`/transfers/${id}/complete/`),
  cancel:     (id)         => api.post(`/transfers/${id}/cancel/`),

  // Item management
  addItem:    (id, data)   => api.post(`/transfers/${id}/items/`, data),
  removeItem: (id, itemId) => api.delete(`/transfers/${id}/items/${itemId}/`),
  updateItem: (id, itemId, data) => api.patch(`/transfers/${id}/items/${itemId}/`, data),

  // Chatter
  sendMessage: (id, data)  => api.post(`/transfers/${id}/messages/`, data),

  // Stock lookup
  itemStock:  (itemId)     => api.get('/transfers/item_stock/', { params: { item_id: itemId } }),

  // Delivery dispatch — POST { delivery_person_name }
  dispatch: (id, data) => api.post(`/transfers/${id}/record-dispatch/`, data),

  // ERP stktrans reference validation — POST { doc_number }
  // Returns { valid, doc_number, branch_code, doc_date, doc_value }
  validateErpRef: (id, data) => api.post(`/transfers/${id}/validate-erp-ref/`, data),
}




export const purchasingApi = {
  dashboard: (days = 30) =>
    api.get('/dashboard/purchasing/', { params: { days } }),
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

  // Dashboard
  dashboard: (params) => api.get('/demand/dashboard/', { params }),
}

// ── Chronic Classifier ────────────────────────────────────────────────────────

// ── Invoices ──────────────────────────────────────────────────────────────────

export const invoicesApi = {
  list:          (params)       => api.get('/invoices/invoices/', { params }),
  get:           (id)           => api.get(`/invoices/invoices/${id}/`),
  create:        (formData)     => api.post('/invoices/invoices/', formData, {
                                    headers: { 'Content-Type': 'multipart/form-data' },
                                  }),
  updateHeader:  (id, data)     => api.patch(`/invoices/invoices/${id}/update-header/`, data),
  addLine:       (id, data)     => api.post(`/invoices/invoices/${id}/add-line/`, data),
  updateLine:    (id, lid, data)=> api.patch(`/invoices/invoices/${id}/lines/${lid}/`, data),
  deleteLine:    (id, lid)      => api.delete(`/invoices/invoices/${id}/lines/${lid}/delete/`),
  lineMatches:   (id, lid)      => api.get(`/invoices/invoices/${id}/lines/${lid}/matches/`),
  runOcr:        (id)           => api.post(`/invoices/invoices/${id}/run-ocr/`),
  confirm:       (id)           => api.post(`/invoices/invoices/${id}/confirm/`),
  reject:        (id)           => api.post(`/invoices/invoices/${id}/reject/`),
}

// ── Vouchers ──────────────────────────────────────────────────────────────────

export const vouchersApi = {
  list:        (params)       => api.get('/vouchers/vouchers/', { params }),
  get:         (id)           => api.get(`/vouchers/vouchers/${id}/`),
  create:      (data)         => api.post('/vouchers/vouchers/', data),
  update:      (id, data)     => api.patch(`/vouchers/vouchers/${id}/`, data),
  cancel:      (id)           => api.post(`/vouchers/vouchers/${id}/cancel/`),
  lookup:      (code)         => api.get('/vouchers/vouchers/lookup/', { params: { code } }),
  generateOtp: (id, phone)    => api.post(`/vouchers/vouchers/${id}/generate-otp/`, { phone }),
  verifyOtp:   (id, code, phone) => api.post(`/vouchers/vouchers/${id}/verify-otp/`, { code, phone }),
  redemptions: (id)           => api.get(`/vouchers/vouchers/${id}/redemptions/`),
}

// ── Shortage ──────────────────────────────────────────────────────────────────

export const shortageApi = {
  list:         (params)       => api.get('/shortage/lists/', { params }),
  get:          (id)           => api.get(`/shortage/lists/${id}/`),
  create:       (data)         => api.post('/shortage/lists/', data),
  addItem:      (id, data)     => api.post(`/shortage/lists/${id}/add-item/`, data),
  bulkImport:   (id, data)     => api.post(`/shortage/lists/${id}/bulk-import/`, data),
  itemMatches:  (id, iid)      => api.get(`/shortage/lists/${id}/items/${iid}/matches/`),
  updateItem:   (id, iid, data)=> api.patch(`/shortage/lists/${id}/items/${iid}/`, data),
  deleteItem:   (id, iid)      => api.delete(`/shortage/lists/${id}/items/${iid}/delete/`),
  submit:       (id)           => api.post(`/shortage/lists/${id}/submit/`),
  resolve:      (id)           => api.post(`/shortage/lists/${id}/resolve/`),
  exportCsv:    (id)           => api.get(`/shortage/lists/${id}/export/`, { responseType: 'blob' }),
}

// ── Stock Count ───────────────────────────────────────────────────────────────

export const stockCountApi = {
  list:       (params) => api.get('/stockcount/sessions/', { params }),
  get:        (id)     => api.get(`/stockcount/sessions/${id}/`),
  create:     (data)   => api.post('/stockcount/sessions/', data),
  importErp:  (id, data) => api.post(`/stockcount/sessions/${id}/import-erp/`, data),
  addItem:    (id, data) => api.post(`/stockcount/sessions/${id}/add-item/`, data),
  updateLine: (id, lid, data) => api.patch(`/stockcount/sessions/${id}/lines/${lid}/`, data),
  complete:   (id)     => api.post(`/stockcount/sessions/${id}/complete/`),
  exportCsv:  (id)     => api.get(`/stockcount/sessions/${id}/export/`, { responseType: 'blob' }),
}

// ── Config / Settings ─────────────────────────────────────────────────────────

export const configApi = {
  // System settings
  listSettings:   (params) => api.get('/config/settings/', { params }),
  updateSetting:  (id, value) => api.patch(`/config/settings/${id}/`, { value }),
  bulkUpdate:     (data)    => api.post('/config/settings/bulk_update/', data),
  byKey:          (keys)    => api.post('/config/settings/by_key/', { keys }),

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

  // Calculate (POST action on a program)
  calculate:      (id, data)     => api.post(`/incentives/programs/${id}/calculate/`, data),

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

  // Transactions (read-only)
  listTransactions: (params)     => api.get('/incentives/transactions/', { params }),

  // Settlements
  listSettlements: (params)      => api.get('/incentives/settlements/', { params }),
  getSettlement:   (id)          => api.get(`/incentives/settlements/${id}/`),
  receipt:         (id)          => api.get(`/incentives/settlements/${id}/receipt/`),
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

