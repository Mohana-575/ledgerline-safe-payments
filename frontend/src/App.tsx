import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
} from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { ProtectedRoute, RoleRoute } from './auth/RouteGuards'
import { AppLayout } from './layout/AppLayout'
import {
  AccountsPage,
  AdminPage,
  AuditLogsPage,
  DashboardPage,
  DepositPage,
  NotFoundPage,
  ProfilePage,
  StatementsPage,
  TransferPage,
  WithdrawPage,
} from './pages/AppPages'
import { LoginPage, RegisterPage } from './pages/AuthPages'
import type { UserRole } from './types/auth'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: false,
    },
  },
})

const transferRoles: UserRole[] = ['ACCOUNT_HOLDER', 'ADMIN']

function ProtectedLayout() {
  return (
    <ProtectedRoute>
      <AppLayout>
        <Outlet />
      </AppLayout>
    </ProtectedRoute>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/accounts" element={<AccountsPage />} />
              <Route element={<RoleRoute roles={transferRoles} />}>
                <Route path="/transfer" element={<TransferPage />} />
                <Route path="/deposit" element={<DepositPage />} />
                <Route path="/withdraw" element={<WithdrawPage />} />
              </Route>
              <Route path="/statements" element={<StatementsPage />} />
              <Route path="/audit-logs" element={<AuditLogsPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route element={<RoleRoute roles={['ADMIN']} />}>
                <Route path="/admin" element={<AdminPage />} />
              </Route>
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
