import { useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, LoaderCircle, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { ErrorState, EmptyState, LoadingState } from './States'
import { fetchAccounts } from '../lib/accounts'
import { apiRequest } from '../lib/api'
import { formatPaise, parseRupeesToPaise } from '../lib/money'

type MovementKind = 'TRANSFER' | 'DEPOSIT' | 'WITHDRAWAL'

interface MoneyFormConfiguration {
  title: string
  description: string
  endpoint: string
  buttonLabel: string
  successLabel: string
}

const formConfigurations: Record<MovementKind, MoneyFormConfiguration> = {
  TRANSFER: {
    title: 'Transfer',
    description: 'Move money securely between accounts.',
    endpoint: '/transfers',
    buttonLabel: 'Transfer',
    successLabel: 'Transfer completed successfully.',
  },
  DEPOSIT: {
    title: 'Deposit',
    description: 'Add funds to one of your accounts.',
    endpoint: '/deposits',
    buttonLabel: 'Deposit',
    successLabel: 'Deposit completed successfully.',
  },
  WITHDRAWAL: {
    title: 'Withdraw',
    description: 'Withdraw funds from one of your accounts.',
    endpoint: '/withdrawals',
    buttonLabel: 'Withdraw',
    successLabel: 'Withdrawal completed successfully.',
  },
}

interface MovementResponse {
  transaction_id: string
  kind: string
  message?: string
}

type Feedback =
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string }

const CUSTOM_DESTINATION = '__custom_destination__'

function accountOptionLabel(
  account: { account_number: string; name: string; balancePaise: bigint },
): string {
  return `${account.account_number} - ${account.name} (${formatPaise(
    account.balancePaise,
  ).replace(/^₹/, '')})`
}

