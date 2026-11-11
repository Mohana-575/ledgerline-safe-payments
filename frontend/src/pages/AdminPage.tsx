import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { CheckCircle2, CircleAlert, Play, ShieldCheck } from 'lucide-react'
import { ErrorState, LoadingState } from '../components/States'
import { fetchAccounts, type Account } from '../lib/accounts'
import { apiRequest } from '../lib/api'
import { formatPaise, parseRupeesToPaise } from '../lib/money'
import type { UserRole } from '../types/auth'

interface AdminUser {
  id: string
  full_name: string
  email: string
  role: UserRole
}

interface ApiAccountMismatch {
  account_id: number
  account_number: string
  balance_paise: number
  ledger_balance_paise: number
}

interface ApiNegativeAccount {
  account_id: number
  account_number: string
  balance_paise: number
}

interface ApiTransactionMismatch {
  transaction_id: string
  debits_paise: number
  credits_paise: number
}

interface ApiReconciliation {
  passed: boolean
  account_balance_sum_paise: number
  accounts_sum_to_zero: boolean
  accounts_match_ledger: boolean
  account_mismatches: ApiAccountMismatch[]
  non_system_accounts_nonnegative: boolean
  negative_accounts: ApiNegativeAccount[]
  transactions_balanced: boolean
  transaction_mismatches: ApiTransactionMismatch[]
}

interface Reconciliation extends Omit<
  ApiReconciliation,
  | 'account_balance_sum_paise'
  | 'account_mismatches'
  | 'negative_accounts'
  | 'transaction_mismatches'
> {
  account_balance_sum_paise: bigint
  account_mismatches: Array<
    Omit<ApiAccountMismatch, 'balance_paise' | 'ledger_balance_paise'> & {
      balance_paise: bigint
      ledger_balance_paise: bigint
    }
  >
  negative_accounts: Array<
    Omit<ApiNegativeAccount, 'balance_paise'> & { balance_paise: bigint }
  >
  transaction_mismatches: Array<
    Omit<ApiTransactionMismatch, 'debits_paise' | 'credits_paise'> & {
      debits_paise: bigint
      credits_paise: bigint
    }
  >
}

interface LedgerVerification {
  passed: boolean
  accounts_checked: number
  accounts: Array<{
    account_id: number
    passed: boolean
    first_broken_entry_id: number | null
  }>
}

type AccountType = 'PERSONAL' | 'SAVINGS' | 'BUSINESS'

function toPaise(value: number, field: string): bigint {
  if (!Number.isSafeInteger(value)) {
    throw new Error(`The server returned an invalid ${field} amount.`)
  }
  return BigInt(value)
}

async function runReconciliation(signal?: AbortSignal): Promise<Reconciliation> {
  const response = await apiRequest<ApiReconciliation>('/admin/reconcile', {
    signal,
  })
  return {
    ...response,
    account_balance_sum_paise: toPaise(
      response.account_balance_sum_paise,
      'account balance sum',
    ),
    account_mismatches: response.account_mismatches.map((mismatch) => ({
      ...mismatch,
      balance_paise: toPaise(mismatch.balance_paise, 'account balance'),
      ledger_balance_paise: toPaise(
        mismatch.ledger_balance_paise,
        'ledger balance',
      ),
    })),
    negative_accounts: response.negative_accounts.map((account) => ({
      ...account,
      balance_paise: toPaise(account.balance_paise, 'negative account balance'),
    })),
    transaction_mismatches: response.transaction_mismatches.map(
      (mismatch) => ({
        ...mismatch,
        debits_paise: toPaise(mismatch.debits_paise, 'transaction debits'),
        credits_paise: toPaise(mismatch.credits_paise, 'transaction credits'),
      }),
    ),
  }
}

function roleLabel(role: UserRole): string {
  return role
    .split('_')
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(' ')
}

