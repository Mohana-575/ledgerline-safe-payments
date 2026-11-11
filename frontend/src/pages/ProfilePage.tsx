import { Mail, ShieldCheck, UserRound } from 'lucide-react'
import { useAuth } from '../auth/useAuth'
import { ErrorState, LoadingState } from '../components/States'
import type { UserRole } from '../types/auth'

function roleLabel(role: UserRole): string {
  return role
    .split('_')
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(' ')
}

export function ProfilePage() {
  const { user, isLoading, error } = useAuth()

  if (isLoading) return <LoadingState label="Loading profile…" />
  if (error) return <ErrorState error={error} />
  if (!user) return <ErrorState error="Your profile is unavailable." />

  return (
    <>
      <div className="mb-7">
        <p className="text-sm font-medium text-slate-500">LedgerLine / Profile</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
          Profile
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Your account identity and access role.
        </p>
      </div>

      <section className="max-w-2xl rounded-xl border border-border bg-white p-5 shadow-sm sm:p-7">
        <div className="flex items-center gap-4 border-b border-border pb-6">
          <span className="grid size-14 place-items-center rounded-2xl bg-blue-50 text-primary">
            <UserRound className="size-7" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-lg font-semibold text-slate-900">
              {user.full_name}
            </h3>
            <p className="mt-1 text-sm text-slate-500">{user.email}</p>
          </div>
        </div>

        <dl className="divide-y divide-border">
          <div className="flex items-center gap-4 py-5">
            <Mail className="size-5 shrink-0 text-slate-400" aria-hidden="true" />
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Email
              </dt>
              <dd className="mt-1 text-sm font-medium text-slate-900">
                {user.email}
              </dd>
            </div>
          </div>
          <div className="flex items-center gap-4 py-5">
            <ShieldCheck
              className="size-5 shrink-0 text-slate-400"
              aria-hidden="true"
            />
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Role
              </dt>
              <dd className="mt-1">
                <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-sm font-medium text-slate-700">
                  {roleLabel(user.role)}
                </span>
              </dd>
            </div>
          </div>
        </dl>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Profile details are read-only. Contact an administrator if your access
          role needs to be reviewed.
        </p>
      </section>
    </>
  )
}
