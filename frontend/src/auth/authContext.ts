import { createContext } from 'react'
import type { AuthUser } from '../types/auth'

export const authQueryKey = ['auth', 'me'] as const

export interface AuthContextValue {
  user: AuthUser | null
  isLoading: boolean
  error: Error | null
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
