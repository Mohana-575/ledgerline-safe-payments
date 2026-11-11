import { useState, type ReactNode } from 'react'
import {
  Activity,
  ArrowLeftRight,
  Bell,
  CreditCard,
  LayoutDashboard,
  LogOut,
  Shield,
  UserRound,
  WalletCards,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { authQueryKey } from '../auth/authContext'
import { useAuth } from '../auth/useAuth'
import { apiRequest } from '../lib/api'
import type { UserRole } from '../types/auth'

interface NavigationItem {
  label: string
  to: string
  icon: typeof LayoutDashboard
  roles?: readonly UserRole[]
}

const navigationItems: NavigationItem[] = [
  { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard },
  { label: 'Accounts', to: '/accounts', icon: WalletCards },
  {
    label: 'Transfer',
    to: '/transfer',
    icon: ArrowLeftRight,
    roles: ['ACCOUNT_HOLDER', 'ADMIN'],
  },
  { label: 'Statements', to: '/statements', icon: CreditCard },
  { label: 'Audit Logs', to: '/audit-logs', icon: Activity },
]

const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/accounts': 'Accounts',
  '/transfer': 'Transfer',
  '/deposit': 'Deposit',
  '/withdraw': 'Withdraw',
  '/statements': 'Statements',
  '/audit-logs': 'Audit Logs',
  '/profile': 'Profile',
  '/admin': 'Admin',
}

function roleLabel(role: UserRole): string {
  return role
    .split('_')
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(' ')
}

export function AppLayout({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [logoutError, setLogoutError] = useState<string | null>(null)

  if (!user) return null

  const items = navigationItems.filter(
    (item) => !item.roles || item.roles.includes(user.role),
  )
  if (user.role === 'ADMIN') {
    items.push({
      label: 'Admin',
      to: '/admin',
      icon: Shield,
    })
  }

  async function handleLogout() {
    setLogoutError(null)
    try {
      await apiRequest<void>('/auth/logout', { method: 'POST' })
      await queryClient.cancelQueries({ queryKey: authQueryKey })
      queryClient.setQueryData(authQueryKey, null)
      await navigate('/login', { replace: true })
    } catch (error) {
      setLogoutError(
        error instanceof Error ? error.message : 'Unable to log out. Please try again.',
      )
    }
  }

  const pageTitle = pageTitles[location.pathname] ?? 'LedgerLine'

  return (
    <div className="min-h-screen bg-surface lg:flex">
      <aside className="flex min-h-0 w-full flex-col bg-sidebar px-4 py-5 text-sidebar-foreground lg:sticky lg:top-0 lg:min-h-screen lg:h-screen lg:w-64 lg:shrink-0">
        <NavLink
          to="/dashboard"
          className="mb-9 flex items-center gap-3 px-3"
          aria-label="LedgerLine dashboard"
        >
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-white">
            <WalletCards className="size-5" aria-hidden="true" />
          </span>
          <span className="text-lg font-semibold tracking-tight">LedgerLine</span>
        </NavLink>

        <nav
          aria-label="Main navigation"
          className="flex flex-row flex-wrap gap-1 lg:flex-col"
        >
          {items.map(({ label, to, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-white/12 text-white'
                    : 'text-sidebar-muted hover:bg-white/8 hover:text-white'
                }`
              }
            >
              <Icon className="size-[18px]" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-5 border-t border-white/10 pt-4 lg:mt-auto">
          <NavLink
            to="/profile"
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-white/12 text-white'
                  : 'text-sidebar-muted hover:bg-white/8 hover:text-white'
              }`
            }
          >
            <UserRound className="size-[18px]" aria-hidden="true" />
            Profile
          </NavLink>
          <button
            type="button"
            onClick={handleLogout}
            className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-sidebar-muted transition-colors hover:bg-white/8 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            <LogOut className="size-[18px]" aria-hidden="true" />
            Logout
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex h-[72px] items-center justify-between border-b border-border bg-white px-5 sm:px-8">
          <h1 className="text-lg font-semibold text-slate-900">{pageTitle}</h1>
          <div className="flex items-center gap-3 sm:gap-5">
            <button
              type="button"
              aria-label="Notifications"
              className="relative grid size-10 place-items-center rounded-full text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-primary"
            >
              <Bell className="size-5" aria-hidden="true" />
              <span className="absolute right-2 top-2 size-2 rounded-full bg-primary" />
            </button>
            <div className="flex items-center gap-2.5 border-l border-border pl-3 sm:pl-5">
              <span className="grid size-9 place-items-center rounded-full bg-blue-50 text-sm font-semibold text-primary">
                {user.full_name.trim().charAt(0).toUpperCase()}
              </span>
              <span className="hidden text-sm font-medium text-slate-700 sm:inline">
                {roleLabel(user.role)}
              </span>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] px-5 py-7 sm:px-8 sm:py-9">
          {logoutError && (
            <p className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
              {logoutError}
            </p>
          )}
          {children}
        </main>
      </div>
    </div>
  )
}
