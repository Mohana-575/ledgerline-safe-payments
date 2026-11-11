import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from './useAuth'
import { ErrorState, LoadingState } from '../components/States'
import type { UserRole } from '../types/auth'

export function ProtectedRoute({ children }: { children?: ReactNode }) {
  const { user, isLoading, error } = useAuth()
  const location = useLocation()

  if (isLoading) return <LoadingState label="Checking your session…" />
  if (error) return <ErrorState error={error} />
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children ?? <Outlet />
}

export function RoleRoute({ roles }: { roles: readonly UserRole[] }) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />
  }
  return <Outlet />
}
