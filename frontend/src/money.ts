const MONEY_SCALE = 6;

function scaledMoney(value: string): bigint {
  const normalized = value.trim();
  const match = /^(-?)(\d+)(?:\.(\d{1,6}))?$/.exec(normalized);
  if (!match) throw new Error(`Invalid fixed-precision money value: ${value}`);
  const [, sign, integer, fraction = ""] = match;
  const units = BigInt(`${integer}${fraction.padEnd(MONEY_SCALE, "0")}`);
  return sign === "-" ? -units : units;
}

export function compareMoney(left: string, right: string): number {
  const leftValue = scaledMoney(left);
  const rightValue = scaledMoney(right);
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}

export function absoluteMoney(value: string): string {
  return value.startsWith("-") ? value.slice(1) : value;
}

export function maximumMoney(left: string, right: string): string {
  return compareMoney(left, right) >= 0 ? left : right;
}

export function formatMoney(value: string, currency: string | null): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return `${currency ?? ""} ${value}`.trim();
  const [, sign, integer, fraction = ""] = match;
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const amount = `${sign}${grouped}.${fraction.padEnd(MONEY_SCALE, "0")}`;
  return `${currency ?? ""} ${amount}`.trim();
}
