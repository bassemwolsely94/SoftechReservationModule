import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import useAuthStore from './store/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import ReservationsKanban from './pages/ReservationsKanban'
import NewReservationPage from './pages/NewReservationPage'
import ReservationDetailPage from './pages/ReservationDetailPage'
import CustomersPage from './pages/CustomersPage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import SyncPage from './pages/SyncPage'
import TransfersPage from './pages/TransfersPage'
import TransferDetailPage from './pages/TransferDetailPage'
import PurchasingPage from './pages/PurchasingPage'
import ChronicClassifierPage from './pages/ChronicClassifierPage'
import SettingsPage from './pages/SettingsPage'
import StockCountPage from './pages/StockCountPage'
import ShortagePage from './pages/ShortagePage'
import VouchersPage from './pages/VouchersPage'
import InvoicePage from './pages/InvoicePage'
import IncentivesPage from './pages/IncentivesPage'
import UserManagementPage from './pages/UserManagementPage'
import PermissionsMatrixPage from './pages/PermissionsMatrixPage'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
})

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

export default function App() {
  const loadMe = useAuthStore(s => s.loadMe)
  useEffect(() => { loadMe() }, [loadMe])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard"          element={<DashboardPage />} />
            <Route path="reservations"       element={<ReservationsKanban />} />
            <Route path="reservations/new"   element={<NewReservationPage />} />
            <Route path="reservations/:id"   element={<ReservationDetailPage />} />
            <Route path="transfers"          element={<TransfersPage />} />
            <Route path="transfers/:id"      element={<TransferDetailPage />} />
            <Route path="purchasing"         element={<PurchasingPage />} />
            <Route path="customers"          element={<CustomersPage />} />
            <Route path="customers/:id"      element={<CustomerDetailPage />} />
            <Route path="chronic-classifier" element={<ChronicClassifierPage />} />
            <Route path="sync"               element={<SyncPage />} />
            <Route path="settings"           element={<SettingsPage />} />
            <Route path="stock-count"        element={<StockCountPage />} />
            <Route path="shortage"           element={<ShortagePage />} />
            <Route path="vouchers"           element={<VouchersPage />} />
            <Route path="invoices"           element={<InvoicePage />} />
            <Route path="incentives"         element={<IncentivesPage />} />
            <Route path="users"              element={<UserManagementPage />} />
            <Route path="permissions"        element={<PermissionsMatrixPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
