import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { ScoreBand } from "@/types";

// Teach tailwind-merge the theme's custom font sizes; otherwise `text-caption` is read as a text
// color and silently removes `text-white` (and other real colors) from the same element.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["caption", "kpi"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type Tone = "success" | "warning" | "danger" | "neutral" | "accent";

export interface BandChanges {
  before: Record<string, number>;
  after: Record<string, number>;
}

const BAND_ORDER = ["qualified", "review", "disqualified", "unscored"];

/** "Qualified 3 → 5, Review 8 → 6" for a bulk re-score result. */
export function describeBandChanges(changes: BandChanges | null | undefined): string | undefined {
  if (!changes) return undefined;
  const parts = BAND_ORDER.filter((band) => (changes.before[band] ?? 0) !== (changes.after[band] ?? 0)).map(
    (band) => `${band[0].toUpperCase()}${band.slice(1)} ${changes.before[band] ?? 0} → ${changes.after[band] ?? 0}`
  );
  return parts.length ? parts.join(", ") : "No lead changed band.";
}

/** Semantic tone for a score band (qualified is positive, review needs attention, disqualified is negative). */
export function getBandTone(band: ScoreBand | null | undefined): Tone {
  switch (band) {
    case "qualified":
    case "high":
      return "success";
    case "review":
    case "medium":
      return "warning";
    case "disqualified":
      return "danger";
    case "low":
      return "neutral";
    default:
      return "neutral";
  }
}

/** Token classes for places that still need raw classes (legacy callers). */
export function getScoreBandColor(band: ScoreBand): { bg: string; text: string; border: string } {
  switch (getBandTone(band)) {
    case "success":
      return { bg: "bg-success-subtle", text: "text-success", border: "border-transparent" };
    case "warning":
      return { bg: "bg-warning-subtle", text: "text-warning", border: "border-transparent" };
    case "danger":
      return { bg: "bg-danger-subtle", text: "text-danger", border: "border-transparent" };
    default:
      return { bg: "bg-neutral-subtle", text: "text-neutral", border: "border-transparent" };
  }
}

export function formatDate(dateString: string | null): string {
  if (!dateString) return "—";
  try {
    const d = new Date(dateString);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return dateString;
  }
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(value);
}

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "2h ago" style label for recent timestamps; falls back to a short date past 30 days. */
export function formatRelative(dateString: string | null | undefined): string {
  if (!dateString) return "—";
  const then = new Date(dateString).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return "Just now";
  for (const [unit, size] of RELATIVE_UNITS) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      if (unit === "month" || unit === "year") {
        return new Date(then).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
      }
      const short = unit === "minute" ? "m" : unit === "hour" ? "h" : "d";
      return `${n}${short} ago`;
    }
  }
  return "Just now";
}

export function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
