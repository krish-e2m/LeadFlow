"use client";

import React, { useMemo, useState } from "react";

export interface ChartPoint {
  label: string;
  value: number;
  /** Comparison value for the same position in the previous period. */
  previous?: number;
}

interface LineChartProps {
  points: ChartPoint[];
  /** Noun used in the readout and the accessible summary, e.g. "leads". */
  unit: string;
  previousLabel?: string;
}

const WIDTH = 800;
const HEIGHT = 240;
const PAD = { top: 12, right: 8, bottom: 28, left: 36 };

function niceMax(max: number): number {
  if (max <= 4) return 4;
  const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
  const step = magnitude / 2;
  return Math.ceil(max / step) * step;
}

/**
 * Single-series line chart: 1px light gridlines, accent line with a flat 8% fill,
 * and an optional gray comparison series. No gradients, no animation.
 */
export const LineChart: React.FC<LineChartProps> = ({ points, unit, previousLabel = "previous period" }) => {
  const [hover, setHover] = useState<number | null>(null);

  const { yMax, path, area, prevPath, coords } = useMemo(() => {
    const max = niceMax(Math.max(1, ...points.flatMap((p) => [p.value, p.previous ?? 0])));
    const innerW = WIDTH - PAD.left - PAD.right;
    const innerH = HEIGHT - PAD.top - PAD.bottom;
    const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
    const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
    const line = (values: number[]) => values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const values = points.map((p) => p.value);
    const hasPrev = points.some((p) => p.previous !== undefined);
    return {
      yMax: max,
      path: line(values),
      area: `${line(values)} L${x(points.length - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`,
      prevPath: hasPrev ? line(points.map((p) => p.previous ?? 0)) : null,
      coords: points.map((p, i) => ({ x: x(i), y: y(p.value) })),
    };
  }, [points]);

  const total = points.reduce((sum, p) => sum + p.value, 0);
  const ticks = [0, 0.5, 1].map((t) => ({ value: Math.round(yMax * t), y: PAD.top + (HEIGHT - PAD.top - PAD.bottom) * (1 - t) }));
  const labelIndexes = Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]));
  const active = hover !== null ? points[hover] : null;

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    const svgX = ratio * WIDTH;
    const innerW = WIDTH - PAD.left - PAD.right;
    const index = Math.round(((svgX - PAD.left) / innerW) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, index)));
  };

  return (
    <figure className="space-y-2">
      <figcaption className="flex min-h-5 items-center justify-between text-caption text-fg-secondary">
        <span aria-live="polite">
          {active ? (
            <>
              <span className="font-medium text-fg">{active.label}</span> · {active.value} {unit}
              {active.previous !== undefined && <span className="text-fg-tertiary"> (vs {active.previous} {previousLabel})</span>}
            </>
          ) : (
            <>
              {total} {unit} in this period
            </>
          )}
        </span>
        {prevPath && (
          <span className="flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-3 rounded-full bg-accent" aria-hidden="true" /> This period
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-3 rounded-full bg-border-strong" aria-hidden="true" /> {previousLabel}
            </span>
          </span>
        )}
      </figcaption>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full"
        role="img"
        aria-label={`${total} ${unit} over ${points.length} days`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((tick) => (
          <g key={tick.y}>
            <line x1={PAD.left} x2={WIDTH - PAD.right} y1={tick.y} y2={tick.y} stroke="var(--border)" strokeWidth={1} />
            <text x={PAD.left - 8} y={tick.y + 4} textAnchor="end" fontSize={12} fill="var(--text-tertiary)">
              {tick.value}
            </text>
          </g>
        ))}

        {prevPath && <path d={prevPath} fill="none" stroke="var(--border-strong)" strokeWidth={1.5} strokeLinejoin="round" />}
        <path d={area} fill="var(--accent)" fillOpacity={0.08} />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {hover !== null && coords[hover] && (
          <g>
            <line x1={coords[hover].x} x2={coords[hover].x} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="var(--border-strong)" strokeWidth={1} />
            <circle cx={coords[hover].x} cy={coords[hover].y} r={4} fill="var(--surface)" stroke="var(--accent)" strokeWidth={2} />
          </g>
        )}

        {labelIndexes.map((i) => (
          <text
            key={i}
            x={coords[i]?.x ?? 0}
            y={HEIGHT - 8}
            textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
            fontSize={12}
            fill="var(--text-tertiary)"
          >
            {points[i]?.label}
          </text>
        ))}
      </svg>
    </figure>
  );
};