export function MoneyForm({ kind }: { kind: MovementKind }) {
  const [searchParams] = useSearchParams()
  const initialAccountId = searchParams.get('accountId') ?? ''
  const accountQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: ({ signal }) => fetchAccounts(signal),
  })

  const [sourceAccountId, setSourceAccountId] = useState(initialAccountId)
  const [destinationAccountNumber, setDestinationAccountNumber] = useState('')
  const [isCustomDestination, setIsCustomDestination] = useState(false)
  const [amount, setAmount] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    crypto.randomUUID(),
  )
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submissionLock = useRef(false)
  const configuration = formConfigurations[kind]

  function fieldChanged() {
    setIdempotencyKey(crypto.randomUUID())
    setFeedback(null)
  }

  function changeSource(value: string) {
    setSourceAccountId(value)
    fieldChanged()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submissionLock.current) return

    const sourceId = Number(sourceAccountId)
    if (!Number.isSafeInteger(sourceId) || sourceId <= 0) {
      setFeedback({ kind: 'error', message: 'Select a valid source account.' })
      return
    }

    if (kind === 'TRANSFER' && !destinationAccountNumber.trim()) {
      setFeedback({
        kind: 'error',
        message: 'Select or enter a destination account number.',
      })
      return
    }

    let amountPaise: bigint
    try {
      amountPaise = parseRupeesToPaise(amount)
    } catch (error) {
      setFeedback({
        kind: 'error',
        message:
          error instanceof Error
            ? error.message
            : 'Enter a valid amount in rupees.',
      })
      return
    }

    if (amountPaise <= 0n) {
      setFeedback({ kind: 'error', message: 'Amount must be greater than zero.' })
      return
    }

    const amountAsNumber = Number(amountPaise)
    if (!Number.isSafeInteger(amountAsNumber)) {
      setFeedback({
        kind: 'error',
        message: 'The amount is too large to submit safely.',
      })
      return
    }

    submissionLock.current = true
    setIsSubmitting(true)
    setFeedback(null)
    try {
      const body =
        kind === 'TRANSFER'
          ? {
              from_account_id: sourceId,
              to_account_number: destinationAccountNumber.trim(),
              amount_paise: amountAsNumber,
            }
          : {
              account_id: sourceId,
              amount_paise: amountAsNumber,
            }
      const response = await apiRequest<MovementResponse>(
        configuration.endpoint,
        {
          method: 'POST',
          body: JSON.stringify(body),
          idempotencyKey,
        },
      )
      setFeedback({
        kind: 'success',
        message:
          response.message ??
          `${configuration.successLabel} Transaction ID: ${response.transaction_id}`,
      })
      setIdempotencyKey(crypto.randomUUID())
    } catch (error) {
      setFeedback({
        kind: 'error',
        message:
          error instanceof Error ? error.message : 'The request could not be completed.',
      })
    } finally {
      submissionLock.current = false
      setIsSubmitting(false)
    }
  }

  if (accountQuery.isPending) {
    return <LoadingState label="Loading accounts…" />
  }

  if (accountQuery.error) {
    return (
      <>
        <PageIntro title={configuration.title} description={configuration.description} />
        <ErrorState
          error={accountQuery.error}
          onRetry={() => void accountQuery.refetch()}
        />
      </>
    )
  }

  const accounts = accountQuery.data
  if (accounts.length === 0) {
    return (
      <>
        <PageIntro title={configuration.title} description={configuration.description} />
        <EmptyState
          title="No accounts yet."
          description="Ask an administrator."
          action={
            <Link
              to="/accounts"
              className="font-semibold text-primary hover:text-blue-800"
            >
              View accounts
            </Link>
          }
        />
      </>
    )
  }

  return (
    <>
      <PageIntro title={configuration.title} description={configuration.description} />
      <form
        onSubmit={handleSubmit}
        className="max-w-3xl rounded-xl border border-border bg-white p-5 shadow-sm sm:p-8"
      >
        <div className="grid gap-5">
          <label className="grid gap-2 text-sm font-medium text-slate-700">
            {kind === 'TRANSFER' ? 'From Account' : 'Account'}
            <select
              required
              value={sourceAccountId}
              disabled={isSubmitting}
              onChange={(event) => changeSource(event.target.value)}
              className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50"
            >
              <option value="" disabled>
                Select an account
              </option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {accountOptionLabel(account)}
                </option>
              ))}
            </select>
          </label>

          {kind === 'TRANSFER' && (
            <div className="grid gap-5 sm:grid-cols-2 sm:items-end">
              <label className="grid gap-2 text-sm font-medium text-slate-700">
                To Account
                <select
                  required
                  value={
                    isCustomDestination
                      ? CUSTOM_DESTINATION
                      : destinationAccountNumber
                  }
                  disabled={isSubmitting}
                  onChange={(event) => {
                    const value = event.target.value
                    setIsCustomDestination(value === CUSTOM_DESTINATION)
                    setDestinationAccountNumber(
                      value === CUSTOM_DESTINATION ? '' : value,
                    )
                    fieldChanged()
                  }}
                  className="h-11 w-full rounded-lg border border-border bg-white px-3 text-sm text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50"
                >
                  <option value="" disabled>
                    Select a destination
                  </option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.account_number}>
                      {accountOptionLabel(account)}
                    </option>
                  ))}
                  <option value={CUSTOM_DESTINATION}>
                    Enter an account number…
                  </option>
                </select>
              </label>
              <p className="pb-1 text-xs leading-5 text-slate-500">
                You can select one of your accounts or enter any destination
                account number.
              </p>
              {isCustomDestination && (
                <label className="grid gap-2 text-sm font-medium text-slate-700 sm:col-span-2">
                  Destination account number
                  <input
                    required
                    type="text"
                    maxLength={32}
                    value={destinationAccountNumber}
                    disabled={isSubmitting}
                    onChange={(event) => {
                      setDestinationAccountNumber(event.target.value)
                      fieldChanged()
                    }}
                    placeholder="e.g. ACC1001"
                    className="h-11 w-full rounded-lg border border-border px-3 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50"
                  />
                </label>
              )}
            </div>
          )}

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
                disabled={isSubmitting}
                onChange={(event) => {
                  setAmount(event.target.value)
                  fieldChanged()
                }}
                placeholder="0.00"
                className="h-full min-w-0 flex-1 rounded-r-lg bg-transparent px-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 disabled:bg-slate-50"
              />
            </span>
            <span className="text-xs font-normal text-slate-500">
              Enter rupees with up to two decimal places.
            </span>
          </label>

          <div className="grid gap-2 text-sm font-medium text-slate-700">
            <label htmlFor="idempotency-key">Idempotency Key</label>
            <div className="flex gap-2">
              <input
                id="idempotency-key"
                type="text"
                readOnly
                value={idempotencyKey}
                className="h-11 min-w-0 flex-1 rounded-lg border border-border bg-slate-50 px-3 font-mono text-xs text-slate-600 outline-none"
              />
              <button
                type="button"
                aria-label="Regenerate idempotency key"
                title="Regenerate idempotency key"
                disabled={isSubmitting}
                onClick={fieldChanged}
                className="grid size-11 shrink-0 place-items-center rounded-lg border border-border text-slate-600 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50"
              >
                <RefreshCw className="size-4" aria-hidden="true" />
              </button>
            </div>
            <p className="text-xs font-normal leading-5 text-slate-500">
              This key stays the same when retrying a failed request.
            </p>
          </div>

          {feedback && (
            <p
              role={feedback.kind === 'error' ? 'alert' : 'status'}
              className={`rounded-lg border px-4 py-3 text-sm font-medium ${
                feedback.kind === 'error'
                  ? 'border-red-200 bg-red-50 text-red-800'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-800'
              }`}
            >
              {feedback.message}
            </p>
          )}

          <div className="flex flex-col-reverse gap-3 border-t border-border pt-5 sm:flex-row sm:justify-end">
            <Link
              to="/accounts"
              aria-disabled={isSubmitting}
              className={`inline-flex h-11 items-center justify-center rounded-lg border border-border px-5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
                isSubmitting ? 'pointer-events-none opacity-50' : ''
              }`}
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-white transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : kind === 'TRANSFER' ? (
                <ArrowLeftRight className="size-4" aria-hidden="true" />
              ) : null}
              {isSubmitting ? 'Processing…' : configuration.buttonLabel}
            </button>
          </div>
        </div>
      </form>
    </>
  )
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
