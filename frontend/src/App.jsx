import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import useAuthStore from './store/authStore'
import useLangStore from './store/langStore'
import usePermissionStore from './store/permissionStore'
import { initPush } from './push'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import NotifyPage from './pages/NotifyPage'
import DashboardPage from './pages/DashboardPage'
import MyDashboardPage from './pages/MyDashboardPage'
import NotificationsInboxPage from './pages/NotificationsInboxPage'
import TargetsPage from './pages/TargetsPage'
import KpiBoardPage from './pages/KpiBoardPage'
import ForecastScenarioPage from './pages/ForecastScenarioPage'
import InsightsPage from './pages/InsightsPage'
import AnnouncementsPage from './pages/AnnouncementsPage'
import ReservationsKanban from './pages/ReservationsKanban'
import ReservationsPage from './pages/ReservationsPage'
import NewReservationPage from './pages/NewReservationPage'
import ReservationDetailPage from './pages/ReservationDetailPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import SyncPage from './pages/SyncPage'
import TransfersPage from './pages/TransfersPage'
import TransitsPage from './pages/TransitsPage'
import NewTransferPage from './pages/NewTransferPage'
import TransferDetailPage from './pages/TransferDetailPage'
import PurchasingDashboard from './pages/PurchasingDashboard'
import ChronicClassifierPage from './pages/ChronicClassifierPage'
import SettingsPage from './pages/SettingsPage'
import StockCountPage from './pages/StockCountPage'
import ShortagePage from './pages/ShortagePage'
import POSOrderPage from './pages/POSOrderPage'
import VouchersPage from './pages/VouchersPage'
import InvoicePage from './pages/InvoicePage'
import IncentivesPage from './pages/IncentivesPage'
import InsuranceClaimsPage from './pages/InsuranceClaimsPage'
import InsurancePrintProfilesPage from './pages/InsurancePrintProfilesPage'
import InsuranceClaimDetailPage from './pages/InsuranceClaimDetailPage'
import InsurancePrintPage from './pages/InsurancePrintPage'
import InsuranceClientsPage from './pages/InsuranceClientsPage'
import InsuranceItemOverridesPage from './pages/InsuranceItemOverridesPage'
import MyIncentivesPage from './pages/MyIncentivesPage'
import UserManagementPage from './pages/UserManagementPage'
import PermissionsMatrixPage from './pages/PermissionsMatrixPage'
import PickZonesPage from './pages/PickZonesPage'
import ErpPermissionsPage from './pages/ErpPermissionsPage'
import DeliveryDashboard from './pages/DeliveryDashboard'
import DeliveryAnalyticsPage from './pages/DeliveryAnalyticsPage'
import DriverDeliveryApp from './pages/DriverDeliveryApp'
import DispatchBoard from './pages/DispatchBoard'
import RiderLayout from './components/RiderLayout'
import MobileLayout from './components/MobileLayout'
import MobilePOSOrderPage from './pages/mobile/MobilePOSOrderPage'
import MobileReservationsPage from './pages/mobile/MobileReservationsPage'
import MobileNewReservationPage from './pages/mobile/MobileNewReservationPage'
import MobileReservationDetailPage from './pages/mobile/MobileReservationDetailPage'
import MobileTransfersPage from './pages/mobile/MobileTransfersPage'
import MobileNewTransferPage from './pages/mobile/MobileNewTransferPage'
import MobileTransferDetailPage from './pages/mobile/MobileTransferDetailPage'
import MobileApprovalsPage from './pages/mobile/MobileApprovalsPage'
import MobileShortagePage from './pages/mobile/MobileShortagePage'
import MobileNewShortagePage from './pages/mobile/MobileNewShortagePage'
import MobileShortageDetailPage from './pages/mobile/MobileShortageDetailPage'
import MobileDeliveryPage from './pages/mobile/MobileDeliveryPage'
import MobileDeliveryDetailPage from './pages/mobile/MobileDeliveryDetailPage'
import MobileDemandPage from './pages/mobile/MobileDemandPage'
import MobileNewDemandPage from './pages/mobile/MobileNewDemandPage'
import MobileDemandDetailPage from './pages/mobile/MobileDemandDetailPage'
import MobileItemsPage from './pages/mobile/MobileItemsPage'
import MobileNotificationsPage from './pages/mobile/MobileNotificationsPage'
import MobileCustomersPage from './pages/mobile/MobileCustomersPage'
import MobileMyIncentivesPage from './pages/mobile/MobileMyIncentivesPage'
import MobileTasksPage from './pages/mobile/MobileTasksPage'
import MobileTaskDetailPage from './pages/mobile/MobileTaskDetailPage'
import MobileVoucherRedeemPage from './pages/mobile/MobileVoucherRedeemPage'
import MobileStockCountPage from './pages/mobile/MobileStockCountPage'
import MobileStockCountDetailPage from './pages/mobile/MobileStockCountDetailPage'
import MobileQAPage from './pages/mobile/MobileQAPage'
import MobileQADetailPage from './pages/mobile/MobileQADetailPage'
import MobileAttendancePage from './pages/mobile/MobileAttendancePage'
import DeliveryTrackPage from './pages/DeliveryTrackPage'
import PaymentTracking from './pages/PaymentTracking'
import SalesDashboard from './pages/SalesDashboard'
import PerformanceDashboard from './pages/PerformanceDashboard'
import InventoryDashboard from './pages/InventoryDashboard'
import TasksPage from './pages/TasksPage'
import TaskDetailPage from './pages/TaskDetailPage'
import TaskDashboardPage from './pages/TaskDashboardPage'
import TaskSchedulesPage from './pages/TaskSchedulesPage'
// Procurement — hub + sub-pages (sub-pages render as tabs inside ProcurementHubPage)
import ProcurementHubPage from './pages/ProcurementHubPage'
import ProcurementDashboard from './pages/ProcurementDashboard'
import SupplierPerformancePage from './pages/SupplierPerformancePage'
import ProcurementMarginPage from './pages/ProcurementMarginPage'
import ProcurementOptimizationPage from './pages/ProcurementOptimizationPage'
import ProcurementHistoryPage from './pages/ProcurementHistoryPage'
import SupplierSegmentationPage from './pages/SupplierSegmentationPage'
import FocAnalysisPage from './pages/FocAnalysisPage'
// Analytics — hub renders Sales + Performance + Reservations + Transfers as tabs
import AnalyticsHubPage from './pages/AnalyticsHubPage'
import ReservationsAnalyticsPage from './pages/ReservationsAnalyticsPage'
import TransfersAnalyticsPage from './pages/TransfersAnalyticsPage'
// Operations — previously missing routes
import CallCenterPage from './pages/CallCenterPage'
import CasesPage from './pages/CasesPage'
import AuditPage from './pages/AuditPage'
import FollowUpsPage from './pages/FollowUpsPage'
import DemandPage from './pages/DemandPage'
import DemandDashboardPage from './pages/DemandDashboardPage'
import DemandRecoveryPage from './pages/DemandRecoveryPage'
import DemandDetailPage from './pages/DemandDetailPage'
// Finance Intelligence Platform
import FinanceHubPage from './pages/FinanceHubPage'
import FinanceDashboardPage from './pages/FinanceDashboardPage'
import ChartOfAccountsPage from './pages/ChartOfAccountsPage'
import ProfitLossPage from './pages/ProfitLossPage'
import CashFlowPage from './pages/CashFlowPage'
import ExpenseAnalyticsPage from './pages/ExpenseAnalyticsPage'
import FinanceSchemaPage from './pages/FinanceSchemaPage'
import ProductCatalogPage from './pages/ProductCatalogPage'
import ProductDetailPage from './pages/ProductDetailPage'
import ProductContentAdminPage from './pages/ProductContentAdminPage'
import WhatsAppCampaignPage from './pages/WhatsAppCampaignPage'
import WhatsAppInboxPage from './pages/WhatsAppInboxPage'
import OmniInboxPage from './pages/OmniInboxPage'
import OmniAccountsPage from './pages/OmniAccountsPage'
import OmniWallboardPage from './pages/OmniWallboardPage'
import OmniAutomationsPage from './pages/OmniAutomationsPage'
import OmniAnalyticsPage from './pages/OmniAnalyticsPage'
import LoyaltyPage from './pages/LoyaltyPage'
import BranchPointsPage from './pages/BranchPointsPage'
import ReferralPage from './pages/ReferralPage'
import PbxLivePage from './pages/PbxLivePage'
import ChequePlanningPage from './pages/ChequePlanningPage'
import CatalogIntelligencePage from './pages/CatalogIntelligencePage'
import ItemIntelPage from './pages/ItemIntelPage'
import ImageEnrichmentPage from './pages/ImageEnrichmentPage'
import RecommendationsPage from './pages/RecommendationsPage'
import CallCenterAnalyticsPage from './pages/CallCenterAnalyticsPage'
import PricingApprovalsPage from './pages/PricingApprovalsPage'
import ApprovalsPage from './pages/ApprovalsPage'
import BatchesPage from './pages/BatchesPage'
import HRPage from './pages/HRPage'
import PaymentAuditPage from './pages/PaymentAuditPage'
import ForecastingPage from './pages/ForecastingPage'
import SecurityPage from './pages/SecurityPage'
// Customer self-service portal (external — magic-link auth, own shell, NOT staff)
import PortalLayout from './pages/portal/PortalLayout'
import PortalLoginPage from './pages/portal/PortalLoginPage'
import PortalAuthPage from './pages/portal/PortalAuthPage'
import PortalHomePage from './pages/portal/PortalHomePage'
import PortalLoyaltyPage from './pages/portal/PortalLoyaltyPage'
import PortalRefillsPage from './pages/portal/PortalRefillsPage'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
})

