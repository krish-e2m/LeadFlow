"use client";

import React, { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Check, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { AUDIT_STEPS, MOCK_COMPANIES, type MockCompany } from "./content";

/**
 * Hero product mockup: an illustrative demo only. It holds its own local state, never calls a
 * real API, and never touches real data — selecting a company, "approving" one, and running the
 * audit simulation are all client-side theater to show how the real product behaves.
 */
export function HeroProductMockup() {
  const prefersReducedMotion = useReducedMotion();
  const [selectedId, setSelectedId] = useState<MockCompany["id"]>(MOCK_COMPANIES[0].id);
  const [approvedMap, setApprovedMap] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(MOCK_COMPANIES.map((c) => [c.id, c.startsApproved]))
  );
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [auditing, setAuditing] = useState(false);
  const [tickerText, setTickerText] = useState<string | null>(null);
  const [liveScore, setLiveScore] = useState<Record<string, number>>(() =>
    Object.fromEntries(MOCK_COMPANIES.map((c) => [c.id, c.score]))
  );
  const [shimmer, setShimmer] = useState(false);

  const cleanupFnsRef = useRef<Array<() => void>>([]);
  useEffect(() => {
    return () => cleanupFnsRef.current.forEach((fn) => fn());
  }, []);

  const selected = MOCK_COMPANIES.find((c) => c.id === selectedId) ?? MOCK_COMPANIES[0];

  function handleSelect(id: MockCompany["id"]) {
    if (auditing) return;
    setSelectedId(id);
  }

  function handleApprove(id: string) {
    if (approvedMap[id] || approvingId) return;
    setApprovingId(id);
    const t = window.setTimeout(() => {
      setApprovedMap((prev) => ({ ...prev, [id]: true }));
      setApprovingId(null);
    }, 600);
    cleanupFnsRef.current.push(() => window.clearTimeout(t));
  }

  function handleRunAudit() {
    if (auditing) return;
    setAuditing(true);
    const target = selected.score;

    if (prefersReducedMotion) {
      setLiveScore((prev) => ({ ...prev, [selectedId]: target }));
      setTickerText(`Score calculated: ${target}/100 • 22 signals checked`);
      const t = window.setTimeout(() => {
        setAuditing(false);
        setTickerText(null);
      }, 900);
      cleanupFnsRef.current.push(() => window.clearTimeout(t));
      return;
    }

    setShimmer(true);
    let step = 0;
    setTickerText(AUDIT_STEPS[0]);
    const tickerInterval = window.setInterval(() => {
      step += 1;
      if (step < AUDIT_STEPS.length) setTickerText(AUDIT_STEPS[step]);
    }, 450);
    cleanupFnsRef.current.push(() => window.clearInterval(tickerInterval));

    let current = 50;
    setLiveScore((prev) => ({ ...prev, [selectedId]: current }));
    const scoreInterval = window.setInterval(() => {
      current += 2;
      if (current >= target) {
        setLiveScore((prev) => ({ ...prev, [selectedId]: target }));
        window.clearInterval(scoreInterval);
      } else {
        setLiveScore((prev) => ({ ...prev, [selectedId]: current }));
      }
    }, 35);
    cleanupFnsRef.current.push(() => window.clearInterval(scoreInterval));

    const endTimeout = window.setTimeout(() => {
      window.clearInterval(tickerInterval);
      setShimmer(false);
      setTickerText(`Score calculated: ${target}/100 • 22 signals checked`);
      const hideTimeout = window.setTimeout(() => {
        setAuditing(false);
        setTickerText(null);
      }, 1400);
      cleanupFnsRef.current.push(() => window.clearTimeout(hideTimeout));
    }, 2200);
    cleanupFnsRef.current.push(() => window.clearTimeout(endTimeout));
  }

  return (
    <div className="relative rounded-2xl border border-slate-200/90 bg-white/95 p-4 shadow-landing-elevation backdrop-blur-xl sm:p-5">
      <div className="flex items-center justify-between border-b border-slate-100 pb-4">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
          <span className="ml-2 font-mono text-xs font-medium text-slate-400">workspace / demo-pipeline</span>
        </div>
        <button
          type="button"
          onClick={handleRunAudit}
          disabled={auditing}
          title="Simulates a 22-signal recalculation for the selected company — demo only"
          className={cn(
            "group inline-flex items-center gap-1.5 rounded-md border border-emerald-200/80 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 shadow-sm transition-all duration-150 hover:bg-emerald-100/90 active:scale-95 disabled:cursor-default",
            auditing && "border-emerald-300 bg-emerald-100"
          )}
        >
          <RefreshCw className={cn("h-3 w-3 text-emerald-600", auditing && "motion-safe:animate-spin")} />
          Run live audit
        </button>
      </div>

      {tickerText && (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-emerald-200/70 bg-emerald-50/80 px-3 py-1.5 font-mono text-[11px] text-emerald-800">
          <span className="flex items-center gap-2">
            <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-emerald-600" />
            {tickerText}
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600">Demo</span>
        </div>
      )}

      <div className="mt-4 space-y-3">
        {MOCK_COMPANIES.map((company) =>
          company.id === selectedId ? (
            <ExpandedCompanyCard
              key={company.id}
              company={company}
              score={liveScore[company.id] ?? company.score}
              shimmer={shimmer}
              approved={!!approvedMap[company.id]}
              approving={approvingId === company.id}
              onApprove={() => handleApprove(company.id)}
            />
          ) : (
            <CompactCompanyRow
              key={company.id}
              company={company}
              approved={!!approvedMap[company.id]}
              onSelect={() => handleSelect(company.id)}
            />
          )
        )}
      </div>
    </div>
  );
}

