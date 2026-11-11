import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Search } from 'lucide-react'
import { useSearchParams } from 'react-router'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { fetchAccounts } from '../lib/accounts'
import { apiRequest } from '../lib/api'
import { formatPaise } from '../lib/money'

type StatementType =
  | 'DEPOSIT'
  | 'WITHDRAWAL'
  | 'TRANSFER_IN'
  | 'TRANSFER_OUT'
  | 'REFUSED'

type StatementFilter = 'ALL' | StatementType

interface ApiStatementEntry {
  date_time: string
  type: StatementType
  amount_paise: number | null
  running_balance_paise: number
  status: 'COMPLETED' | 'REFUSED'
  reason_code: string | null
  initiated_by: { name: string; email: string } | null
}

interface StatementEntry
  extends Omit<
    ApiStatementEntry,
    'amount_paise' | 'running_balance_paise'
  > {
  amount_paise: bigint | null
  running_balance_paise: bigint
}

interface StatementPage {
  items: StatementEntry[]
  next_cursor: string | null
}

interface ApiStatementPage {
  items: ApiStatementEntry[]
  next_cursor: string | null
}

interface StatementFilters {
  type: StatementFilter
  from: string
  to: string
}

const typeLabels: Record<StatementFilter, string> = {
  ALL: 'All',
  DEPOSIT: 'Deposit',
  WITHDRAWAL: 'Withdrawal',
  TRANSFER_IN: 'Transfer In',
  TRANSFER_OUT: 'Transfer Out',
  REFUSED: 'Refused',
}

const typeOptions: Array<{ value: StatementFilter; label: string }> = [
  { value: 'ALL', label: 'All' },
  { value: 'DEPOSIT', label: 'Deposit' },
  { value: 'WITHDRAWAL', label: 'Withdrawal' },
  { value: 'TRANSFER_IN', label: 'Transfer In' },
  { value: 'TRANSFER_OUT', label: 'Transfer Out' },
  { value: 'REFUSED', label: 'Refused' },
]

function toPaise(value: number, field: string): bigint {
  if (!Number.isSafeInteger(value)) {
    throw new Error(`The server returned an invalid ${field} amount.`)
  }
  return BigInt(value)
}

function dateBound(value: string, endOfDay: boolean): string | undefined {
  if (!value) return undefined
  const date = new Date(`${value}T${endOfDay ? '23:59:59.999' : '00:00:00'}`)
  if (Number.isNaN(date.getTime())) {
    throw new Error('Choose a valid date range.')
  }
  return date.toISOString()
}

