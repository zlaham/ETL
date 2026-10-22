export function formatMoney(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value));
}

export function formatAmount(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  return number.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatStamp(value) {
  if (!value) return null;
  const text = String(value).replace("T", " ").replace("+00:00", "Z");
  if (text.length <= 20) return text;
  return `${text.slice(0, 19)}Z`;
}

export function durationLabel(ms) {
  if (ms < 1) return "computed in under 1 ms";
  return `computed in ${ms} ms`;
}