function toneClasses(tone: MockCompany["tone"]) {
  if (tone === "low") return { badge: "bg-amber-50 text-amber-700 border-amber-200", dot: "bg-amber-500" };
  return { badge: "bg-emerald-100 text-emerald-800 border-emerald-200", dot: "bg-emerald-500" };
}

function ExpandedCompanyCard({
  company,
  score,
  shimmer,
  approved,
  approving,
  onApprove,
}: {
  company: MockCompany;
  score: number;
  shimmer: boolean;
  approved: boolean;
  approving: boolean;
  onApprove: () => void;
}) {
  const tone = toneClasses(company.tone);
  const signals = Object.values(company.signals);

  return (
    <div className="space-y-3 rounded-xl border border-emerald-300 bg-emerald-50/20 p-3.5 shadow-sm transition-colors">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white ring-1 ring-slate-800">
            {company.initials}
          </div>
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              {company.name}
              <span className="font-mono text-[11px] text-slate-400">{company.domain}</span>
            </div>
            <div className="text-xs text-slate-500">{company.meta}</div>
          </div>
        </div>
        <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold shadow-sm", tone.badge)}>
          {score} / 100
        </span>
      </div>

      <div className="space-y-2 rounded-lg border border-slate-200/80 bg-white p-3 text-xs shadow-inner">
        <div className="flex items-center justify-between border-b border-slate-100 pb-1 font-medium text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className={cn("h-1.5 w-1.5 rounded-full", tone.dot)} />
            Signal audit verification
          </span>
          <span className="rounded border border-emerald-200/50 bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] text-emerald-700">
            {company.statusBadge}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2 pt-1 font-mono text-[11px]">
          {signals.map((signal) => (
            <div
              key={signal.label}
              className={cn(
                "relative flex flex-col justify-between rounded border border-slate-100 bg-slate-50 p-2 transition-all hover:border-emerald-200 hover:bg-emerald-50/40",
                shimmer && "landing-shimmer-active"
              )}
              title={signal.detail}
            >
              <div className="flex items-center justify-between">
                <span className="text-slate-600">{signal.label}</span>
                <span className="font-bold text-emerald-600">{signal.status}</span>
              </div>
              <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-slate-200/70">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-all duration-700"
                  style={{ width: `${shimmer ? 20 : signal.value}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        <p className="border-t border-slate-100 pt-1 text-[11px] italic text-slate-500">{company.evidence}</p>

        <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-2">
          <span className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <span className={cn("h-1.5 w-1.5 rounded-full", approved ? "bg-emerald-500" : "bg-amber-500 motion-safe:animate-pulse")} />
            Human checkpoint:{" "}
            <strong className={cn("font-medium", approved ? "text-emerald-700" : "text-slate-700")}>
              {approved ? "Cleared" : "Required"}
            </strong>
          </span>

          <button
            type="button"
            onClick={onApprove}
            disabled={approved || approving}
            className={cn(
              "flex items-center gap-1.5 overflow-hidden rounded px-3 py-1.5 text-xs font-semibold shadow-sm transition-all active:scale-95",
              approved
                ? "cursor-default border border-emerald-300 bg-emerald-50 text-emerald-800 shadow-none"
                : "bg-emerald-700 text-white hover:bg-emerald-800 disabled:cursor-default"
            )}
          >
            {approving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Verifying…
              </>
            ) : approved ? (
              <>
                <Check className="h-3.5 w-3.5" />
                Approved • synced to HubSpot
              </>
            ) : (
              <>
                <Check className="h-3.5 w-3.5" />
                Approve &amp; reveal (1 credit)
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function CompactCompanyRow({
  company,
  approved,
  onSelect,
}: {
  company: MockCompany;
  approved: boolean;
  onSelect: () => void;
}) {
  const tone = toneClasses(company.tone);
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-400 text-xs font-bold text-white transition-transform group-hover:scale-105">
          {company.initials}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-700 transition-colors group-hover:text-slate-900">{company.name}</div>
          <div className="text-xs text-slate-400">{company.meta}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold", tone.badge)}>
          {company.score} / 100
        </span>
        {approved && (
          <span className="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
            <Check className="h-3 w-3" />
            Synced
          </span>
        )}
      </div>
    </button>
  );
}