async function fetchStatement(
  accountId: string,
  filters: StatementFilters,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<StatementPage> {
  const params = new URLSearchParams({ type: filters.type, limit: '25' })
  const from = dateBound(filters.from, false)
  const to = dateBound(filters.to, true)
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  if (cursor) params.set('cursor', cursor)

  const response = await apiRequest<ApiStatementPage>(
    `/accounts/${accountId}/statement?${params.toString()}`,
    { signal },
  )

  return {
    ...response,
    items: response.items.map((entry) => ({
      ...entry,
      amount_paise:
        entry.amount_paise === null
          ? null
          : toPaise(entry.amount_paise, 'transaction'),
      running_balance_paise: toPaise(
        entry.running_balance_paise,
        'running balance',
      ),
    })),
  }
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function displayReason(reason: string): string {
  return reason
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function PageIntro() {
  return (
    <div className="mb-7">
      <p className="text-sm font-medium text-slate-500">LedgerLine / Statements</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
        Statements
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-500">
        Review account transactions, balances, and refused activity.
      </p>
    </div>
  )
}

export function StatementsPage() {
  const [searchParams] = useSearchParams()
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: ({ signal }) => fetchAccounts(signal),
  })
  const [selectedAccountId, setSelectedAccountId] = useState(
    () => searchParams.get('accountId') ?? '',
  )
  const [appliedAccountId, setAppliedAccountId] = useState(
    () => searchParams.get('accountId') ?? '',
  )
  const [filters, setFilters] = useState<StatementFilters>({
    type: 'ALL',
    from: '',
    to: '',
  })
  const [appliedFilters, setAppliedFilters] = useState<StatementFilters>(filters)
  const [cursorStack, setCursorStack] = useState<Array<string | null>>([null])
  const [pageIndex, setPageIndex] = useState(0)
  const [filterError, setFilterError] = useState<string | null>(null)

  const accountOptions = accountsQuery.data ?? []
  const firstAccountId = accountOptions[0] ? String(accountOptions[0].id) : ''
  const visibleSelectedAccountId = accountOptions.some(
    (account) => String(account.id) === selectedAccountId,
  )
    ? selectedAccountId
    : firstAccountId
  const visibleAppliedAccountId = accountOptions.some(
    (account) => String(account.id) === appliedAccountId,
  )
    ? appliedAccountId
    : firstAccountId

  const cursor = cursorStack[pageIndex] ?? null
  const statementQuery = useQuery({
    queryKey: [
      'statement',
      visibleAppliedAccountId,
      appliedFilters.type,
      appliedFilters.from,
      appliedFilters.to,
      cursor,
    ],
    queryFn: ({ signal }) =>
      fetchStatement(visibleAppliedAccountId, appliedFilters, cursor, signal),
    enabled: visibleAppliedAccountId !== '' && !accountsQuery.isPending,
  })

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (filters.from && filters.to && filters.from > filters.to) {
      setFilterError('The From date must be on or before the To date.')
      return
    }
    setFilterError(null)
    setAppliedAccountId(visibleSelectedAccountId)
    setAppliedFilters(filters)
    setCursorStack([null])
    setPageIndex(0)
  }

  function goToNextPage() {
    const nextCursor = statementQuery.data?.next_cursor
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
      <PageIntro />
      {accountsQuery.isPending ? (
        <LoadingState label="Loading accounts…" />
      ) : accountsQuery.error ? (
        <ErrorState
          error={accountsQuery.error}
          onRetry={() => void accountsQuery.refetch()}
        />
      ) : accountsQuery.data.length === 0 ? (
        <EmptyState
          title="No accounts available"
          description="There are no accounts available for your user."
        />
      ) : (
        <>
          <form
            onSubmit={handleSearch}
            className="mb-6 rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6"
          >
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[minmax(190px,1.3fr)_repeat(3,minmax(140px,1fr))_auto] xl:items-end">
              <label className="grid gap-2 text-sm font-medium text-slate-700">
                Account
                <select
                  value={visibleSelectedAccountId}
                  onChange={(event) => setSelectedAccountId(event.target.value)}
                  className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                >
                  {accountsQuery.data.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name} · {account.account_number}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium text-slate-700">
                Type
                <select
                  value={filters.type}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      type: event.target.value as StatementFilter,
                    }))
                  }
                  className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                >
                  {typeOptions.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
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
            {statementQuery.isPending ? (
              <LoadingState label="Loading statement…" />
            ) : statementQuery.error ? (
              <ErrorState
                error={statementQuery.error}
                onRetry={() => void statementQuery.refetch()}
              />
            ) : statementQuery.data.items.length === 0 ? (
              <EmptyState
                title="No transactions found"
                description="Try changing the account, type, or date range."
              />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[980px] border-collapse text-left">
                    <thead>
                      <tr className="border-b border-border bg-slate-50/80 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <th className="px-5 py-4">Date &amp; Time</th>
                        <th className="px-5 py-4">Type</th>
                        <th className="px-5 py-4 text-right">Amount</th>
                        <th className="px-5 py-4 text-right">Running Balance</th>
                        <th className="px-5 py-4">Status</th>
                        <th className="px-5 py-4">Initiated By</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {statementQuery.data.items.map((entry, index) => {
                        const amount =
                          entry.amount_paise
                        const isCredit = amount !== null && amount >= 0n
                        return (
                          <tr
                            key={`${entry.date_time}-${entry.type}-${index}`}
                            className="align-top text-sm text-slate-700"
                          >
                            <td className="whitespace-nowrap px-5 py-4 text-slate-600">
                              {formatDateTime(entry.date_time)}
                            </td>
                            <td className="px-5 py-4">
                              <span className="inline-flex rounded-full bg-violet-50 px-2.5 py-1 text-xs font-semibold text-violet-700">
                                {typeLabels[entry.type]}
                              </span>
                            </td>
                            <td
                              className={`whitespace-nowrap px-5 py-4 text-right font-semibold tabular-nums ${
                                amount === null
                                  ? 'text-slate-500'
                                  : isCredit
                                    ? 'text-emerald-700'
                                    : 'text-red-700'
                              }`}
                            >
                              {amount === null
                                ? '—'
                                : `${isCredit ? '+' : '-'}${formatPaise(
                                    amount < 0n ? -amount : amount,
                                  )}`}
                            </td>
                            <td className="whitespace-nowrap px-5 py-4 text-right font-medium tabular-nums text-slate-900">
                              {formatPaise(entry.running_balance_paise)}
                            </td>
                            <td className="px-5 py-4">
                              <span
                                className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                                  entry.status === 'REFUSED'
                                    ? 'bg-red-50 text-red-700'
                                    : 'bg-emerald-50 text-emerald-700'
                                }`}
                              >
                                {entry.status === 'REFUSED'
                                  ? 'Refused'
                                  : 'Completed'}
                              </span>
                              {entry.status === 'REFUSED' && (
                                <p className="mt-1.5 max-w-48 text-xs leading-5 text-red-700">
                                  Reason:{' '}
                                  {entry.reason_code
                                    ? displayReason(entry.reason_code)
                                    : 'Not provided'}
                                </p>
                              )}
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
                                <span className="text-slate-400">—</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="flex items-center justify-between border-t border-border px-5 py-4">
                  <p className="text-sm text-slate-500">
                    Page {pageIndex + 1}
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={goToPreviousPage}
                      disabled={pageIndex === 0 || statementQuery.isFetching}
                      className="rounded-lg border border-border px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={goToNextPage}
                      disabled={
                        !statementQuery.data.next_cursor ||
                        statementQuery.isFetching
                      }
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
      )}
    </>
  )
}
