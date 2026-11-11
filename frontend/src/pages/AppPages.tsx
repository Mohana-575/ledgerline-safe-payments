import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowUpFromLine,
  FileText,
  ShieldCheck,
  Wallet,
  WalletCards,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { MoneyForm } from '../components/MoneyForm'
import { fetchAccounts, type Account, type ApiAccount } from '../lib/accounts'
import { apiRequest } from '../lib/api'
import { formatPaise } from '../lib/money'
import type { UserRole } from '../types/auth'
export { AdminPage } from './AdminPage'
export { AuditLogsPage } from './AuditLogsPage'
export { ProfilePage } from './ProfilePage'
export { StatementsPage } from './StatementsPage'

interface ApiDashboardTransaction {
  transaction_id: string
  type: 'DEPOSIT' | 'WITHDRAWAL' | 'TRANSFER'
  date_time: string
  account_id: number
  direction: 'DEBIT' | 'CREDIT'
  amount_paise: number
  balance_after_paise: number
}

interface Dashboard {
  totalBalancePaise: bigint
  accountCount: number
  transactionsLast30Days: number
  role: UserRole
  accounts: Account[]
  recentTransactions: Array<
    Omit<ApiDashboardTransaction, 'amount_paise' | 'balance_after_paise'> & {
      amountPaise: bigint
      balanceAfterPaise: bigint
    }
  >
}

function toPaise(value: number, field: string): bigint {
  if (!Number.isSafeInteger(value)) {
    throw new Error(`The server returned an invalid ${field} amount.`)
  }
  return BigInt(value)
}

async function fetchDashboard(signal?: AbortSignal): Promise<Dashboard> {
  const response = await apiRequest<{
    total_balance_paise: number
    account_count: number
    transactions_last_30_days: number
    role: UserRole
    accounts: ApiAccount[]
    recent_transactions: ApiDashboardTransaction[]
  }>('/dashboard', { signal })

  return {
    totalBalancePaise: toPaise(response.total_balance_paise, 'total balance'),
    accountCount: response.account_count,
    transactionsLast30Days: response.transactions_last_30_days,
    role: response.role,
    accounts: response.accounts.map(({ balance_paise, ...account }) => ({
      ...account,
      balancePaise: toPaise(balance_paise, 'account balance'),
    })),
    recentTransactions: response.recent_transactions.map(
      ({ amount_paise, balance_after_paise, ...transaction }) => ({
        ...transaction,
        amountPaise: toPaise(amount_paise, 'transaction'),
        balanceAfterPaise: toPaise(balance_after_paise, 'transaction balance'),
      }),
    ),
  }
}

function PageIntro({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="mb-7">
      <p className="text-sm font-medium text-slate-500">LedgerLine / {title}</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
        {title}
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-500">{description}</p>
    </div>
  )
}

function WorkspacePage({
  title,
  description,
  emptyTitle,
  emptyDescription,
}: {
  title: string
  description: string
  emptyTitle: string
  emptyDescription: string
}) {
  return (
    <>
      <PageIntro title={title} description={description} />
      <EmptyState title={emptyTitle} description={emptyDescription} />
    </>
  )
}

function roleLabel(role: UserRole): string {
  return role
    .split('_')
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(' ')
}

function StatCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
}) {
  return (
    <article className="rounded-xl border border-border bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <span className="grid size-9 place-items-center rounded-lg bg-blue-50 text-primary">
          <Icon className="size-[18px]" aria-hidden="true" />
        </span>
      </div>
      <p className="mt-4 text-2xl font-semibold tracking-tight text-slate-900">
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </article>
  )
}

function AccountList({
  accounts,
  showActions = false,
  canMoveMoney = true,
}: {
  accounts: Account[]
  showActions?: boolean
  canMoveMoney?: boolean
}) {
  return (
    <div className="divide-y divide-border">
      {accounts.map((account) => (
        <article
          key={account.id}
          className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600">
              <WalletCards className="size-5" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">
                {account.name}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                {account.account_number}
              </p>
            </div>
          </div>
          <p className="text-sm font-semibold tabular-nums text-slate-900 sm:text-right">
            {formatPaise(account.balancePaise)}
          </p>
          {showActions && (
            <div className="flex flex-wrap gap-2 sm:justify-end">
              {canMoveMoney && (
                <>
                  <Link
                    to={`/deposit?accountId=${account.id}`}
                    className="rounded-lg bg-deposit px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-deposit/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deposit"
                  >
                    Deposit
                  </Link>
                  <Link
                    to={`/withdraw?accountId=${account.id}`}
                    className="rounded-lg bg-withdrawal px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-withdrawal/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-withdrawal"
                  >
                    Withdraw
                  </Link>
                  <Link
                    to={`/transfer?accountId=${account.id}`}
                    className="rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  >
                    Transfer
                  </Link>
                </>
              )}
              <Link
                to={`/statements?accountId=${account.id}`}
                className="rounded-lg bg-statement px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-statement/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-statement"
              >
                Statement
              </Link>
            </div>
          )}
        </article>
      ))}
    </div>
  )
}

