import { apiRequest } from './api'

export interface ApiAccount {
  id: number
  account_number: string
  name: string
  type: string
  balance_paise: number
  status: string
}

export interface Account extends Omit<ApiAccount, 'balance_paise'> {
  balancePaise: bigint
}

function toPaise(value: number): bigint {
  if (!Number.isSafeInteger(value)) {
    throw new Error('The server returned an invalid account balance.')
  }
  return BigInt(value)
}

export async function fetchAccounts(signal?: AbortSignal): Promise<Account[]> {
  const accounts = await apiRequest<ApiAccount[]>('/accounts', { signal })
  return accounts.map(({ balance_paise, ...account }) => ({
    ...account,
    balancePaise: toPaise(balance_paise),
  }))
}
