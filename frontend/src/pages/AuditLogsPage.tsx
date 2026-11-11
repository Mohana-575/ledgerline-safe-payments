import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import { apiRequest } from '../lib/api'
import { EmptyState, ErrorState, LoadingState } from '../components/States'

interface AuditLogEntry {
  id: number
  date_time: string
  action: string
  details: Record<string, string>
  ip: string | null
  initiated_by: { name: string; email: string } | null
}

interface AuditLogPage {
  items: AuditLogEntry[]
  next_cursor: string | null
}

interface AuditFilters {
  action: string
  from: string
  to: string
}

const actionOptions = [
  'ACCOUNT_CREATED',
  'DEPOSIT',
  'IDEMPOTENT_REPLAY',
  'LEDGER_VERIFICATION_RUN',
  'LOGIN_FAILED',
  'LOGIN_SUCCESS',
  'MEMBER_ASSIGNED',
  'RECONCILIATION_RUN',
  'REGISTER',
  'TRANSFER',
  'WITHDRAWAL',
]

function dateBound(value: string, endOfDay: boolean): string | undefined {
  if (!value) return undefined
  const date = new Date(`${value}T${endOfDay ? '23:59:59.999' : '00:00:00'}`)
  if (Number.isNaN(date.getTime())) {
    throw new Error('Choose a valid date range.')
  }
  return date.toISOString()
}

function actionLabel(action: string): string {
  return action
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

async function fetchAuditLogs(
  filters: AuditFilters,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<AuditLogPage> {
  const params = new URLSearchParams({ limit: '25' })
  if (filters.action) params.set('action', filters.action)
  const from = dateBound(filters.from, false)
  const to = dateBound(filters.to, true)
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  if (cursor) params.set('cursor', cursor)
  return apiRequest<AuditLogPage>(`/audit-logs?${params.toString()}`, { signal })
}

export function AuditLogsPage() {
  const [filters, setFilters] = useState<AuditFilters>({
    action: '',
    from: '',
    to: '',
  })
  const [appliedFilters, setAppliedFilters] = useState(filters)
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([null])
  const [pageIndex, setPageIndex] = useState(0)
  const [filterError, setFilterError] = useState<string | null>(null)
  const cursor = cursorStack[pageIndex] ?? null
  const auditQuery = useQuery({
    queryKey: [
      'audit-logs',
      appliedFilters.action,
      appliedFilters.from,
      appliedFilters.to,
      cursor,
    ],
    queryFn: ({ signal }) => fetchAuditLogs(appliedFilters, cursor, signal),
  })

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (filters.from && filters.to && filters.from > filters.to) {
      setFilterError('The From date must be on or before the To date.')
      return
    }
    setFilterError(null)
    setAppliedFilters(filters)
    setCursorStack([null])
    setPageIndex(0)
  }

  function goToNextPage() {
    const nextCursor = auditQuery.data?.next_cursor
    if (!nextCursor) return
    setCursorStack((current) => [...current.slice(0, pageIndex + 1), nextCursor])
    setPageIndex((current) => current + 1)
  }

  function goToPreviousPage() {
    if (pageIndex === 0) return
    setPageIndex((current) => current - 1)
  }

  return (
    <>
      <div className="mb-7">
        <p className="text-sm font-medium text-slate-500">
          LedgerLine / Audit Logs
        </p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
          Audit Logs
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Read-only history of account and system activity.
        </p>
      </div>

      <form
        onSubmit={handleSearch}
        className="mb-6 rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6"
      >
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(190px,1.3fr)_repeat(2,minmax(150px,1fr))_auto] xl:items-end">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Action
            <select
              value={filters.action}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  action: event.target.value,
                }))
              }
              className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              <option value="">All actions</option>
              {actionOptions.map((action) => (
                <option key={action} value={action}>
                  {actionLabel(action)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            From
            <input
              type="date"
              value={filters.from}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  from: event.target.value,
                }))
              }
              className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            To
            <input
              type="date"
              value={filters.to}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  to: event.target.value,
                }))
              }
              className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </label>
          <button
            type="submit"
            className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-5 text-sm font-semibold text-white transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <Search className="size-4" aria-hidden="true" />
            Search
          </button>
        </div>
        {filterError && (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {filterError}
          </p>
        )}
      </form>

      <section className="overflow-hidden rounded-xl border border-border bg-white shadow-sm">
        {auditQuery.isPending ? (
          <LoadingState label="Loading audit logs…" />
        ) : auditQuery.error ? (
          <ErrorState
            error={auditQuery.error}
            onRetry={() => void auditQuery.refetch()}
          />
        ) : auditQuery.data.items.length === 0 ? (
          <EmptyState
            title="No audit events found"
            description="Try changing the action or date range."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-border bg-slate-50/80 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-5 py-4">Date &amp; Time</th>
                    <th className="px-5 py-4">Action</th>
                    <th className="px-5 py-4">User</th>
                    <th className="px-5 py-4">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {auditQuery.data.items.map((entry) => (
                    <tr key={entry.id} className="align-top text-sm text-slate-700">
                      <td className="whitespace-nowrap px-5 py-4 text-slate-600">
                        {new Intl.DateTimeFormat(undefined, {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        }).format(new Date(entry.date_time))}
                      </td>
                      <td className="px-5 py-4">
                        <span className="inline-flex rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700">
                          {actionLabel(entry.action)}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        {entry.initiated_by ? (
                          <>
                            <p className="font-medium text-slate-800">
                              {entry.initiated_by.name}
                            </p>
                            <p className="mt-1 text-xs text-slate-500">
                              {entry.initiated_by.email}
                            </p>
                          </>
                        ) : (
                          <span className="text-slate-400">System</span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-[auto_1fr]">
                          {Object.entries(entry.details).map(([key, value]) => (
                            <div
                              key={key}
                              className="contents text-xs leading-5"
                            >
                              <dt className="font-medium text-slate-500">
                                {actionLabel(key)}
                              </dt>
                              <dd className="break-all text-slate-700">
                                {value}
                              </dd>
                            </div>
                          ))}
                          {entry.ip && (
                            <>
                              <dt className="text-xs font-medium leading-5 text-slate-500">
                                IP
                              </dt>
                              <dd className="break-all text-xs leading-5 text-slate-700">
                                {entry.ip}
                              </dd>
                            </>
                          )}
                        </dl>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-border px-5 py-4">
              <p className="text-sm text-slate-500">Page {pageIndex + 1}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={goToPreviousPage}
                  disabled={pageIndex === 0 || auditQuery.isFetching}
                  className="rounded-lg border border-border px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={goToNextPage}
                  disabled={!auditQuery.data.next_cursor || auditQuery.isFetching}
                  className="rounded-lg border border-border px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </>
  )
}
