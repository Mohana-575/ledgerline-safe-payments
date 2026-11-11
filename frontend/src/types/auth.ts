export type UserRole = 'ADMIN' | 'ACCOUNT_HOLDER' | 'AUDITOR'

export interface AuthUser {
  id: string
  full_name: string
  email: string
  role: UserRole
}
