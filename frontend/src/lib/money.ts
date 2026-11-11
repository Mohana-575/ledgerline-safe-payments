const paisePerRupee = 100n

export function formatPaise(paise: bigint): string {
  const isNegative = paise < 0n
  const absolutePaise = isNegative ? -paise : paise
  const rupees = absolutePaise / paisePerRupee
  const paiseRemainder = (absolutePaise % paisePerRupee)
    .toString()
    .padStart(2, '0')
  const formattedRupees = new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 0,
  }).format(rupees)

  return `${isNegative ? '-' : ''}₹${formattedRupees}.${paiseRemainder}`
}

export function parseRupeesToPaise(value: string): bigint {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,2}))?$/.exec(value)
  if (!match) {
    throw new RangeError('Enter rupees as digits with up to two decimal places')
  }

  const rupees = BigInt(match[1])
  const fraction = BigInt((match[2] ?? '').padEnd(2, '0') || '0')
  return rupees * paisePerRupee + fraction
}