function ResultBanner({ passed }: { passed: boolean }) {
  const Icon = passed ? CheckCircle2 : CircleAlert
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border px-4 py-3 ${
        passed
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
          : 'border-red-200 bg-red-50 text-red-800'
      }`}
      role="status"
    >
      <Icon className="size-5 shrink-0" aria-hidden="true" />
      <p className="text-sm font-semibold">
        {passed ? 'Passed' : 'Failed'} —{' '}
        {passed ? 'no issues found' : 'review the details below'}
      </p>
    </div>
  )
}

function AdminPageIntro() {
  return (
    <div className="mb-7">
      <p className="text-sm font-medium text-slate-500">LedgerLine / Admin</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
        Admin
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-500">
        Manage accounts and review ledger integrity checks.
      </p>
    </div>
  )
}

function IntegrityChecks() {
  const reconciliation = useMutation({
    mutationFn: () => runReconciliation(),
  })
  const verification = useMutation({
    mutationFn: ({ signal }: { signal?: AbortSignal } = {}) =>
      apiRequest<LedgerVerification>('/admin/verify-ledger', { signal }),
  })

  return (
    <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-5">
        <h3 className="text-base font-semibold text-slate-900">
          Reconciliation &amp; ledger verification
        </h3>
        <p className="mt-1 text-sm leading-5 text-slate-500">
          Check account balances against ledger entries and verify each ledger
          hash chain.
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => reconciliation.mutate()}
          disabled={reconciliation.isPending}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:cursor-wait disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          <Play className="size-4" aria-hidden="true" />
          {reconciliation.isPending ? 'Reconciling…' : 'Run Reconcile'}
        </button>
        <button
          type="button"
          onClick={() => verification.mutate({})}
          disabled={verification.isPending}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          <ShieldCheck className="size-4" aria-hidden="true" />
          {verification.isPending ? 'Verifying…' : 'Verify Ledger'}
        </button>
      </div>

      {reconciliation.error && (
        <div className="mt-5">
          <ErrorState error={reconciliation.error} />
        </div>
      )}
      {reconciliation.data && (
        <div className="mt-6 border-t border-border pt-5">
          <ResultBanner passed={reconciliation.data.passed} />
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ['Account balances sum to zero', reconciliation.data.accounts_sum_to_zero],
              ['Balances match ledger', reconciliation.data.accounts_match_ledger],
              [
                'Non-system balances are nonnegative',
                reconciliation.data.non_system_accounts_nonnegative,
              ],
              ['Transactions are balanced', reconciliation.data.transactions_balanced],
            ].map(([label, passed]) => (
              <div
                key={String(label)}
                className="rounded-lg border border-border bg-slate-50 px-3 py-3"
              >
                <dt className="text-xs leading-5 text-slate-600">
                  {String(label)}
                </dt>
                <dd
                  className={`mt-1 text-sm font-semibold ${
                    passed ? 'text-emerald-700' : 'text-red-700'
                  }`}
                >
                  {passed ? 'Pass' : 'Fail'}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-4 text-sm text-slate-600">
            Total account balance: <strong className="text-slate-900">{formatPaise(reconciliation.data.account_balance_sum_paise)}</strong>
          </p>
          {(reconciliation.data.account_mismatches.length > 0 ||
            reconciliation.data.negative_accounts.length > 0 ||
            reconciliation.data.transaction_mismatches.length > 0) && (
            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              {reconciliation.data.account_mismatches.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50/60 p-4">
                  <h4 className="text-sm font-semibold text-red-900">
                    Account balance mismatches
                  </h4>
                  <ul className="mt-2 space-y-2 text-xs leading-5 text-red-800">
                    {reconciliation.data.account_mismatches.map((item) => (
                      <li key={item.account_id}>
                        {item.account_number}: account{' '}
                        {formatPaise(item.balance_paise)}; ledger{' '}
                        {formatPaise(item.ledger_balance_paise)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {reconciliation.data.negative_accounts.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50/60 p-4">
                  <h4 className="text-sm font-semibold text-red-900">
                    Negative account balances
                  </h4>
                  <ul className="mt-2 space-y-2 text-xs leading-5 text-red-800">
                    {reconciliation.data.negative_accounts.map((item) => (
                      <li key={item.account_id}>
                        {item.account_number}: {formatPaise(item.balance_paise)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {reconciliation.data.transaction_mismatches.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50/60 p-4">
                  <h4 className="text-sm font-semibold text-red-900">
                    Unbalanced transactions
                  </h4>
                  <ul className="mt-2 space-y-2 text-xs leading-5 text-red-800">
                    {reconciliation.data.transaction_mismatches.map((item) => (
                      <li key={item.transaction_id} className="break-all">
                        {item.transaction_id}: debits{' '}
                        {formatPaise(item.debits_paise)}; credits{' '}
                        {formatPaise(item.credits_paise)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {verification.error && (
        <div className="mt-5">
          <ErrorState error={verification.error} />
        </div>
      )}
      {verification.data && (
        <div className="mt-6 border-t border-border pt-5">
          <ResultBanner passed={verification.data.passed} />
          <p className="mt-3 text-sm text-slate-600">
            Checked {verification.data.accounts_checked}{' '}
            {verification.data.accounts_checked === 1 ? 'account' : 'accounts'}.
          </p>
          {verification.data.accounts.length > 0 && (
            <ul className="mt-4 divide-y divide-border rounded-lg border border-border">
              {verification.data.accounts.map((account) => (
                <li
                  key={account.account_id}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm"
                >
                  <span className="font-medium text-slate-700">
                    Account {account.account_id}
                  </span>
                  <span
                    className={
                      account.passed
                        ? 'font-semibold text-emerald-700'
                        : 'font-semibold text-red-700'
                    }
                  >
                    {account.passed
                      ? 'Pass'
                      : `Fail — first broken entry ${account.first_broken_entry_id ?? 'unknown'}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

function AccountManagement({
  accounts,
  users,
}: {
  accounts: Account[]
  users: AdminUser[]
}) {
  const queryClient = useQueryClient()
  const [accountName, setAccountName] = useState('')
  const [accountType, setAccountType] = useState<AccountType>('PERSONAL')
  const [selectedAccount, setSelectedAccount] = useState('')
  const [selectedUser, setSelectedUser] = useState('')

  const createAccount = useMutation({
    mutationFn: (body: { name: string; type: AccountType }) =>
      apiRequest('/accounts', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: async () => {
      setAccountName('')
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
  const assignMember = useMutation({
    mutationFn: (body: { accountId: string; userId: string }) =>
      apiRequest(`/accounts/${body.accountId}/members`, {
        method: 'POST',
        body: JSON.stringify({ user_id: body.userId }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  function submitCreateAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    createAccount.mutate({ name: accountName.trim(), type: accountType })
  }

  function submitAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedAccount || !selectedUser) return
    assignMember.mutate({ accountId: selectedAccount, userId: selectedUser })
  }

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
        <h3 className="text-base font-semibold text-slate-900">Create account</h3>
        <p className="mt-1 text-sm leading-5 text-slate-500">
          New accounts start with a zero balance.
        </p>
        <form onSubmit={submitCreateAccount} className="mt-5 grid gap-4">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Account name
            <input
              required
              maxLength={255}
              value={accountName}
              onChange={(event) => setAccountName(event.target.value)}
              className="h-11 rounded-lg border border-border px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Account type
            <select
              value={accountType}
              onChange={(event) =>
                setAccountType(event.target.value as AccountType)
              }
              className="h-11 rounded-lg border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              <option value="PERSONAL">Personal</option>
              <option value="SAVINGS">Savings</option>
              <option value="BUSINESS">Business</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={createAccount.isPending || !accountName.trim()}
            className="min-h-11 justify-self-start rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createAccount.isPending ? 'Creating…' : 'Create Account'}
          </button>
        </form>
        {createAccount.isError && (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {createAccount.error.message}
          </p>
        )}
        {createAccount.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700" role="status">
            Account created successfully.
          </p>
        )}
      </section>

      <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
        <h3 className="text-base font-semibold text-slate-900">
          Assign user to account
        </h3>
        <p className="mt-1 text-sm leading-5 text-slate-500">
          Assign an existing user as an account holder.
        </p>
        <form onSubmit={submitAssignment} className="mt-5 grid gap-4">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            Account
            <select
              required
              value={selectedAccount}
              onChange={(event) => setSelectedAccount(event.target.value)}
              className="h-11 rounded-lg border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              <option value="">Select an account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name} · {account.account_number}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            User
            <select
              required
              value={selectedUser}
              onChange={(event) => setSelectedUser(event.target.value)}
              className="h-11 rounded-lg border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              <option value="">Select a user</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.full_name} · {user.email} ({roleLabel(user.role)})
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={
              assignMember.isPending ||
              accounts.length === 0 ||
              users.length === 0
            }
            className="min-h-11 justify-self-start rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {assignMember.isPending ? 'Assigning…' : 'Assign User'}
          </button>
        </form>
        {assignMember.isError && (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {assignMember.error.message}
          </p>
        )}
        {assignMember.isSuccess && (
          <p className="mt-3 text-sm text-emerald-700" role="status">
            User assigned successfully.
          </p>
        )}
      </section>
    </div>
  )
}

interface DepositResponse {
  transaction_id: string
  kind: string
}

function FundAccount({ accounts }: { accounts: Account[] }) {
  const queryClient = useQueryClient()
  const [accountId, setAccountId] = useState('')
  const [amount, setAmount] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    crypto.randomUUID(),
  )

  const deposit = useMutation({
    mutationFn: (body: {
      accountId: number
      amountPaise: number
      idempotencyKey: string
    }) =>
      apiRequest<DepositResponse>('/deposits', {
        method: 'POST',
        body: JSON.stringify({
          account_id: body.accountId,
          amount_paise: body.amountPaise,
        }),
        idempotencyKey: body.idempotencyKey,
      }),
    onSuccess: async () => {
      setAmount('')
      setIdempotencyKey(crypto.randomUUID())
      await queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  function resetAttempt() {
    setIdempotencyKey(crypto.randomUUID())
    setValidationError(null)
    deposit.reset()
  }

  function submitDeposit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setValidationError(null)
    const parsedAccountId = Number(accountId)
    if (!Number.isSafeInteger(parsedAccountId) || parsedAccountId <= 0) {
      setValidationError('Select a valid account.')
      return
    }

    let amountPaise: bigint
    try {
      amountPaise = parseRupeesToPaise(amount)
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : 'Enter a valid amount in rupees.',
      )
      return
    }
    if (amountPaise <= 0n) {
      setValidationError('Amount must be greater than zero.')
      return
    }

    const amountAsNumber = Number(amountPaise)
    if (!Number.isSafeInteger(amountAsNumber)) {
      setValidationError('The amount is too large to submit safely.')
      return
    }
    deposit.mutate({
      accountId: parsedAccountId,
      amountPaise: amountAsNumber,
      idempotencyKey,
    })
  }

  if (accounts.length === 0) {
    return (
      <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
        <h3 className="mb-4 text-base font-semibold text-slate-900">
          Fund account
        </h3>
        <p className="text-sm text-slate-500">
          Create an account before adding funds.
        </p>
      </section>
    )
  }

  return (
    <section className="rounded-xl border border-border bg-white p-5 shadow-sm sm:p-6">
      <h3 className="text-base font-semibold text-slate-900">Fund account</h3>
      <p className="mt-1 text-sm leading-5 text-slate-500">
        Deposit funds into an account. Retrying an unchanged request reuses its
        idempotency key.
      </p>
      <form onSubmit={submitDeposit} className="mt-5 grid gap-4 sm:max-w-xl">
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Account
          <select
            required
            value={accountId}
            disabled={deposit.isPending}
            onChange={(event) => {
              setAccountId(event.target.value)
              resetAttempt()
            }}
            className="h-11 rounded-lg border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50"
          >
            <option value="">Select an account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name} · {account.account_number}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-medium text-slate-700">
          Amount in rupees
          <span className="flex h-11 items-center rounded-lg border border-border focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/15">
            <span className="pl-3 text-sm text-slate-500" aria-hidden="true">
              ₹
            </span>
            <input
              required
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={amount}
              disabled={deposit.isPending}
              onChange={(event) => {
                setAmount(event.target.value)
                resetAttempt()
              }}
              placeholder="0.00"
              className="h-full min-w-0 flex-1 rounded-r-lg bg-transparent px-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 disabled:bg-slate-50"
            />
          </span>
          <span className="text-xs font-normal text-slate-500">
            Enter rupees with up to two decimal places.
          </span>
        </label>
        <p className="break-all font-mono text-xs text-slate-500">
          Idempotency key: {idempotencyKey}
        </p>
        {validationError && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {validationError}
          </p>
        )}
        {deposit.isError && (
          <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {deposit.error.message}
          </p>
        )}
        {deposit.isSuccess && (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">
            Deposit completed successfully. Transaction ID:{' '}
            {deposit.data.transaction_id}
          </p>
        )}
        <button
          type="submit"
          disabled={deposit.isPending || !accountId || !amount}
          className="min-h-11 justify-self-start rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {deposit.isPending ? 'Funding…' : 'Fund Account'}
        </button>
      </form>
    </section>
  )
}

function DirectoryTables({
  accounts,
  users,
}: {
  accounts: Account[]
  users: AdminUser[]
}) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <section className="overflow-hidden rounded-xl border border-border bg-white shadow-sm">
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold text-slate-900">Accounts</h3>
          <p className="mt-1 text-xs text-slate-500">
            {accounts.length} {accounts.length === 1 ? 'account' : 'accounts'}
          </p>
        </div>
        {accounts.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-500">
            No accounts found.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3">Account</th>
                  <th className="px-5 py-3">Type</th>
                  <th className="px-5 py-3 text-right">Balance</th>
                  <th className="px-5 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td className="px-5 py-3">
                      <p className="font-medium text-slate-800">{account.name}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {account.account_number}
                      </p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-slate-600">
                      {account.type}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-right font-medium tabular-nums text-slate-900">
                      {formatPaise(account.balancePaise)}
                    </td>
                    <td className="px-5 py-3 text-slate-600">{account.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-white shadow-sm">
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold text-slate-900">Users</h3>
          <p className="mt-1 text-xs text-slate-500">
            {users.length} {users.length === 1 ? 'user' : 'users'}
          </p>
        </div>
        {users.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-500">
            No users found.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3">User</th>
                  <th className="px-5 py-3">Role</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {users.map((user) => (
                  <tr key={user.id}>
                    <td className="px-5 py-3">
                      <p className="font-medium text-slate-800">
                        {user.full_name}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">{user.email}</p>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3 text-slate-600">
                      {roleLabel(user.role)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

export function AdminPage() {
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: ({ signal }) => fetchAccounts(signal),
  })
  const usersQuery = useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) =>
      apiRequest<AdminUser[]>('/users', { signal }),
  })

  return (
    <>
      <AdminPageIntro />
      <div className="grid gap-6">
        {accountsQuery.isPending || usersQuery.isPending ? (
          <LoadingState label="Loading administration data…" />
        ) : accountsQuery.error ? (
          <ErrorState
            error={accountsQuery.error}
            onRetry={() => void accountsQuery.refetch()}
          />
        ) : usersQuery.error ? (
          <ErrorState
            error={usersQuery.error}
            onRetry={() => void usersQuery.refetch()}
          />
        ) : (
          <>
            <AccountManagement
              accounts={accountsQuery.data}
              users={usersQuery.data}
            />
            <FundAccount accounts={accountsQuery.data} />
            <IntegrityChecks />
            <DirectoryTables
              accounts={accountsQuery.data}
              users={usersQuery.data}
            />
          </>
        )}
      </div>
    </>
  )
}