interface QuickAction {
  label: string
  description: string
  to: string
  icon: LucideIcon
  color: string
}

const quickActions: QuickAction[] = [
  {
    label: 'Deposit',
    description: 'Add funds to an account',
    to: '/deposit',
    icon: ArrowDownToLine,
    color: 'bg-deposit',
  },
  {
    label: 'Withdraw',
    description: 'Withdraw from an account',
    to: '/withdraw',
    icon: ArrowUpFromLine,
    color: 'bg-withdrawal',
  },
  {
    label: 'Transfer',
    description: 'Move money between accounts',
    to: '/transfer',
    icon: ArrowLeftRight,
    color: 'bg-primary',
  },
  {
    label: 'Statement',
    description: 'Review account activity',
    to: '/statements',
    icon: FileText,
    color: 'bg-statement',
  },
]

function QuickActions({ role }: { role: UserRole }) {
  const actions =
    role === 'AUDITOR'
      ? quickActions.filter((action) => action.label === 'Statement')
      : quickActions

  return (
    <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
      <h2 className="text-base font-semibold text-slate-900">Quick Actions</h2>
      <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        {actions.map(({ label, description, to, icon: Icon, color }) => (
          <Link
            key={label}
            to={to}
            className="group flex min-h-32 flex-col items-start rounded-xl border border-border p-4 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <span
              className={`grid size-10 place-items-center rounded-lg text-white ${color}`}
            >
              <Icon className="size-5" aria-hidden="true" />
            </span>
            <span className="mt-3 text-sm font-semibold text-slate-900">
              {label}
            </span>
            <span className="mt-1 text-xs leading-5 text-slate-500">
              {description}
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

function transactionLabel(type: ApiDashboardTransaction['type']): string {
  return type === 'WITHDRAWAL' ? 'Withdraw' : type.charAt(0) + type.slice(1).toLowerCase()
}

function RecentTransactions({
  transactions,
  accounts,
}: {
  transactions: Dashboard['recentTransactions']
  accounts: Account[]
}) {
  const accountsById = new Map(accounts.map((account) => [account.id, account]))

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-white shadow-sm">
      <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4 sm:px-6">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Recent Transactions
          </h2>
          <p className="mt-1 text-xs text-slate-500">Your latest account activity</p>
        </div>
        <Link
          to="/statements"
          className="shrink-0 text-sm font-semibold text-primary hover:text-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          View all
        </Link>
      </div>
      {transactions.length === 0 ? (
        <div className="px-5 py-2 sm:px-6">
          <EmptyState
            title="No recent transactions"
            description="Transactions will appear here when there is activity on your accounts."
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-5 py-3 sm:px-6">
                  Date &amp; Time
                </th>
                <th scope="col" className="px-4 py-3">
                  Type
                </th>
                <th scope="col" className="px-4 py-3">
                  Account
                </th>
                <th scope="col" className="px-4 py-3 text-right">
                  Amount
                </th>
                <th scope="col" className="px-4 py-3 text-right">
                  Balance
                </th>
                <th scope="col" className="px-5 py-3 text-right sm:px-6">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border text-sm">
              {transactions.map((transaction) => {
                const account = accountsById.get(transaction.account_id)
                const isCredit = transaction.direction === 'CREDIT'
                const amount =
                  transaction.amountPaise < 0n
                    ? -transaction.amountPaise
                    : transaction.amountPaise

                return (
                  <tr key={transaction.transaction_id} className="text-slate-700">
                    <td className="whitespace-nowrap px-5 py-4 text-slate-600 sm:px-6">
                      {new Intl.DateTimeFormat('en-IN', {
                        dateStyle: 'medium',
                        timeStyle: 'short',
                      }).format(new Date(transaction.date_time))}
                    </td>
                    <td className="px-4 py-4">
                      <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                        {transactionLabel(transaction.type)}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <p className="font-medium text-slate-800">
                        {account?.name ?? `Account ${transaction.account_id}`}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {account?.account_number ?? 'Account'}
                      </p>
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-4 text-right font-semibold tabular-nums ${
                        isCredit ? 'text-emerald-700' : 'text-red-600'
                      }`}
                    >
                      {isCredit ? '+' : '-'}
                      {formatPaise(amount)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-4 text-right tabular-nums text-slate-700">
                      {formatPaise(transaction.balanceAfterPaise)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-right sm:px-6">
                      <span className="inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                        Completed
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function DashboardPage() {
  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: ({ signal }) => fetchDashboard(signal),
  })

  if (dashboardQuery.isPending) {
    return <LoadingState label="Loading your dashboard…" />
  }

  if (dashboardQuery.error) {
    return (
      <>
        <PageIntro
          title="Dashboard"
          description="Your account activity and balances at a glance."
        />
        <ErrorState
          error={dashboardQuery.error}
          onRetry={() => void dashboardQuery.refetch()}
        />
      </>
    )
  }

  const dashboard = dashboardQuery.data
  const accounts = dashboard.accounts

  return (
    <>
      <PageIntro
        title="Dashboard"
        description="Your account activity and balances at a glance."
      />

      <section
        aria-label="Account overview"
        className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        <StatCard
          label="Total Balance"
          value={formatPaise(dashboard.totalBalancePaise)}
          detail="Across your accounts"
          icon={Wallet}
        />
        <StatCard
          label="My Accounts"
          value={String(dashboard.accountCount)}
          detail="Accounts linked to you"
          icon={WalletCards}
        />
        <StatCard
          label="Recent Transactions"
          value={String(dashboard.transactionsLast30Days)}
          detail="In the last 30 days"
          icon={Activity}
        />
        <article className="rounded-xl border border-border bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-slate-500">My Role</p>
            <span className="grid size-9 place-items-center rounded-lg bg-violet-50 text-statement">
              <ShieldCheck className="size-[18px]" aria-hidden="true" />
            </span>
          </div>
          <p className="mt-4">
            <span className="inline-flex rounded-full bg-blue-50 px-3 py-1.5 text-sm font-semibold text-primary">
              {roleLabel(dashboard.role)}
            </span>
          </p>
          <p className="mt-2 text-xs text-slate-500">Your access level</p>
        </article>
      </section>

      <div className="mb-7 grid gap-7 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
          <div className="mb-5 flex items-center justify-between gap-4">
            <h2 className="text-base font-semibold text-slate-900">My Accounts</h2>
            <Link
              to="/accounts"
              className="text-sm font-semibold text-primary hover:text-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              View All
            </Link>
          </div>
          {accounts.length === 0 ? (
            <EmptyState
              title="No accounts yet."
              description="Ask an administrator."
            />
          ) : (
            <AccountList accounts={accounts.slice(0, 4)} />
          )}
        </section>
        <QuickActions role={dashboard.role} />
      </div>

      <RecentTransactions
        transactions={dashboard.recentTransactions}
        accounts={accounts}
      />
    </>
  )
}

export function AccountsPage() {
  const { user } = useAuth()
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: ({ signal }) => fetchAccounts(signal),
  })

  return (
    <>
      <PageIntro
        title="Accounts"
        description="View your account details and balances."
      />
      {accountsQuery.isPending ? (
        <LoadingState label="Loading accounts…" />
      ) : accountsQuery.error ? (
        <ErrorState
          error={accountsQuery.error}
          onRetry={() => void accountsQuery.refetch()}
        />
      ) : accountsQuery.data.length === 0 ? (
        <EmptyState
          title="No accounts yet."
          description="Ask an administrator."
        />
      ) : (
        <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
          <AccountList
            accounts={accountsQuery.data}
            showActions
            canMoveMoney={user?.role !== 'AUDITOR'}
          />
        </section>
      )}
    </>
  )
}

export function TransferPage() {
  return <MoneyForm kind="TRANSFER" />
}

export function DepositPage() {
  return <MoneyForm kind="DEPOSIT" />
}

export function WithdrawPage() {
  return <MoneyForm kind="WITHDRAWAL" />
}

export function NotFoundPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-surface px-5">
      <div className="text-center">
        <p className="text-sm font-semibold uppercase tracking-widest text-primary">
          404
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
          Page not found
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          The page you are looking for does not exist.
        </p>
      </div>
    </main>
  )
}
