"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/Badge";
import { CountUp } from "@/components/CountUp";
import { LineChart, type ChartPoint } from "@/components/LineChart";
import { MeterBar } from "@/components/Meter";
import { PageHeader } from "@/components/PageHeader";
import { RunProgressIndicator } from "@/components/RunProgressIndicator";
import { Select } from "@/components/Select";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/StateDisplay";
import { Run, Lead, UsageOverviewResponse, AccessRequest } from "@/types";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { cn, formatNumber, formatRelative, getBandTone } from "@/lib/utils";

const RANGE_OPTIONS = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const DAY_MS = 24 * 60 * 60 * 1000;
const LEAD_FETCH_LIMIT = 100;

const STAGGER_CONTAINER = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};
const STAGGER_ITEM = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] as const } },
};

interface Kpi {
  label: string;
  value: number;
  current: number;
  previous: number;
  /** Whether more is better. Neutral metrics never turn red or green. */
  direction: "up-good" | "neutral";
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function Delta({ kpi, days }: { kpi: Kpi; days: number }) {
  if (kpi.current === 0 && kpi.previous === 0) {
    return <p className="text-xs text-fg-tertiary">No activity in this period</p>;
  }
  const diff = kpi.current - kpi.previous;
  const Icon = diff >= 0 ? ArrowUpRight : ArrowDownRight;
  const tone =
    kpi.direction === "neutral" || diff === 0 ? "text-fg-secondary" : diff > 0 ? "text-success" : "text-danger";
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-fg-secondary">
        {kpi.current} new in {days} days
      </span>
      <span
        className={cn("inline-flex items-center gap-0.5 font-medium", tone)}
        title={`${kpi.previous} in the previous ${days} days`}
      >
        {diff !== 0 && <Icon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />}
        {diff > 0 ? "+" : ""}
        {diff}
      </span>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-live="polite">
      <span className="sr-only">Loading dashboard…</span>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { user } = useAuth();
  const isClientViewer = user?.role === "client_viewer";
  const reduceMotion = useReducedMotion();

  const [runs, setRuns] = useState<Run[]>([]);
  const [usage, setUsage] = useState<UsageOverviewResponse | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [pendingAccessRequests, setPendingAccessRequests] = useState<AccessRequest[]>([]);
  const [rangeDays, setRangeDays] = useState("30");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboardData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [usageData, runsData, leadsData, accessRequestsData] = await Promise.all([
        apiClient.get<UsageOverviewResponse>("/admin/usage").catch(() => null),
        apiClient.get<Run[]>("/runs?limit=5").catch(() => []),
        apiClient.get<Lead[]>(`/leads?limit=${LEAD_FETCH_LIMIT}`).catch(() => []),
        apiClient.get<AccessRequest[]>("/access-requests?status=pending").catch(() => []),
      ]);
      setUsage(usageData);
      setRuns(runsData);
      setLeads(leadsData);
      setPendingAccessRequests(accessRequestsData);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "The dashboard data couldn't be loaded.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDashboardData();
  }, [fetchDashboardData]);

  const days = Number(rangeDays);

  const { kpis, chartPoints } = useMemo(() => {
    const today = startOfDay(new Date());
    const periodStart = today - (days - 1) * DAY_MS;
    const previousStart = periodStart - days * DAY_MS;

    const inPeriod = (lead: Lead) => {
      const t = startOfDay(new Date(lead.created_at));
      return t >= periodStart && t <= today;
    };
    const inPrevious = (lead: Lead) => {
      const t = startOfDay(new Date(lead.created_at));
      return t >= previousStart && t < periodStart;
    };

    const defs: { label: string; match: (l: Lead) => boolean; total: number; direction: Kpi["direction"] }[] = [
      { label: "Sourced", match: () => true, total: usage ? usage.total_leads_sourced : leads.length, direction: "up-good" },
      {
        label: "Qualified",
        match: (l) => l.score_band === "qualified" || l.score_band === "high",
        total: leads.filter((l) => l.score_band === "qualified" || l.score_band === "high").length,
        direction: "up-good",
      },
      {
        label: "Needs review",
        match: (l) => l.approval_status === "pending",
        total: leads.filter((l) => l.approval_status === "pending").length,
        direction: "neutral",
      },
      {
        label: "Synced to HubSpot",
        match: (l) => l.pipeline_status === "synced",
        total: usage ? usage.total_crm_syncs : leads.filter((l) => l.pipeline_status === "synced").length,
        direction: "up-good",
      },
    ];

    const kpiList: Kpi[] = defs.map((d) => ({
      label: d.label,
      value: d.total,
      current: leads.filter((l) => d.match(l) && inPeriod(l)).length,
      previous: leads.filter((l) => d.match(l) && inPrevious(l)).length,
      direction: d.direction,
    }));

    const points: ChartPoint[] = Array.from({ length: days }).map((_, i) => {
      const dayStart = periodStart + i * DAY_MS;
      const prevDayStart = dayStart - days * DAY_MS;
      const onDay = (start: number) => leads.filter((l) => startOfDay(new Date(l.created_at)) === start).length;
      return {
        label: new Date(dayStart).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        value: onDay(dayStart),
        previous: onDay(prevDayStart),
      };
    });

    return { kpis: kpiList, chartPoints: points };
  }, [leads, usage, days]);

  const recentLeads = useMemo(
    () => [...leads].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, 6),
    [leads]
  );
  const activeRuns = runs.filter((r) => r.status === "running" || r.status === "pending");

  const quotaRows = usage
    ? [
        {
          label: "Leads this month",
          used: usage.monthly_leads?.used ?? usage.quotas?.leads_monthly?.used ?? 0,
          limit: usage.monthly_leads?.limit ?? usage.quotas?.leads_monthly?.limit ?? 100,
        },
        {
          label: "Contact reveals today",
          used: usage.daily_contact_reveals?.used ?? usage.quotas?.contact_reveals_daily?.used ?? 0,
          limit: usage.daily_contact_reveals?.limit ?? usage.quotas?.contact_reveals_daily?.limit ?? 100,
        },
        {
          label: "Runs in progress",
          used: usage.concurrent_runs?.active ?? usage.concurrent_runs?.used ?? usage.quotas?.concurrent_runs?.active ?? 0,
          limit: usage.concurrent_runs?.limit ?? usage.quotas?.concurrent_runs?.limit ?? 2,
        },
      ]
    : [];

  if (isLoading && leads.length === 0 && !usage) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <DashboardSkeleton />
      </>
    );
  }

  if (error && !usage && leads.length === 0) {
    return <ErrorState title="The dashboard isn't available" message={error} onRetry={fetchDashboardData} />;
  }

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={isClientViewer ? "Approved leads shared with your team." : "Pipeline activity across sourcing, scoring and approvals."}
        actions={
          <>
            <div className="w-40">
              <Select value={rangeDays} onValueChange={setRangeDays} options={RANGE_OPTIONS} aria-label="Date range" />
            </div>
            <Button variant="secondary" onClick={fetchDashboardData} isLoading={isLoading}>
              {!isLoading && <RefreshCw className="h-4 w-4" strokeWidth={1.5} />}
              Refresh
            </Button>
            {!isClientViewer && (
              <Button onClick={() => router.push("/searches/new")}>
                <Search className="h-4 w-4" strokeWidth={1.5} />
                New search
              </Button>
            )}
          </>
        }
      />

      {!isClientViewer && pendingAccessRequests.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3">
          <p className="text-sm text-fg">
            <span className="font-medium">
              {pendingAccessRequests.length} access {pendingAccessRequests.length === 1 ? "request needs" : "requests need"} review
            </span>
            <span className="text-fg-secondary"> before those people can sign in.</span>
          </p>
          <Link href="/admin">
            <Button variant="secondary" size="sm">
              Review requests <ArrowRight className="h-4 w-4" strokeWidth={1.5} />
            </Button>
          </Link>
        </div>
      )}

      <motion.div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        variants={STAGGER_CONTAINER}
        initial={reduceMotion ? false : "hidden"}
        animate="show"
      >
        {kpis.map((kpi) => (
          <motion.div key={kpi.label} variants={STAGGER_ITEM}>
            <Card className="space-y-1.5">
              <p className="text-caption text-fg-secondary">{kpi.label}</p>
              <p className="text-kpi font-semibold text-fg">
                <CountUp value={kpi.value} format={formatNumber} />
              </p>
              <Delta kpi={kpi} days={days} />
            </Card>
          </motion.div>
        ))}
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card className="space-y-3">
          <h2 className="text-sm font-semibold text-fg">Leads added</h2>
          <LineChart points={chartPoints} unit="leads" previousLabel="previous period" />
          {leads.length >= LEAD_FETCH_LIMIT && (
            <p className="text-xs text-fg-tertiary">Based on your {LEAD_FETCH_LIMIT} most recent leads.</p>
          )}
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-fg">Recent leads</h2>
            <Link href="/leads" className="focus-ring rounded-control text-caption font-medium text-accent hover:text-accent-hover">
              View all
            </Link>
          </div>
          {recentLeads.length > 0 ? (
            <motion.ul
              className="divide-y divide-border"
              variants={STAGGER_CONTAINER}
              initial={reduceMotion ? false : "hidden"}
              animate="show"
            >
              {recentLeads.map((lead) => (
                <motion.li key={lead.id} variants={STAGGER_ITEM}>
                  <Link
                    href={`/leads/${lead.id}`}
                    className="focus-ring -mx-2 flex items-center justify-between gap-3 rounded-control px-2 py-2.5 transition-colors duration-fast hover:bg-surface-subtle"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-fg">{lead.company_name}</span>
                      <span className="block truncate text-xs text-fg-tertiary">
                        {lead.domain} · {formatRelative(lead.created_at)}
                      </span>
                    </span>
                    <StatusBadge tone={getBandTone(lead.score_band)}>{lead.score_band ?? "Not scored"}</StatusBadge>
                  </Link>
                </motion.li>
              ))}
            </motion.ul>
          ) : (
            <p className="py-6 text-center text-sm text-fg-secondary">
              No leads yet.{!isClientViewer && " Run a search to add some."}
            </p>
          )}
        </Card>
      </div>

      {!isClientViewer && (usage || runs.length > 0) && (
        <div className="grid gap-6 lg:grid-cols-2">
          {quotaRows.length > 0 && (
            <Card className="space-y-4">
              <h2 className="text-sm font-semibold text-fg">Usage</h2>
              <ul className="space-y-4">
                {quotaRows.map((row) => (
                  <li key={row.label} className="space-y-1.5">
                    <div className="flex items-baseline justify-between text-caption">
                      <span className="text-fg-secondary">{row.label}</span>
                      <span className="font-medium text-fg">
                        {formatNumber(row.used)} / {formatNumber(row.limit)}
                      </span>
                    </div>
                    <MeterBar value={(row.used / Math.max(1, row.limit)) * 100} strong={row.used < row.limit} danger={row.used >= row.limit} label={row.label} />
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <section className="space-y-3" aria-label="Recent runs">
            <h2 className="text-sm font-semibold text-fg">Search runs</h2>
            {activeRuns.length > 0 ? (
              activeRuns.map((run) => <RunProgressIndicator key={run.id} run={run} />)
            ) : runs.length > 0 ? (
              <Card className="p-0">
                <ul className="divide-y divide-border">
                  {runs.slice(0, 4).map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <StatusBadge tone={r.status === "completed" ? "success" : r.status === "failed" ? "danger" : "neutral"}>
                          {r.status}
                        </StatusBadge>
                        <span className="truncate text-caption text-fg-secondary">
                          {r.items_processed} of {r.items_total} processed
                        </span>
                      </div>
                      <span className="shrink-0 text-xs text-fg-tertiary">{formatRelative(r.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            ) : (
              <Card className="py-8 text-center text-sm text-fg-secondary">No search runs yet.</Card>
            )}
          </section>
        </div>
      )}
    </>
  );
}