// Bottom-tab navigation for the standalone mobile surfaces (/m). One tab per
// section; "new" is reached via each list's floating + button (not a tab).
// `roles` (when present) gates the tab; MobileLayout filters by the user's role.
const MOBILE_TABS = [
  { to: '/m/pos',          label: 'نقطة البيع', icon: '🧾', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor'] },
  { to: '/m/reservations', label: 'الحجوزات',  icon: '📋' },
  { to: '/m/transfers',    label: 'التحويلات', icon: '🔀' },
  { to: '/m/demand',       label: 'الطلب الضائع', icon: '🔍', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/shortage',     label: 'النواقص',   icon: '🚨', roles: ['admin', 'pharmacist', 'call_center', 'salesperson', 'purchasing', 'supervisor', 'quality_manager'] },
  { to: '/m/delivery',     label: 'التوصيل',   icon: '🚚', roles: ['admin', 'call_center', 'supervisor', 'quality_manager', 'pharmacist'] },
  { to: '/m/approvals',    label: 'الموافقات', icon: '✔️', roles: ['admin', 'supervisor', 'purchasing'], badge: 'approvals' },
  { to: '/m/items',        label: 'الأصناف',   icon: '🔎' },
  { to: '/m/customers',    label: 'العملاء',   icon: '👥', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/vouchers',     label: 'القسائم',   icon: '🎫', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/tasks',        label: 'المهام',    icon: '✅', roles: ['admin', 'call_center', 'pharmacist', 'supervisor'] },
  { to: '/m/stock-count',  label: 'الجرد',     icon: '📦', roles: ['admin', 'pharmacist', 'supervisor', 'quality_manager'] },
  { to: '/m/qa',           label: 'مراجعة الجودة', icon: '🧹', roles: ['admin', 'quality_manager', 'supervisor', 'pharmacist'] },
  { to: '/m/attendance',   label: 'الحضور',    icon: '🕐' },
  { to: '/m/my-incentives', label: 'حوافزي',   icon: '🏅' },
]

function RequireAuth({ children }) {
  const { isAuthenticated, isLoading } = useAuthStore()
  if (isLoading) return (
    <div className="min-h-screen flex items-center justify-center bg-brand-50">
      <div className="text-brand-600 text-xl font-cairo font-semibold animate-pulse">
        صيدليات الرزيقي...
      </div>
    </div>
  )
  return isAuthenticated ? children : <Navigate to="/login" replace />
}

function RequireRole({ roles, children }) {
  const { user } = useAuthStore()
  const userRole = user?.role || 'viewer'
  if (!roles.includes(userRole)) return <Navigate to="/dashboard" replace />
  return children
}

export default function App() {
  const loadMe        = useAuthStore(s => s.loadMe)
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const initLang      = useLangStore(s => s.init)
  const loadPerms     = usePermissionStore(s => s.load)
  const resetPerms    = usePermissionStore(s => s.reset)

  useEffect(() => { loadMe(); initLang() }, [loadMe, initLang])

  // Load permissions whenever auth state becomes true; reset on logout
  useEffect(() => {
    if (isAuthenticated) {
      loadPerms()
      // Silently re-sync the Web Push subscription if the user already granted
      // permission on this device (never prompts here — opt-in is on the bell).
      initPush()
    } else {
      resetPerms()
    }
  }, [isAuthenticated, loadPerms, resetPerms])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/notify" element={<NotifyPage />} />
          {/* Public customer delivery tracking (tokenized, no login) */}
          <Route path="/track/:token" element={<DeliveryTrackPage />} />

          {/* ── Customer self-service portal (external; magic-link auth) ──────
              Fully isolated from staff auth: own API client, own session token,
              own shell. Sits OUTSIDE RequireAuth. */}
          <Route path="/portal/login"       element={<PortalLoginPage />} />
          <Route path="/portal/auth/:token" element={<PortalAuthPage />} />
          <Route path="/portal" element={<PortalLayout />}>
            <Route index            element={<PortalHomePage />} />
            <Route path="refills"    element={<PortalRefillsPage />} />
            <Route path="loyalty"    element={<PortalLoyaltyPage />} />
          </Route>
          {/* Standalone mobile rider screen (no desktop sidebar) */}
          <Route path="/rider" element={<RequireAuth><RiderLayout><DriverDeliveryApp /></RiderLayout></RequireAuth>} />

          {/* ── Standalone mobile web surfaces (no desktop sidebar) ─────────
              Phone-friendly, thin views over the existing APIs. Pilot: reservations.
              Reached at /m — bookmark on a phone home screen. */}
          <Route path="/m" element={<RequireAuth><MobileLayout title="صيدليات الرزيقي" tabs={MOBILE_TABS} /></RequireAuth>}>
            <Route index element={<Navigate to="/m/reservations" replace />} />
            <Route path="pos"               element={<MobilePOSOrderPage />} />
            <Route path="reservations"      element={<MobileReservationsPage />} />
            <Route path="reservations/new"  element={<MobileNewReservationPage />} />
            <Route path="reservations/:id"  element={<MobileReservationDetailPage />} />
            <Route path="transfers"         element={<MobileTransfersPage />} />
            <Route path="transfers/new"     element={<MobileNewTransferPage />} />
            <Route path="transfers/:id"     element={<MobileTransferDetailPage />} />
            <Route path="approvals"         element={<MobileApprovalsPage />} />
            <Route path="shortage"          element={<MobileShortagePage />} />
            <Route path="shortage/new"      element={<MobileNewShortagePage />} />
            <Route path="shortage/:id"      element={<MobileShortageDetailPage />} />
            <Route path="delivery"          element={<MobileDeliveryPage />} />
            <Route path="delivery/:id"      element={<MobileDeliveryDetailPage />} />
            <Route path="demand"            element={<MobileDemandPage />} />
            <Route path="demand/new"        element={<MobileNewDemandPage />} />
            <Route path="demand/:id"        element={<MobileDemandDetailPage />} />
            <Route path="items"             element={<MobileItemsPage />} />
            <Route path="notifications"     element={<MobileNotificationsPage />} />
            <Route path="customers"         element={<MobileCustomersPage />} />
            <Route path="my-incentives"     element={<MobileMyIncentivesPage />} />
            <Route path="tasks"             element={<MobileTasksPage />} />
            <Route path="tasks/:id"         element={<MobileTaskDetailPage />} />
            <Route path="vouchers"          element={<MobileVoucherRedeemPage />} />
            <Route path="stock-count"       element={<MobileStockCountPage />} />
            <Route path="stock-count/:id"   element={<MobileStockCountDetailPage />} />
            <Route path="qa"                element={<MobileQAPage />} />
            <Route path="qa/:id"            element={<MobileQADetailPage />} />
            <Route path="attendance"        element={<MobileAttendancePage />} />
          </Route>

          <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<Navigate to="/dashboard" replace />} />

            {/* ── Core ─────────────────────────────────────────────────── */}
            <Route path="dashboard"          element={<DashboardPage />} />
            <Route path="me"                 element={<MyDashboardPage />} />
            <Route path="security"           element={<SecurityPage />} />{/* 2FA self-service — all roles */}
            <Route path="notifications"      element={<NotificationsInboxPage />} />
            <Route path="announcements"      element={<AnnouncementsPage />} />
            <Route path="targets"            element={<TargetsPage />} />
            <Route path="kpi-board"          element={<KpiBoardPage />} />
            <Route path="forecast-scenarios" element={<ForecastScenarioPage />} />
            <Route path="insights"           element={<InsightsPage />} />

            {/* ── Operations ───────────────────────────────────────────── */}
            <Route path="reservations"       element={<ReservationsKanban />} />
            <Route path="reservations/list"  element={<ReservationsPage />} />
            <Route path="reservations/new"   element={<NewReservationPage />} />
            <Route path="reservations/:id"   element={<ReservationDetailPage />} />
            <Route path="transfers"          element={<TransfersPage />} />
            <Route path="transits"           element={<TransitsPage />} />
            <Route path="transfers/new"      element={<NewTransferPage />} />
            <Route path="transfers/:id"      element={<TransferDetailPage />} />
            <Route path="delivery"           element={<DeliveryDashboard />} />
            <Route path="delivery/dispatch"  element={<DispatchBoard />} />
            <Route path="delivery/my"        element={<DriverDeliveryApp />} />
            <Route path="delivery/analytics" element={<DeliveryAnalyticsPage />} />
            <Route path="payments"           element={<PaymentTracking />} />
            <Route path="tasks"              element={<TasksPage />} />
            <Route path="tasks/dashboard"    element={<TaskDashboardPage />} />
            <Route path="tasks/schedules"    element={<TaskSchedulesPage />} />
            <Route path="tasks/:id"          element={<TaskDetailPage />} />

            {/* ── Call Center & Follow-Ups ─────────────────────────────── */}
            <Route path="callcenter"            element={<CallCenterPage />} />
            <Route path="callcenter/cases"      element={<CasesPage />} />
            <Route path="callcenter/analytics"  element={<CallCenterAnalyticsPage />} />
            <Route path="followups"             element={<FollowUpsPage />} />

            {/* ── WhatsApp ─────────────────────────────────────────────── */}
            <Route path="campaigns"          element={<WhatsAppCampaignPage />} />
            <Route path="whatsapp/inbox"     element={<WhatsAppInboxPage />} />

            {/* ── Omni — unified omnichannel inbox (doc 15) ────────────── */}
            <Route path="omni/inbox"         element={<OmniInboxPage />} />
            <Route path="omni/accounts"      element={<OmniAccountsPage />} />
            <Route path="omni/wallboard"     element={<OmniWallboardPage />} />
            <Route path="omni/automations"   element={<OmniAutomationsPage />} />
            <Route path="omni/analytics"     element={<OmniAnalyticsPage />} />

            {/* ── Loyalty & Referral ────────────────────────────────────── */}
            <Route path="loyalty"            element={<LoyaltyPage />} />
            <Route path="loyalty/branch"     element={<BranchPointsPage />} />
            <Route path="referral"           element={<ReferralPage />} />

            {/* ── PBX Live Dashboard ───────────────────────────────────── */}
            <Route path="pbx/live"           element={<PbxLivePage />} />

            {/* ── Cheque Planning + Treasury ───────────────────────────── */}
            {/* cheques guarded below in Administration section */}

            {/* ── Demand / Lost Sales ──────────────────────────────────── */}
            <Route path="demand"             element={<DemandPage />} />
            <Route path="demand/dashboard"   element={<DemandDashboardPage />} />
            <Route path="demand/recovery"    element={<DemandRecoveryPage />} />
            <Route path="demand/:id"         element={<DemandDetailPage />} />

            {/* ── Customers ────────────────────────────────────────────── */}
            <Route path="customers"          element={<CustomersPage />} />
            <Route path="customers/:id"      element={<CustomerDetailPage />} />
            <Route path="vouchers"           element={<VouchersPage />} />
            <Route path="chronic-classifier" element={<ChronicClassifierPage />} />

            {/* ── Inventory ────────────────────────────────────────────── */}
            <Route path="products"           element={<ProductCatalogPage />} />
            <Route path="products/:id"       element={<ProductDetailPage />} />
            <Route path="products/:id/admin" element={<ProductContentAdminPage />} />
            <Route path="products/:id/intel" element={<ItemIntelPage />} />
            <Route path="catalog-intelligence"  element={<CatalogIntelligencePage />} />
            <Route path="image-enrichment"      element={<ImageEnrichmentPage />} />
            <Route path="pricing-approvals"     element={<PricingApprovalsPage />} />
            <Route path="pos"                   element={<POSOrderPage />} />
            <Route path="recommendations"       element={<RecommendationsPage />} />
            <Route path="inventory"          element={<InventoryDashboard />} />
            <Route path="stock-count"        element={<StockCountPage />} />
            <Route path="shortage"           element={<ShortagePage />} />
            <Route path="purchasing"         element={<PurchasingDashboard />} />

            {/* ── Procurement hub (4 tabs) ──────────────────────────────
                /procurement              → redirects to /procurement/overview
                /procurement/overview     → ProcurementDashboard
                /procurement/history      → ProcurementHistoryPage
                /procurement/segments     → SupplierSegmentationPage
                /procurement/foc          → FocAnalysisPage
            ─────────────────────────────────────────────────────────── */}
            <Route path="procurement" element={<ProcurementHubPage />}>
              <Route index element={<Navigate to="overview" replace />} />
              <Route path="overview"     element={<ProcurementDashboard />} />
              <Route path="history"      element={<ProcurementHistoryPage />} />
              <Route path="segments"     element={<SupplierSegmentationPage />} />
              <Route path="foc"          element={<FocAnalysisPage />} />
              {/* Legacy deep-links kept working */}
              <Route path="suppliers"            element={<SupplierPerformancePage />} />
              <Route path="suppliers/:supplierCode" element={<SupplierPerformancePage />} />
              <Route path="margins"              element={<ProcurementMarginPage />} />
              <Route path="optimization"         element={<ProcurementOptimizationPage />} />
              <Route path="mappings"             element={<ProcurementOptimizationPage />} />
            </Route>

            {/* ── Procurement operational ──────────────────────────────── */}
            {/* invoices + incentives guarded below in Administration section */}
            <Route path="my-incentives" element={<MyIncentivesPage />} />

            {/* ── Insurance Claims Module ───────────────────────────────── */}
            <Route path="insurance"                           element={<InsuranceClaimsPage />} />
            <Route path="insurance/clients"                   element={<InsuranceClientsPage />} />
            <Route path="insurance/item-overrides"            element={<InsuranceItemOverridesPage />} />
            <Route path="insurance/print-profiles"            element={<InsurancePrintProfilesPage />} />
            <Route path="insurance/claims/:id"                element={<InsuranceClaimDetailPage />} />
            <Route path="insurance/claims/:id/print"          element={<InsurancePrintPage />} />

            {/* ── Analytics hub (2 tabs) ────────────────────────────────
                /analytics              → redirects to /analytics/sales
                /analytics/sales        → SalesDashboard
                /analytics/performance  → PerformanceDashboard
                Legacy: /sales and /performance redirect here.
            ─────────────────────────────────────────────────────────── */}
            <Route path="analytics" element={<AnalyticsHubPage />}>
              <Route index element={<Navigate to="sales" replace />} />
              <Route path="sales"         element={<SalesDashboard />} />
              <Route path="performance"   element={<PerformanceDashboard />} />
              <Route path="reservations"  element={<ReservationsAnalyticsPage />} />
              <Route path="transfers"    element={<TransfersAnalyticsPage />} />
            </Route>
            {/* Legacy redirects so any saved links still work */}
            <Route path="sales"       element={<Navigate to="/analytics/sales"       replace />} />
            <Route path="performance" element={<Navigate to="/analytics/performance" replace />} />

            {/* ── Finance Intelligence Platform ──────────────────────── */}
            <Route path="finance" element={<FinanceHubPage />}>
              <Route index element={<Navigate to="dashboard" replace />} />
              <Route path="dashboard" element={<FinanceDashboardPage />} />
              <Route path="coa"       element={<ChartOfAccountsPage />} />
              <Route path="pnl"       element={<ProfitLossPage />} />
              <Route path="cashflow"  element={<CashFlowPage />} />
              <Route path="expenses"  element={<ExpenseAnalyticsPage />} />
              <Route path="schema"    element={<FinanceSchemaPage />} />
            </Route>

            {/* ── Administration ───────────────────────────────────────── */}
            {/* audit: admin + supervisor + quality_manager can review */}
            <Route path="audit"
              element={<RequireRole roles={['admin','supervisor','quality_manager']}><AuditPage /></RequireRole>} />
            {/* users: admin manages; supervisor can view */}
            <Route path="users"
              element={<RequireRole roles={['admin','supervisor']}><UserManagementPage /></RequireRole>} />
            {/* pick zones: picking-sheet classification (read: all staff) */}
            <Route path="pick-zones" element={<PickZonesPage />} />
            {/* permissions matrix: admin only */}
            <Route path="permissions"
              element={<RequireRole roles={['admin']}><PermissionsMatrixPage /></RequireRole>} />
            {/* SOFTECH inherited permissions: admin only */}
            <Route path="erp-permissions"
              element={<RequireRole roles={['admin']}><ErpPermissionsPage /></RequireRole>} />
            {/* settings: admin + pharmacist (own branch settings) */}
            <Route path="settings"
              element={<RequireRole roles={['admin','pharmacist']}><SettingsPage /></RequireRole>} />
            {/* sync: admin only */}
            <Route path="sync"
              element={<RequireRole roles={['admin']}><SyncPage /></RequireRole>} />
            {/* procurement: purchasing + admin */}
            <Route path="invoices"
              element={<RequireRole roles={['admin','purchasing']}><InvoicePage /></RequireRole>} />
            {/* incentives: admin + purchasing + quality_manager */}
            <Route path="incentives"
              element={<RequireRole roles={['admin','purchasing','quality_manager']}><IncentivesPage /></RequireRole>} />
            {/* cheques + finance: admin + purchasing + pharmacist */}
            <Route path="cheques"
              element={<RequireRole roles={['admin','purchasing','pharmacist']}><ChequePlanningPage /></RequireRole>} />

            {/* ── New Modules (Phases 1–5) ─────────────────────────────── */}
            {/* approvals inbox: roles that approve something (server still enforces per-step eligibility) */}
            <Route path="approvals"     element={<RequireRole roles={['admin','supervisor','pharmacist','quality_manager','purchasing']}><ApprovalsPage /></RequireRole>} />
            <Route path="batches"       element={<BatchesPage />} />
            <Route path="hr"            element={<HRPage />} />
            <Route path="payment-audit" element={<RequireRole roles={['admin','purchasing','pharmacist']}><PaymentAuditPage /></RequireRole>} />
            <Route path="forecasting"   element={<RequireRole roles={['admin','purchasing','pharmacist','quality_manager']}><ForecastingPage /></RequireRole>} />

          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
