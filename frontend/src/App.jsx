import { lazy, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import useAuthStore from './store/authStore'
import useLangStore from './store/langStore'
import usePermissionStore from './store/permissionStore'
import { initPush } from './push'
import Layout from './components/Layout'
import { RequireAuth, RequireRole } from './components/RouteGuards'
import LoginPage from './pages/LoginPage'
const NotifyPage = lazy(() => import('./pages/NotifyPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const MyDashboardPage = lazy(() => import('./pages/MyDashboardPage'))
const NotificationsInboxPage = lazy(() => import('./pages/NotificationsInboxPage'))
const TargetsPage = lazy(() => import('./pages/TargetsPage'))
const KpiBoardPage = lazy(() => import('./pages/KpiBoardPage'))
const SalespersonBoardPage = lazy(() => import('./pages/SalespersonBoardPage'))
const ForecastScenarioPage = lazy(() => import('./pages/ForecastScenarioPage'))
const InsightsPage = lazy(() => import('./pages/InsightsPage'))
const ReferralStatsPage = lazy(() => import('./pages/ReferralStatsPage'))
const VisionCorpusPage = lazy(() => import('./pages/VisionCorpusPage'))
const AnnouncementsPage = lazy(() => import('./pages/AnnouncementsPage'))
const ReservationsKanban = lazy(() => import('./pages/ReservationsKanban'))
const ReservationsPage = lazy(() => import('./pages/ReservationsPage'))
const NewReservationPage = lazy(() => import('./pages/NewReservationPage'))
const MissedSalesPage = lazy(() => import('./pages/MissedSalesPage'))
const ReservationDetailPage = lazy(() => import('./pages/ReservationDetailPage'))
const CustomersPage = lazy(() => import('./pages/CustomersPage'))
const CustomerDetailPage = lazy(() => import('./pages/CustomerDetailPage'))
const SyncPage = lazy(() => import('./pages/SyncPage'))
const TrustedNetworksPage = lazy(() => import('./pages/TrustedNetworksPage'))
const DevicesPage = lazy(() => import('./pages/DevicesPage'))
const ZonePolicyPage = lazy(() => import('./pages/ZonePolicyPage'))
const TransfersPage = lazy(() => import('./pages/TransfersPage'))
const TransitsPage = lazy(() => import('./pages/TransitsPage'))
const NewTransferPage = lazy(() => import('./pages/NewTransferPage'))
const TransferDetailPage = lazy(() => import('./pages/TransferDetailPage'))
const PurchasingDashboard = lazy(() => import('./pages/PurchasingDashboard'))
const MarketShortagePage = lazy(() => import('./pages/MarketShortagePage'))
const PhantomSalesPage = lazy(() => import('./pages/PhantomSalesPage'))
const CashOptimizationPage = lazy(() => import('./pages/CashOptimizationPage'))
const ChronicClassifierPage = lazy(() => import('./pages/ChronicClassifierPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const StockCountPage = lazy(() => import('./pages/StockCountPage'))
const ShortagePage = lazy(() => import('./pages/ShortagePage'))
const POSOrderPage = lazy(() => import('./pages/POSOrderPage'))
const ExceptionCenterPage = lazy(() => import('./pages/ExceptionCenterPage'))
const VouchersPage = lazy(() => import('./pages/VouchersPage'))
const RefillRemindersPage = lazy(() => import('./pages/RefillRemindersPage'))
const CustomerMergePage = lazy(() => import('./pages/CustomerMergePage'))
const OffersPage = lazy(() => import('./pages/OffersPage'))
const InvoicePage = lazy(() => import('./pages/InvoicePage'))
const IncentivesPage = lazy(() => import('./pages/IncentivesPage'))
const InsuranceClaimsPage = lazy(() => import('./pages/InsuranceClaimsPage'))
const CommerceDocumentsPage = lazy(() => import('./pages/CommerceDocumentsPage'))
const CommerceDocumentEditorPage = lazy(() => import('./pages/CommerceDocumentEditorPage'))
const InsurancePrintProfilesPage = lazy(() => import('./pages/InsurancePrintProfilesPage'))
const InsuranceClaimDetailPage = lazy(() => import('./pages/InsuranceClaimDetailPage'))
const InsurancePrintPage = lazy(() => import('./pages/InsurancePrintPage'))
const InsuranceClientsPage = lazy(() => import('./pages/InsuranceClientsPage'))
const InsuranceItemOverridesPage = lazy(() => import('./pages/InsuranceItemOverridesPage'))
const InsuranceSeparationListsPage = lazy(() => import('./pages/InsuranceSeparationListsPage'))
const InsuranceRostersPage = lazy(() => import('./pages/InsuranceRostersPage'))
const InsuranceReportsPage = lazy(() => import('./pages/InsuranceReportsPage'))
const MyIncentivesPage = lazy(() => import('./pages/MyIncentivesPage'))
const GamificationPage = lazy(() => import('./pages/GamificationPage'))
const StockAuditPage = lazy(() => import('./pages/StockAuditPage'))
const PicAnalyticsPage = lazy(() => import('./pages/PicAnalyticsPage'))
const UsagePrintPage = lazy(() => import('./pages/UsagePrintPage'))
const UserManagementPage = lazy(() => import('./pages/UserManagementPage'))
const PermissionsMatrixPage = lazy(() => import('./pages/PermissionsMatrixPage'))
const PickZonesPage = lazy(() => import('./pages/PickZonesPage'))
const PhoneAlertsPage = lazy(() => import('./pages/PhoneAlertsPage'))
const ErpPermissionsPage = lazy(() => import('./pages/ErpPermissionsPage'))
const DeliveryDashboard = lazy(() => import('./pages/DeliveryDashboard'))
const DeliveryAnalyticsPage = lazy(() => import('./pages/DeliveryAnalyticsPage'))
const DriverDeliveryApp = lazy(() => import('./pages/DriverDeliveryApp'))
const DispatchBoard = lazy(() => import('./pages/DispatchBoard'))
import RiderLayout from './components/RiderLayout'
import useNumberInputGuards from './hooks/useNumberInputGuards'
import MobileLayout from './components/MobileLayout'
import PageSuspense from './components/PageSuspense'
const HelpCenterPage = lazy(() => import('./pages/HelpCenterPage'))
const HelpManualPage = lazy(() => import('./pages/HelpManualPage'))
const MobilePOSOrderPage = lazy(() => import('./pages/mobile/MobilePOSOrderPage'))
const MobileReservationsPage = lazy(() => import('./pages/mobile/MobileReservationsPage'))
import { MOBILE_RESERVATION_ROLES, MOBILE_TRANSFER_ROLES } from './pages/mobile/mobileAccess'
const MobileNewReservationPage = lazy(() => import('./pages/mobile/MobileNewReservationPage'))
const MobileReservationDetailPage = lazy(() => import('./pages/mobile/MobileReservationDetailPage'))
const MobileTransfersPage = lazy(() => import('./pages/mobile/MobileTransfersPage'))
const MobileNewTransferPage = lazy(() => import('./pages/mobile/MobileNewTransferPage'))
const MobileTransferDetailPage = lazy(() => import('./pages/mobile/MobileTransferDetailPage'))
const MobileApprovalsPage = lazy(() => import('./pages/mobile/MobileApprovalsPage'))
const MobileShortagePage = lazy(() => import('./pages/mobile/MobileShortagePage'))
const MobileNewShortagePage = lazy(() => import('./pages/mobile/MobileNewShortagePage'))
const MobileShortageDetailPage = lazy(() => import('./pages/mobile/MobileShortageDetailPage'))
const MobileDeliveryPage = lazy(() => import('./pages/mobile/MobileDeliveryPage'))
const MobileDeliveryDetailPage = lazy(() => import('./pages/mobile/MobileDeliveryDetailPage'))
const MobileDemandPage = lazy(() => import('./pages/mobile/MobileDemandPage'))
const MobileNewDemandPage = lazy(() => import('./pages/mobile/MobileNewDemandPage'))
const MobileDemandDetailPage = lazy(() => import('./pages/mobile/MobileDemandDetailPage'))
const MobileItemsPage = lazy(() => import('./pages/mobile/MobileItemsPage'))
const MobileNotificationsPage = lazy(() => import('./pages/mobile/MobileNotificationsPage'))
const MobileCustomersPage = lazy(() => import('./pages/mobile/MobileCustomersPage'))
const MobileMyIncentivesPage = lazy(() => import('./pages/mobile/MobileMyIncentivesPage'))
const MobileGamificationPage = lazy(() => import('./pages/mobile/MobileGamificationPage'))
const MobileTasksPage = lazy(() => import('./pages/mobile/MobileTasksPage'))
const MobileTaskDetailPage = lazy(() => import('./pages/mobile/MobileTaskDetailPage'))
const MobileVoucherRedeemPage = lazy(() => import('./pages/mobile/MobileVoucherRedeemPage'))
const MobileStockCountPage = lazy(() => import('./pages/mobile/MobileStockCountPage'))
const MobileStockCountDetailPage = lazy(() => import('./pages/mobile/MobileStockCountDetailPage'))
const MobileDailyCountPage = lazy(() => import('./pages/mobile/MobileDailyCountPage'))
const MobileQAPage = lazy(() => import('./pages/mobile/MobileQAPage'))
const MobileQADetailPage = lazy(() => import('./pages/mobile/MobileQADetailPage'))
const MobileAttendancePage = lazy(() => import('./pages/mobile/MobileAttendancePage'))
const DeliveryTrackPage = lazy(() => import('./pages/DeliveryTrackPage'))
const CounselCardPublicPage = lazy(() => import('./pages/CounselCardPublicPage'))
const CounsellingPage = lazy(() => import('./pages/CounsellingPage'))
const PaymentTracking = lazy(() => import('./pages/PaymentTracking'))
const SalesDashboard = lazy(() => import('./pages/SalesDashboard'))
const PerformanceDashboard = lazy(() => import('./pages/PerformanceDashboard'))
const InventoryDashboard = lazy(() => import('./pages/InventoryDashboard'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const TaskDetailPage = lazy(() => import('./pages/TaskDetailPage'))
const TaskDashboardPage = lazy(() => import('./pages/TaskDashboardPage'))
const TaskSchedulesPage = lazy(() => import('./pages/TaskSchedulesPage'))
// Procurement — hub + sub-pages (sub-pages render as tabs inside ProcurementHubPage)
const ProcurementHubPage = lazy(() => import('./pages/ProcurementHubPage'))
const ProcurementDashboard = lazy(() => import('./pages/ProcurementDashboard'))
const SupplierPerformancePage = lazy(() => import('./pages/SupplierPerformancePage'))
const ProcurementMarginPage = lazy(() => import('./pages/ProcurementMarginPage'))
const ProcurementOptimizationPage = lazy(() => import('./pages/ProcurementOptimizationPage'))
const ProcurementHistoryPage = lazy(() => import('./pages/ProcurementHistoryPage'))
const SupplierSegmentationPage = lazy(() => import('./pages/SupplierSegmentationPage'))
const FocAnalysisPage = lazy(() => import('./pages/FocAnalysisPage'))
const SupplierCategoriesPage = lazy(() => import('./pages/SupplierCategoriesPage'))
// Analytics — hub renders Sales + Performance + Reservations + Transfers as tabs
const AnalyticsHubPage = lazy(() => import('./pages/AnalyticsHubPage'))
const ReservationsAnalyticsPage = lazy(() => import('./pages/ReservationsAnalyticsPage'))
const TransfersAnalyticsPage = lazy(() => import('./pages/TransfersAnalyticsPage'))
// Operations — previously missing routes
const CallCenterPage = lazy(() => import('./pages/CallCenterPage'))
const CasesPage = lazy(() => import('./pages/CasesPage'))
const CallbackQueuePage = lazy(() => import('./pages/CallbackQueuePage'))
const AuditPage = lazy(() => import('./pages/AuditPage'))
const FollowUpsPage = lazy(() => import('./pages/FollowUpsPage'))
const DemandPage = lazy(() => import('./pages/DemandPage'))
const DemandDashboardPage = lazy(() => import('./pages/DemandDashboardPage'))
const DemandRecoveryPage = lazy(() => import('./pages/DemandRecoveryPage'))
const DemandDetailPage = lazy(() => import('./pages/DemandDetailPage'))
// Finance Intelligence Platform
const FinanceHubPage = lazy(() => import('./pages/FinanceHubPage'))
const FinanceDashboardPage = lazy(() => import('./pages/FinanceDashboardPage'))
const GLAccountsPage = lazy(() => import('./pages/finance/gl/GLAccountsPage'))   // finance's own chart of accounts (GL)
const GLJournalPage = lazy(() => import('./pages/finance/gl/JournalPage'))
const GLTrialBalancePage = lazy(() => import('./pages/finance/gl/TrialBalancePage'))
const GLStatementsPage = lazy(() => import('./pages/finance/gl/StatementsPage'))
const GLAccountStatementPage = lazy(() => import('./pages/finance/gl/AccountStatementPage'))
const GLPartiesPage = lazy(() => import('./pages/finance/gl/GLPartiesPage'))
const PostingRulesPage = lazy(() => import('./pages/finance/gl/PostingRulesPage'))
const PeriodClosePage = lazy(() => import('./pages/finance/gl/PeriodClosePage'))
const GLSubledgersPage = lazy(() => import('./pages/finance/gl/SubledgersPage'))
const GLSoftechComparePage = lazy(() => import('./pages/finance/gl/SoftechComparePage'))
const ProfitLossPage = lazy(() => import('./pages/ProfitLossPage'))
const CashViewPage = lazy(() => import('./pages/CashViewPage'))   // P-40 — replaces the retired cash-flow page (P-43)
const ExpenseAnalyticsPage = lazy(() => import('./pages/ExpenseAnalyticsPage'))
const FinanceSchemaPage = lazy(() => import('./pages/FinanceSchemaPage'))
const ContractReceivablesPage = lazy(() => import('./pages/ContractReceivablesPage'))   // P-41
const SupplierTermsPage = lazy(() => import('./pages/SupplierTermsPage'))               // P-42
const ProductCatalogPage = lazy(() => import('./pages/ProductCatalogPage'))
const ProductDetailPage = lazy(() => import('./pages/ProductDetailPage'))
const ProductContentAdminPage = lazy(() => import('./pages/ProductContentAdminPage'))
const WhatsAppCampaignPage = lazy(() => import('./pages/WhatsAppCampaignPage'))
const WhatsAppInboxPage = lazy(() => import('./pages/WhatsAppInboxPage'))
const OmniInboxPage = lazy(() => import('./pages/OmniInboxPage'))
const OmniAccountsPage = lazy(() => import('./pages/OmniAccountsPage'))
const OmniWallboardPage = lazy(() => import('./pages/OmniWallboardPage'))
const OmniAutomationsPage = lazy(() => import('./pages/OmniAutomationsPage'))
const OmniAnalyticsPage = lazy(() => import('./pages/OmniAnalyticsPage'))
const LoyaltyPage = lazy(() => import('./pages/LoyaltyPage'))
const BranchPointsPage = lazy(() => import('./pages/BranchPointsPage'))
const ReferralPage = lazy(() => import('./pages/ReferralPage'))
const PbxLivePage = lazy(() => import('./pages/PbxLivePage'))
const ChequePlanningPage = lazy(() => import('./pages/ChequePlanningPage'))
const CatalogIntelligencePage = lazy(() => import('./pages/CatalogIntelligencePage'))
const CompositionPage = lazy(() => import('./pages/CompositionPage'))
const IngredientSearchPage = lazy(() => import('./pages/IngredientSearchPage'))
const ItemIntelPage = lazy(() => import('./pages/ItemIntelPage'))
const ImageEnrichmentPage = lazy(() => import('./pages/ImageEnrichmentPage'))
const RecommendationsPage = lazy(() => import('./pages/RecommendationsPage'))
const CallCenterAnalyticsPage = lazy(() => import('./pages/CallCenterAnalyticsPage'))
const PricingApprovalsPage = lazy(() => import('./pages/PricingApprovalsPage'))
const DiscountAlignmentPage = lazy(() => import('./pages/DiscountAlignmentPage'))
const SupplyPage = lazy(() => import('./pages/SupplyPage'))
const ReplacementCasesPage = lazy(() => import('./pages/ReplacementCasesPage'))
const ReplacementCaseDetailPage = lazy(() => import('./pages/ReplacementCaseDetailPage'))
const ReplacementNewCasePage = lazy(() => import('./pages/ReplacementNewCasePage'))
const ApprovalsPage = lazy(() => import('./pages/ApprovalsPage'))
const BatchesPage = lazy(() => import('./pages/BatchesPage'))
const HRPage = lazy(() => import('./pages/HRPage'))
const PaymentAuditPage = lazy(() => import('./pages/PaymentAuditPage'))
const ReconciliationPage = lazy(() => import('./pages/ReconciliationPage'))
const ForecastingPage = lazy(() => import('./pages/ForecastingPage'))
const SecurityPage = lazy(() => import('./pages/SecurityPage'))
// Customer self-service portal (external — magic-link auth, own shell, NOT staff)
const PortalLayout = lazy(() => import('./pages/portal/PortalLayout'))
const PortalLoginPage = lazy(() => import('./pages/portal/PortalLoginPage'))
const PortalAuthPage = lazy(() => import('./pages/portal/PortalAuthPage'))
const PortalHomePage = lazy(() => import('./pages/portal/PortalHomePage'))
const PortalLoyaltyPage = lazy(() => import('./pages/portal/PortalLoyaltyPage'))
const PortalRefillsPage = lazy(() => import('./pages/portal/PortalRefillsPage'))
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
})

// Bottom-tab navigation for the standalone mobile surfaces (/m). One tab per
// section; "new" is reached via each list's floating + button (not a tab).
// `roles` (when present) gates the tab; MobileLayout filters by the user's role. Reservations /
// transfers follow the matrix's view grant (Batch 4, Z-11i — delivery / purchasing saw tabs that
// loaded nothing); roles without reservations land on «لوحتي» (MobileReservationsPage redirects).
const MOBILE_TABS = [
  { to: '/m/me',           label: 'لوحتي',      icon: '🙋' },
  { to: '/m/pos',          label: 'نقطة البيع', icon: '🧾', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor'] },
  { to: '/m/reservations', label: 'الحجوزات',  icon: '📋', roles: MOBILE_RESERVATION_ROLES },
  { to: '/m/transfers',    label: 'التحويلات', icon: '🔀', roles: MOBILE_TRANSFER_ROLES },
  { to: '/m/demand',       label: 'الطلب الضائع', icon: '🔍', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/shortage',     label: 'النواقص',   icon: '🚨', roles: ['admin', 'pharmacist', 'call_center', 'salesperson', 'purchasing', 'supervisor', 'quality_manager'] },
  { to: '/m/delivery',     label: 'التوصيل',   icon: '🚚', roles: ['admin', 'call_center', 'supervisor', 'quality_manager', 'pharmacist'] },
  { to: '/m/approvals',    label: 'الموافقات', icon: '✔️', roles: ['admin', 'supervisor', 'purchasing'], badge: 'approvals' },
  { to: '/m/items',        label: 'الأصناف',   icon: '🔎' },
  { to: '/m/customers',    label: 'العملاء',   icon: '👥', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/vouchers',     label: 'القسائم',   icon: '🎫', roles: ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'] },
  { to: '/m/tasks',        label: 'المهام',    icon: '✅', module: 'tasks' },
  { to: '/m/daily-count',  label: 'جردي اليوم', icon: '🧮', feature: 'daily_count' },
  { to: '/m/stock-count',  label: 'الجرد',     icon: '📦', roles: ['admin', 'pharmacist', 'supervisor', 'quality_manager'] },
  { to: '/m/qa',           label: 'مراجعة الجودة', icon: '🧹', roles: ['admin', 'quality_manager', 'supervisor', 'pharmacist'] },
  { to: '/m/attendance',   label: 'الحضور',    icon: '🕐' },
  { to: '/m/my-incentives', label: 'حوافزي',   icon: '🏅' },
  { to: '/m/gamification',  label: 'التحفيز',  icon: '🏆' },
]

// A rider lives on /rider only (N3 H4): any other staff route sends the delivery role back there,
// except «أمان الحساب» (/security), which opens inside the rider shell at /rider/security so a rider
// can enrol two-factor (C1). The server (zone policy, access='rider') is the real guard.
function RiderHome({ children }) {
  const { user } = useAuthStore()
  const { pathname } = useLocation()
  if (user?.role === 'delivery') {
    return <Navigate to={pathname.replace(/\/+$/, '') === '/security' ? '/rider/security' : '/rider'} replace />
  }
  return children
}

export default function App() {
  const loadMe        = useAuthStore(s => s.loadMe)
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const initLang      = useLangStore(s => s.init)
  const loadPerms     = usePermissionStore(s => s.load)
  const resetPerms    = usePermissionStore(s => s.reset)

  useNumberInputGuards()  // app-wide: plain arrows/wheel inert, Shift+arrow/wheel steps

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
        {/* pages load on demand; routes outside a layout suspend here */}
        <PageSuspense>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/notify" element={<NotifyPage />} />
          {/* Public customer delivery tracking (tokenized, no login) */}
          <Route path="/track/:token" element={<DeliveryTrackPage />} />
          {/* Public customer counselling card (tokenized, no login) — Project 4 */}
          <Route path="/c/:token" element={<CounselCardPublicPage />} />

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
          <Route path="/rider" element={<RequireAuth><RequireRole roles={['delivery','admin','supervisor']}><RiderLayout><DriverDeliveryApp /></RiderLayout></RequireRole></RequireAuth>} />
          <Route path="/rider/security" element={<RequireAuth><RequireRole roles={['delivery','admin','supervisor']}><RiderLayout><SecurityPage /></RiderLayout></RequireRole></RequireAuth>} />

          {/* ── Standalone mobile web surfaces (no desktop sidebar) ─────────
              Phone-friendly, thin views over the existing APIs. Pilot: reservations.
              Reached at /m — bookmark on a phone home screen. */}
          <Route path="/m" element={<RequireAuth><RiderHome><MobileLayout title="صيدليات الرزيقي" tabs={MOBILE_TABS} /></RiderHome></RequireAuth>}>
            <Route index element={<Navigate to="/m/reservations" replace />} />
            <Route path="me"                element={<MyDashboardPage />} />
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
            <Route path="gamification"      element={<MobileGamificationPage />} />
            <Route path="tasks"             element={<MobileTasksPage />} />
            <Route path="tasks/:id"         element={<MobileTaskDetailPage />} />
            <Route path="vouchers"          element={<MobileVoucherRedeemPage />} />
            <Route path="stock-count"       element={<MobileStockCountPage />} />
            <Route path="stock-count/:id"   element={<MobileStockCountDetailPage />} />
            <Route path="daily-count"       element={<MobileDailyCountPage />} />
            <Route path="qa"                element={<MobileQAPage />} />
            <Route path="qa/:id"            element={<MobileQADetailPage />} />
            <Route path="attendance"        element={<MobileAttendancePage />} />
          </Route>

          {/* printable training manual — own shell so it prints without the side menu */}
          <Route path="/help/manual" element={<RequireAuth><HelpManualPage /></RequireAuth>} />
          <Route path="/" element={<RequireAuth><RiderHome><Layout /></RiderHome></RequireAuth>}>
            <Route index element={<Navigate to="/dashboard" replace />} />

            {/* ── Core ─────────────────────────────────────────────────── */}
            <Route path="dashboard"          element={<DashboardPage />} />
            <Route path="me"                 element={<MyDashboardPage />} />
            <Route path="help"               element={<HelpCenterPage />} />{/* in-app help guide — all roles */}
            <Route path="security"           element={<SecurityPage />} />{/* 2FA self-service — all roles */}
            <Route path="notifications"      element={<NotificationsInboxPage />} />
            <Route path="announcements"      element={<AnnouncementsPage />} />
            <Route path="targets"            element={<TargetsPage />} />
            <Route path="kpi-board"          element={<KpiBoardPage />} />
            <Route path="salesperson-board"  element={<SalespersonBoardPage />} />
            <Route path="forecast-scenarios" element={<ForecastScenarioPage />} />
            <Route path="insights"           element={<InsightsPage />} />
            <Route path="referral-stats"     element={<ReferralStatsPage />} />
            <Route path="vision-corpus"      element={<VisionCorpusPage />} />

            {/* ── Operations ───────────────────────────────────────────── */}
            <Route path="reservations"       element={<ReservationsKanban />} />
            <Route path="reservations/list"  element={<ReservationsPage />} />
            <Route path="reservations/new"   element={<NewReservationPage />} />
            <Route path="reservations/:id"   element={<ReservationDetailPage />} />
            <Route path="missed-sales"       element={<MissedSalesPage />} />
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
            <Route path="callcenter/callbacks"  element={<CallbackQueuePage />} />
            <Route path="callcenter/analytics"  element={<CallCenterAnalyticsPage />} />
            <Route path="followups"             element={<FollowUpsPage />} />
            <Route path="followups/reminders"   element={<RefillRemindersPage />} />

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
            <Route path="customers/merge"    element={<CustomerMergePage />} />
            <Route path="customers/pic-analytics" element={<PicAnalyticsPage />} />
            <Route path="customers/:id"      element={<CustomerDetailPage />} />
            <Route path="vouchers"           element={<VouchersPage />} />
            <Route path="offers"             element={<OffersPage />} />
            <Route path="chronic-classifier" element={<ChronicClassifierPage />} />
            <Route path="composition"        element={<CompositionPage />} />
            <Route path="ingredient-search"  element={<IngredientSearchPage />} />

            {/* ── Inventory ────────────────────────────────────────────── */}
            <Route path="products"           element={<ProductCatalogPage />} />
            <Route path="counselling"        element={<CounsellingPage />} />
            <Route path="products/:id"       element={<ProductDetailPage />} />
            <Route path="products/:id/admin" element={<ProductContentAdminPage />} />
            <Route path="products/:id/intel" element={<ItemIntelPage />} />
            <Route path="catalog-intelligence"  element={<CatalogIntelligencePage />} />
            <Route path="image-enrichment"      element={<ImageEnrichmentPage />} />
            <Route path="pricing-approvals"     element={<PricingApprovalsPage />} />
            <Route path="discount-alignment"    element={<DiscountAlignmentPage />} />
            <Route path="supply"                element={<SupplyPage />} />
            <Route path="replacement"           element={<RequireRole roles={['admin','supervisor','purchasing','quality_manager','pharmacist']}><ReplacementCasesPage /></RequireRole>} />
            <Route path="replacement/new"       element={<RequireRole roles={['admin','supervisor','pharmacist']}><ReplacementNewCasePage /></RequireRole>} />
            <Route path="replacement/:id"       element={<RequireRole roles={['admin','supervisor','purchasing','quality_manager','pharmacist']}><ReplacementCaseDetailPage /></RequireRole>} />
            <Route path="pos"                   element={<POSOrderPage />} />
            <Route path="usage-print"           element={<UsagePrintPage />} />
            <Route path="pos/exceptions"        element={<RequireRole roles={['admin','supervisor','pharmacist']}><ExceptionCenterPage /></RequireRole>} />
            <Route path="recommendations"       element={<RecommendationsPage />} />
            <Route path="inventory"          element={<InventoryDashboard />} />
            <Route path="stock-count"        element={<StockCountPage />} />
            <Route path="shortage"           element={<ShortagePage />} />
            <Route path="purchasing"         element={<PurchasingDashboard />} />
            <Route path="market-shortage"    element={<RequireRole roles={['admin','purchasing','pharmacist','supervisor','quality_manager']}><MarketShortagePage /></RequireRole>} />
            <Route path="phantom-sales"      element={<RequireRole roles={['admin','purchasing','pharmacist','supervisor','quality_manager']}><PhantomSalesPage /></RequireRole>} />
            <Route path="cash-optimization"  element={<RequireRole roles={['admin','purchasing','pharmacist','supervisor','quality_manager']}><CashOptimizationPage /></RequireRole>} />

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
              <Route path="categories"   element={<SupplierCategoriesPage />} />
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
            <Route path="gamification"  element={<GamificationPage />} />
            {/* stock-transactions audit (doc 32): management + named branch managers — gated server-side */}
            <Route path="stock-audit"   element={<StockAuditPage />} />

            {/* ── Insurance Claims Module ───────────────────────────────── */}
            <Route path="insurance"                           element={<InsuranceClaimsPage />} />
            <Route path="commerce"                            element={<CommerceDocumentsPage />} />
            <Route path="commerce/documents/:id"              element={<CommerceDocumentEditorPage />} />
            <Route path="insurance/clients"                   element={<InsuranceClientsPage />} />
            <Route path="insurance/item-overrides"            element={<InsuranceItemOverridesPage />} />
            <Route path="insurance/separation-lists"          element={<InsuranceSeparationListsPage />} />
            <Route path="insurance/rosters"                   element={<InsuranceRostersPage />} />
            <Route path="insurance/reports"                   element={<InsuranceReportsPage />} />
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
              <Route path="coa"       element={<GLAccountsPage />} />
              <Route path="journal"   element={<GLJournalPage />} />
              <Route path="trial-balance" element={<GLTrialBalancePage />} />
              <Route path="statements" element={<GLStatementsPage />} />
              <Route path="ledger"    element={<GLAccountStatementPage />} />
              <Route path="parties"   element={<GLPartiesPage />} />
              <Route path="rules"     element={<PostingRulesPage />} />
              <Route path="close"     element={<PeriodClosePage />} />
              <Route path="subledgers" element={<GLSubledgersPage />} />
              <Route path="softech-compare" element={<GLSoftechComparePage />} />
              <Route path="pnl"       element={<ProfitLossPage />} />
              {/* P-40: the 13-week cash view replaces the retired cash-flow page; the old URL redirects. */}
              <Route path="cash"      element={<CashViewPage />} />
              <Route path="cashflow"  element={<Navigate to="/finance/cash" replace />} />
              <Route path="expenses"  element={<ExpenseAnalyticsPage />} />
              <Route path="receivables" element={<ContractReceivablesPage />} />
              <Route path="supplier-terms" element={<SupplierTermsPage />} />
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
            {/* phone alerts (WhatsApp): admin + supervisor */}
            <Route path="phone-alerts"
              element={<RequireRole roles={['admin','supervisor']}><PhoneAlertsPage /></RequireRole>} />
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
            {/* trusted networks (security N1): admin only */}
            <Route path="access/networks"
              element={<RequireRole roles={['admin']}><TrustedNetworksPage /></RequireRole>} />
            <Route path="access/devices"
              element={<RequireRole roles={['admin']}><DevicesPage /></RequireRole>} />
            <Route path="access/zone-policy"
              element={<RequireRole roles={['admin']}><ZonePolicyPage /></RequireRole>} />
            {/* procurement: purchasing + admin */}
            <Route path="invoices"
              element={<RequireRole roles={['admin','purchasing']}><InvoicePage /></RequireRole>} />
            {/* incentives payroll: all-branch admin + quality_manager + purchasing only (owner 2026-11-03; server enforces) */}
            <Route path="incentives"
              element={<RequireRole roles={['admin','quality_manager','purchasing']}><IncentivesPage /></RequireRole>} />
            {/* cheques + finance: admin + purchasing + pharmacist */}
            <Route path="cheques"
              element={<RequireRole roles={['admin','purchasing','pharmacist','accountant']}><ChequePlanningPage /></RequireRole>} />

            {/* ── New Modules (Phases 1–5) ─────────────────────────────── */}
            {/* approvals inbox: roles that approve something (server still enforces per-step eligibility) */}
            <Route path="approvals"     element={<RequireRole roles={['admin','supervisor','pharmacist','quality_manager','purchasing']}><ApprovalsPage /></RequireRole>} />
            <Route path="batches"       element={<BatchesPage />} />
            <Route path="hr"            element={<HRPage />} />
            <Route path="payment-audit" element={<RequireRole roles={['admin','purchasing','pharmacist','quality_manager','accountant']}><PaymentAuditPage /></RequireRole>} />
            <Route path="reconciliation" element={<RequireRole roles={['admin','purchasing','quality_manager','accountant']}><ReconciliationPage /></RequireRole>} />
            <Route path="forecasting"   element={<RequireRole roles={['admin','purchasing','pharmacist','quality_manager']}><ForecastingPage /></RequireRole>} />

          </Route>
        </Routes>
        </PageSuspense>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
