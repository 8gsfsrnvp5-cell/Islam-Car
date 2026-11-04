"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Простые графики на SVG без сторонних библиотек.
 * Цвета рядов проверены валидатором палитры (CVD и контраст на белой карточке): см. .viz в globals.css.
 * Тексты подписей — цветами текста, цвет несёт только сама отметка. Каждый график имеет табличный вид.
 */

export const SERIES = ["var(--series-1)", "var(--series-2)"];
export const ORDINAL = ["var(--ordinal-1)", "var(--ordinal-2)", "var(--ordinal-3)"];

const MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

export function monthLabel(key: string): string {
  const [y, m] = key.split("-");
  return `${MONTHS[Number(m) - 1]} ${y.slice(2)}`;
}

/** Компактная сумма для осей: 0 · 500 тыс. · 1,2 млн */
export function compactRub(kopecks: number): string {
  const rub = kopecks / 100;
  if (Math.abs(rub) >= 1_000_000) return `${(rub / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  if (Math.abs(rub) >= 1_000) return `${Math.round(rub / 1_000).toLocaleString("ru-RU")} тыс.`;
  return Math.round(rub).toLocaleString("ru-RU");
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow >= value / 4) ?? 10;
  return Math.ceil(value / (step * pow)) * step * pow;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => setWidth(Math.max(280, entries[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export type Series = { key: string; name: string; color: string; values: number[] };

export function Legend({ series }: { series: { name: string; color: string }[] }) {
  return (
    <div className="viz-legend">
      {series.map((s) => (
        <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>
      ))}
    </div>
  );
}

/** Сгруппированные столбцы по месяцам. Одна ось. Подсказка по наведению и фокусу показывает все ряды месяца. */
export function ColumnChart({ categories, series, format, height = 220, extra }: {
  categories: string[]; series: Series[]; format: (v: number) => string; height?: number;
  extra?: (index: number) => ReactNode;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const left = 64, right = 8, top = 8, bottom = 28;
  const plotW = width - left - right, plotH = height - top - bottom;
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values)));
  const band = plotW / Math.max(1, categories.length);
  const gap = 2;
  const barW = Math.min(24, (band * 0.7 - gap * (series.length - 1)) / series.length);
  const groupW = barW * series.length + gap * (series.length - 1);
  const y = (v: number) => top + plotH - (v / max) * plotH;
  const ticks = [0, max / 4, max / 2, (3 * max) / 4, max];
  const labelEvery = Math.ceil(categories.length / Math.max(1, Math.floor(plotW / 56)));

  return (
    <div className="viz" ref={ref} onMouseLeave={() => setHover(null)}>
      {series.length > 1 ? <Legend series={series} /> : null}
      <svg width={width} height={height} role="img" aria-label={series.map((s) => s.name).join(", ")}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} className={t === 0 ? "viz-base" : "viz-grid"} />
            <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">{compactRub(t)}</text>
          </g>
        ))}
        {categories.map((c, i) => {
          const x0 = left + band * i + (band - groupW) / 2;
          return (
            <g key={c} tabIndex={0} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
               className={hover === null || hover === i ? "" : "viz-dim"} aria-label={`${monthLabel(c)}: ${series.map((s) => `${s.name} ${format(s.values[i])}`).join(", ")}`}>
              <rect x={left + band * i} y={top} width={band} height={plotH} fill="transparent" />
              {series.map((s, k) => {
                const v = s.values[i];
                const h = Math.max(0, y(0) - y(v));
                const x = x0 + k * (barW + gap);
                const r = Math.min(4, h, barW / 2);
                // Скругление 4px только у вершины, у основания — прямой угол
                const d = h <= 0 ? "" : `M${x},${y(0)} V${y(v) + r} Q${x},${y(v)} ${x + r},${y(v)} H${x + barW - r} Q${x + barW},${y(v)} ${x + barW},${y(v) + r} V${y(0)} Z`;
                return d ? <path key={s.key} d={d} fill={s.color} /> : null;
              })}
              {i % labelEvery === 0 ? <text x={left + band * i + band / 2} y={height - 8} textAnchor="middle" className="viz-tick">{monthLabel(c)}</text> : null}
            </g>
          );
        })}
      </svg>
      {hover !== null ? (
        <div className="viz-tooltip" style={{ left: Math.min(width - 200, Math.max(0, left + band * hover + band / 2 - 100)), top: 28 }}>
          <div className="viz-tooltip-title">{monthLabel(categories[hover])}</div>
          {series.map((s) => (
            <div key={s.key} className="viz-tooltip-row"><i style={{ background: s.color }} /><strong>{format(s.values[hover])}</strong><span>{s.name}</span></div>
          ))}
          {extra ? extra(hover) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Горизонтальные полосы с подписью значения у конца полосы (для упорядоченных категорий). */
export function BarList({ rows, format }: { rows: { label: string; value: number; color: string; note?: string }[]; format: (v: number) => string }) {
  const max = Math.max(0, ...rows.map((r) => r.value)) || 1;
  return (
    <div className="viz-bars">
      {rows.map((r) => (
        <div key={r.label} className="viz-bar-row" tabIndex={0} title={`${r.label}: ${format(r.value)}${r.note ? ` · ${r.note}` : ""}`}>
          <span className="viz-bar-label">{r.label}</span>
          <span className="viz-bar-track">
            <span className="viz-bar-fill" style={{ width: `${(r.value / max) * 75}%`, background: r.color }} />
            <span className="viz-bar-value">{format(r.value)}{r.note ? <span className="muted"> · {r.note}</span> : null}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Переключатель «График / Таблица» для карточки. */
export function useTableToggle(): [boolean, ReactNode] {
  const [table, setTable] = useState(false);
  return [table, (
    <div className="actions" key="toggle">
      <button className={`btn btn-sm ${!table ? "btn-primary" : ""}`} onClick={() => setTable(false)}>График</button>
      <button className={`btn btn-sm ${table ? "btn-primary" : ""}`} onClick={() => setTable(true)}>Таблица</button>
    </div>
  )];
}
