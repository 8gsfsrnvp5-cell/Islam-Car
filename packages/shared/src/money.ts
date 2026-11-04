// Все суммы в API — целые копейки. Здесь только форматирование и разбор ввода.

const NBSP = " ";

export function formatRub(kopecks: number | null | undefined, withKopecks = false): string {
  if (kopecks === null || kopecks === undefined) return "—";
  const negative = kopecks < 0;
  const abs = Math.abs(kopecks);
  const rubles = Math.floor(abs / 100);
  const kop = abs % 100;
  const grouped = String(rubles).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  const tail = withKopecks || kop ? `,${String(kop).padStart(2, "0")}` : "";
  return `${negative ? "−" : ""}${grouped}${tail}${NBSP}₽`;
}

/** «1 600 000,50» → 160000050. Пустая строка → null. Некорректный ввод → NaN. */
export function rublesToKopecks(input: string): number | null {
  const cleaned = input.replace(/[\s ₽]/g, "").replace(",", ".");
  if (cleaned === "") return null;
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return Number.NaN;
  const [whole, frac = ""] = cleaned.split(".");
  return Number(whole) * 100 + Number(frac.padEnd(2, "0"));
}

export function kopecksToInput(kopecks: number | null | undefined): string {
  if (kopecks === null || kopecks === undefined) return "";
  const rubles = Math.floor(kopecks / 100);
  const kop = kopecks % 100;
  return kop ? `${rubles},${String(kop).padStart(2, "0")}` : String(rubles);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  return dt.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];

export function formatMonth(iso: string): string {
  const [y, m] = iso.split("-");
  return `${MONTHS[Number(m) - 1]} ${y}`;
}

export function pluralMonths(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${n} месяц`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} месяца`;
  return `${n} месяцев`;
}
