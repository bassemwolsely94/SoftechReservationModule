/**
 * mobileAccess.js — which roles see a mobile section, following the RBAC matrix's view grant
 * (Batch 4, Z-11i). Shared by the tab bar (App.jsx) and the pages that redirect away.
 */
export const MOBILE_RESERVATION_ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'viewer', 'supervisor', 'quality_manager']
export const MOBILE_TRANSFER_ROLES = ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'viewer', 'supervisor', 'quality_manager']
