import { AlertCircle, Inbox, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div
      className="flex min-h-48 items-center justify-center gap-3 text-sm text-slate-500"
      role="status"
      aria-live="polite"
    >
      <LoaderCircle className="size-5 animate-spin text-primary" aria-hidden="true" />
      {label}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-white px-6 py-10 text-center">
      <span className="mb-4 grid size-12 place-items-center rounded-full bg-slate-100 text-slate-500">
        <Inbox className="size-5" aria-hidden="true" />
      </span>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: Error | string
  onRetry?: () => void
}) {
  const message = typeof error === 'string' ? error : error.message
  return (
    <div
      className="flex min-h-48 flex-col items-center justify-center px-6 py-10 text-center"
      role="alert"
    >
      <AlertCircle className="size-8 text-red-600" aria-hidden="true" />
      <h2 className="mt-3 text-base font-semibold text-slate-900">
        Something went wrong
      </h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-600">{message}</p>
      {onRetry && (
        <button
          type="button"
          className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          onClick={onRetry}
        >
          Try again
        </button>
      )}
    </div>
  )
}
