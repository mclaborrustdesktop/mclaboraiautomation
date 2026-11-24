"use client";

import { useState } from "react";

/* Chart tokens (validated reference palette, single-series blue). */
const SERIES_1 = "#2a78d6";
const GRID = "#e1e0d9";
const AXIS = "#c3c2b7";
const MUTED = "#898781";
const INK = "#0b0b0b";

export interface ColumnDatum {
  label: string;
  value: number;
  detail?: string;
}

/** Single-series column chart with hover tooltip; no legend (the title names the series). */
export function ColumnChart({ data, height = 180, valueLabel = "" }: { data: ColumnDatum[]; height?: number; valueLabel?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 640;
  const padL = 40, padR = 8, padT = 12, padB = 28;
  const plotW = W - padL - padR;
  const plotH = height - padT - padB;
  const max = Math.max(1, ...data.map((d) => d.value));
  const niceMax = niceCeil(max);
  const n = data.length || 1;
  const band = plotW / n;
  const barW = Math.min(24, band * 0.6);
  const y = (v: number) => padT + plotH - (v / niceMax) * plotH;
  const ticks = [0, 0.5, 1].map((t) => t * niceMax);

  if (data.length === 0) return <div className="py-8 text-center text-sm text-slate-500">No data yet.</div>;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} className="h-auto w-full" role="img" aria-label={`Column chart${valueLabel ? ` of ${valueLabel}` : ""}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke={t === 0 ? AXIS : GRID} strokeWidth={1} />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill={MUTED}>{compact(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + band * i + (band - barW) / 2;
          const top = y(d.value);
          const h = Math.max(0, padT + plotH - top);
          const r = Math.min(4, h);
          const active = hover === i;
          return (
            <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* hit target wider than the mark */}
              <rect x={padL + band * i} y={padT} width={band} height={plotH} fill="transparent" />
              <path
                d={`M${x},${padT + plotH} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${barW - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z`}
                fill={SERIES_1}
                opacity={hover === null || active ? 1 : 0.55}
              />
              {(active || i === data.length - 1) && (
                <text x={x + barW / 2} y={top - 4} textAnchor="middle" fontSize={10} fill={INK} fontWeight={600}>{compact(d.value)}</text>
              )}
              <text x={x + barW / 2} y={height - 10} textAnchor="middle" fontSize={10} fill={MUTED}>{d.label}</text>
            </g>
          );
        })}
      </svg>
      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute top-1 right-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 shadow-sm">
          <div className="font-medium">{data[hover].label}</div>
          <div>{valueLabel ? `${valueLabel}: ` : ""}{data[hover].value.toLocaleString()}</div>
          {data[hover].detail && <div className="text-slate-500">{data[hover].detail}</div>}
        </div>
      )}
    </div>
  );
}

/** Horizontal single-series bars with direct labels (magnitude ranking). */
export function HBarList({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (data.length === 0) return <div className="py-8 text-center text-sm text-slate-500">No data yet.</div>;
  return (
    <ul className="space-y-2" aria-label="Ranked bars">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[120px_1fr_40px] items-center gap-2 text-sm" title={`${d.label}: ${d.value}`}>
          <span className="truncate text-slate-700">{d.label}</span>
          <span className="h-3 w-full rounded-r-[4px] bg-slate-100">
            <span className="block h-3 rounded-r-[4px]" style={{ width: `${(d.value / max) * 100}%`, background: SERIES_1 }} />
          </span>
          <span className="text-right text-xs text-slate-700 tabular-nums">{d.value}</span>
        </li>
      ))}
    </ul>
  );
}

function niceCeil(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / p;
  const n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return n * p;
}

function compact(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 10_000) return `${Math.round(v / 1000)}K`;
  if (v >= 1_000) return `${(v / 1000).toFixed(1)}K`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
