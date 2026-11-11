import { useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useLocation, useNavigate } from 'react-router'
import {
  Eye,
  EyeOff,
  Landmark,
  LockKeyhole,
  Mail,
  UserRound,
  type LucideIcon,
} from 'lucide-react'
import { z } from 'zod'
import { useQueryClient } from '@tanstack/react-query'
import { authQueryKey } from '../auth/authContext'
import { apiRequest } from '../lib/api'
import type { AuthUser } from '../types/auth'

interface LoginLocationState {
  registered?: boolean
}

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
})

const registerSchema = z
  .object({
    full_name: z
      .string()
      .trim()
      .min(1, 'Enter your full name')
      .max(255, 'Name must be 255 characters or fewer'),
    email: z
      .string()
      .trim()
      .email('Enter a valid email address')
      .max(320, 'Email must be 320 characters or fewer'),
    password: z
      .string()
      .min(8, 'Password must be at least 8 characters')
      .max(1024, 'Password must be 1024 characters or fewer'),
    confirmPassword: z.string().min(1, 'Confirm your password'),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type LoginFormValues = z.infer<typeof loginSchema>
type RegisterFormValues = z.infer<typeof registerSchema>

function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-[linear-gradient(135deg,#0b1530_0%,#14264b_52%,#0d1b3b_100%)] px-4 py-10 sm:px-6">
      <header className="mb-8 flex flex-col items-center text-center">
        <Link
          to="/login"
          className="flex items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white"
          aria-label="LedgerLine home"
        >
          <span className="grid size-12 place-items-center rounded-2xl bg-blue-500 text-white shadow-lg shadow-blue-950/30">
            <Landmark aria-hidden="true" size={25} strokeWidth={2.2} />
          </span>
          <span className="text-2xl font-semibold tracking-tight text-white">
            LedgerLine
          </span>
        </Link>
        <p className="mt-4 max-w-sm text-sm leading-6 text-blue-100/80 sm:text-base">
          Money Movement with a Ledger You Can Prove
        </p>
      </header>
      {children}
    </main>
  )
}

function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  return (
    <section className="w-full max-w-md rounded-2xl bg-white px-6 py-7 shadow-2xl shadow-slate-950/25 sm:px-9 sm:py-9">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
        {title}
      </h1>
      <p className="mt-2 text-sm leading-6 text-slate-500">{subtitle}</p>
      {children}
    </section>
  )
}

function AuthField({
  id,
  label,
  icon: Icon,
  error,
  children,
}: {
  id: string
  label: string
  icon: LucideIcon
  error?: string
  children: ReactNode
}) {
  const errorId = `${id}-error`

  return (
    <div>
      <label
        className="mb-2 block text-sm font-medium text-slate-700"
        htmlFor={id}
      >
        {label}
      </label>
      <div
        className={`flex min-h-12 items-center gap-3 rounded-lg border px-3.5 transition-colors focus-within:ring-4 ${
          error
            ? 'border-red-300 focus-within:border-red-500 focus-within:ring-red-100'
            : 'border-slate-200 focus-within:border-blue-500 focus-within:ring-blue-100'
        }`}
      >
        <Icon
          aria-hidden="true"
          className="shrink-0 text-slate-400"
          size={18}
          strokeWidth={1.8}
        />
        {children}
      </div>
      {error && (
        <p id={errorId} className="mt-1.5 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  )
}

const inputClassName =
  'min-w-0 flex-1 bg-transparent py-3 text-sm text-slate-900 outline-none placeholder:text-slate-400'

function VisibilityButton({
  visible,
  onToggle,
}: {
  visible: boolean
  onToggle: () => void
}) {
  const Icon = visible ? EyeOff : Eye

  return (
    <button
      className="rounded-md p-1 text-slate-400 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      type="button"
      onClick={onToggle}
      aria-label={visible ? 'Hide password' : 'Show password'}
      aria-pressed={visible}
    >
      <Icon aria-hidden="true" size={18} />
    </button>
  )
}

function FormError({ children }: { children: ReactNode }) {
  return (
    <p
      className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700"
      role="alert"
    >
      {children}
    </p>
  )
}

const submitButtonClassName =
  'w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60'

export function LoginPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as LoginLocationState | null
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  async function submit(values: LoginFormValues) {
    setError(null)

    try {
      const user = await apiRequest<AuthUser>('/auth/login', {
        method: 'POST',
        body: JSON.stringify(values),
      })
      await queryClient.cancelQueries({ queryKey: authQueryKey })
      queryClient.setQueryData(authQueryKey, user)
      await navigate('/dashboard', { replace: true })
    } catch {
      setError('Unable to sign in. Check your email and password, then try again.')
    }
  }

  return (
    <AuthFrame>
      <AuthCard title="Sign In" subtitle="Welcome back. Sign in to continue.">
        <form
          className="mt-7 space-y-5"
          noValidate
          onSubmit={handleSubmit(submit)}
        >
          {state?.registered && (
            <p
              className="rounded-lg border border-green-200 bg-green-50 px-3.5 py-3 text-sm text-green-700"
              role="status"
            >
              Your account is ready. Sign in to continue.
            </p>
          )}
          <AuthField
            id="login-email"
            label="Email address"
            icon={Mail}
            error={errors.email?.message}
          >
            <input
              {...register('email')}
              id="login-email"
              className={inputClassName}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'login-email-error' : undefined}
            />
          </AuthField>
          <AuthField
            id="login-password"
            label="Password"
            icon={LockKeyhole}
            error={errors.password?.message}
          >
            <input
              {...register('password')}
              id="login-password"
              className={inputClassName}
              type={isPasswordVisible ? 'text' : 'password'}
              autoComplete="current-password"
              placeholder="Enter your password"
              aria-invalid={Boolean(errors.password)}
              aria-describedby={
                errors.password ? 'login-password-error' : undefined
              }
            />
            <VisibilityButton
              visible={isPasswordVisible}
              onToggle={() => setIsPasswordVisible((visible) => !visible)}
            />
          </AuthField>
          {error && <FormError>{error}</FormError>}
          <button
            className={submitButtonClassName}
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Signing in…' : 'Login'}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-500">
          Don&apos;t have an account?{' '}
          <Link
            to="/register"
            className="font-semibold text-blue-700 hover:text-blue-800 hover:underline"
          >
            Register
          </Link>
        </p>
      </AuthCard>
    </AuthFrame>
  )
}

export function RegisterPage() {
  const navigate = useNavigate()
  const [isPasswordVisible, setIsPasswordVisible] = useState(false)
  const [isConfirmPasswordVisible, setIsConfirmPasswordVisible] =
    useState(false)
  const [error, setError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      full_name: '',
      email: '',
      password: '',
      confirmPassword: '',
    },
  })

  async function submit({ full_name, email, password }: RegisterFormValues) {
    setError(null)

    try {
      await apiRequest<AuthUser>('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ full_name, email, password }),
      })
      await navigate('/login', { state: { registered: true } })
    } catch {
      setError('Unable to create your account. Please try again.')
    }
  }

  return (
    <AuthFrame>
      <AuthCard
        title="Create your account"
        subtitle="Get started with your LedgerLine account."
      >
        <form
          className="mt-7 space-y-4"
          noValidate
          onSubmit={handleSubmit(submit)}
        >
          <AuthField
            id="register-full-name"
            label="Full name"
            icon={UserRound}
            error={errors.full_name?.message}
          >
            <input
              {...register('full_name')}
              id="register-full-name"
              className={inputClassName}
              type="text"
              autoComplete="name"
              placeholder="Your full name"
              aria-invalid={Boolean(errors.full_name)}
              aria-describedby={
                errors.full_name ? 'register-full-name-error' : undefined
              }
            />
          </AuthField>
          <AuthField
            id="register-email"
            label="Email address"
            icon={Mail}
            error={errors.email?.message}
          >
            <input
              {...register('email')}
              id="register-email"
              className={inputClassName}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={Boolean(errors.email)}
              aria-describedby={
                errors.email ? 'register-email-error' : undefined
              }
            />
          </AuthField>
          <AuthField
            id="register-password"
            label="Password"
            icon={LockKeyhole}
            error={errors.password?.message}
          >
            <input
              {...register('password')}
              id="register-password"
              className={inputClassName}
              type={isPasswordVisible ? 'text' : 'password'}
              autoComplete="new-password"
              placeholder="At least 8 characters"
              aria-invalid={Boolean(errors.password)}
              aria-describedby={
                errors.password ? 'register-password-error' : undefined
              }
            />
            <VisibilityButton
              visible={isPasswordVisible}
              onToggle={() => setIsPasswordVisible((visible) => !visible)}
            />
          </AuthField>
          <AuthField
            id="register-confirm-password"
            label="Confirm password"
            icon={LockKeyhole}
            error={errors.confirmPassword?.message}
          >
            <input
              {...register('confirmPassword')}
              id="register-confirm-password"
              className={inputClassName}
              type={isConfirmPasswordVisible ? 'text' : 'password'}
              autoComplete="new-password"
              placeholder="Enter your password again"
              aria-invalid={Boolean(errors.confirmPassword)}
              aria-describedby={
                errors.confirmPassword
                  ? 'register-confirm-password-error'
                  : undefined
              }
            />
            <VisibilityButton
              visible={isConfirmPasswordVisible}
              onToggle={() =>
                setIsConfirmPasswordVisible((visible) => !visible)
              }
            />
          </AuthField>
          {error && <FormError>{error}</FormError>}
          <button
            className={`${submitButtonClassName} mt-2`}
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Creating account…' : 'Register'}
          </button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-500">
          Already have an account?{' '}
          <Link
            to="/login"
            className="font-semibold text-blue-700 hover:text-blue-800 hover:underline"
          >
            Sign in
          </Link>
        </p>
      </AuthCard>
    </AuthFrame>
  )
}
