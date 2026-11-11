import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiRequest } from '../lib/api'
import type { AuthUser } from '../types/auth'
import { AuthContext, authQueryKey } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const authQuery = useQuery<AuthUser | null, Error>({
    queryKey: authQueryKey,
    queryFn: async ({ signal }) => {
      try {
        return await apiRequest<AuthUser>('/auth/me', { signal })
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    staleTime: 60_000,
  })

  const value = {
    user: authQuery.data ?? null,
    isLoading: authQuery.isPending,
    error: authQuery.error,
    refresh: async () => {
      await queryClient.invalidateQueries({ queryKey: authQueryKey })
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
