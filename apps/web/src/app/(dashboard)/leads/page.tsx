"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  Check,
  ChevronDown,
  Copy,
  Download,
  ListFilter,
  Mail,
  Rows3,
  RotateCw,
  Search,
  X,
} from "lucide-react";
import { ApprovalStatus, Lead } from "@/types";
import { Avatar } from "@/components/Brand";
import { Button } from "@/components/Button";
import { Checkbox } from "@/components/Checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/DropdownMenu";
import { EmptyState, ErrorState } from "@/components/StateDisplay";
import { LeadSheet } from "@/components/LeadSheet";
import { RevealContactDialog } from "@/components/RevealContactDialog";
import { PageHeader } from "@/components/PageHeader";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/Popover";
import { Select } from "@/components/Select";
import { StatusBadge } from "@/components/Badge";
import { Table, TableContainer, TableSkeletonRows, Td, Th } from "@/components/Table";
import { Tabs } from "@/components/Tabs";
import { useToast } from "@/components/Toast";
import { Tooltip } from "@/components/Tooltip";
import { apiClient } from "@/lib/api-client";
import { announceApproval } from "@/lib/autoDraft";
import { useAuth } from "@/lib/auth-context";
import {
  cn,
  describeBandChanges,
  formatDate,
  formatNumber,
  formatRelative,
  getBandTone,
  type BandChanges,
  type Tone,
} from "@/lib/utils";

const PAGE_SIZE = 100;
const CHECKBOX_COL_WIDTH = "44px";

const VIEW_TABS = [
  { value: "all", label: "All leads" },
  { value: "pending", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "archived", label: "Archived" },
];

const BAND_OPTIONS = [
  { value: "all", label: "All bands" },
  { value: "qualified", label: "Qualified" },
  { value: "review", label: "Review" },
  { value: "disqualified", label: "Disqualified" },
];

const SORT_OPTIONS = [
  { value: "score", label: "Highest score" },
  { value: "newest", label: "Newest" },
];

const approvalTone: Record<ApprovalStatus, Tone> = { approved: "success", rejected: "danger", pending: "warning" };

const SKELETON_COLUMNS = ["w-4", "w-48", "w-32", "w-10", "w-20", "w-20", "w-20", "w-16", "w-12"];

type BulkAction = "approve" | "reject" | "rescore" | "archive" | "unarchive";

const bulkVerb: Record<BulkAction, string> = {
  approve: "approved",
  reject: "rejected",
  rescore: "re-scored",
  archive: "archived",
  unarchive: "restored",
};

interface BulkResult {
  total_succeeded: number;
  total_failed: number;
  drafts_queued?: number;
  band_changes?: BandChanges | null;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

function LeadsPipeline() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const reduceMotion = useReducedMotion();

  const isClientViewer = user?.role === "client_viewer";
  const initialQuery = searchParams.get("q") ?? "";

  const [leads, setLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery);
  const [view, setView] = useState("all");
  const [band, setBand] = useState("all");
  const [sort, setSort] = useState("score");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [compact, setCompact] = useState(false);
  const [openLeadId, setOpenLeadId] = useState<string | null>(null);
  const [flashId, setFlashId] = useState<string | null>(null);
  const [isBulkRunning, setIsBulkRunning] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [revealLead, setRevealLead] = useState<Lead | null>(null);

  // Follow ?q= so the command palette can search from anywhere.
  const urlQuery = searchParams.get("q");
  useEffect(() => {
    if (urlQuery !== null) {
      setSearchInput(urlQuery);
      setQuery(urlQuery);
    }
  }, [urlQuery]);

  // Debounce typing so each keystroke doesn't hit the API.
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const isArchivedView = !isClientViewer && view === "archived";

  const filterParams = useCallback(() => {
    const params = new URLSearchParams();
    if (band !== "all") params.append("score_band", band);
    if (!isClientViewer && view === "archived") params.append("archived", "true");
    else if (!isClientViewer && view !== "all") params.append("approval_status", view);
    if (query) params.append("search", query);
    return params;
  }, [band, view, query, isClientViewer]);

  const fetchLeads = useCallback(
    async (silent = false) => {
      if (!silent) {
        setIsLoading(true);
        setSelectedIds([]);
      }
      setError(null);
      try {
        const params = filterParams();
        params.append("limit", String(PAGE_SIZE));
        params.append("sort", sort);
        setLeads(await apiClient.get<Lead[]>(`/leads?${params.toString()}`));
      } catch (err: unknown) {
        setError(errorMessage(err, "The leads request failed. Check your connection and try again."));
        setLeads([]);
      } finally {
        setIsLoading(false);
      }
    },
    [filterParams, sort]
  );

  useEffect(() => {
    void fetchLeads();
  }, [fetchLeads]);

  const hasActiveFilters = band !== "all" || query !== "" || view !== "all";

  // Drop ?q= once the user changes the search themselves, so the command palette can set it again later.
  const dropUrlQuery = useCallback(() => {
    if (searchParams.get("q") !== null) router.replace("/leads", { scroll: false });
  }, [router, searchParams]);

  const clearSearch = () => {
    setSearchInput("");
    setQuery("");
    dropUrlQuery();
  };

  const clearFilters = () => {
    setBand("all");
    setView("all");
    clearSearch();
  };

  const handleQuickApproval = async (lead: Lead, status: ApprovalStatus) => {
    try {
      const updated = await apiClient.patch<Lead>(`/leads/${lead.id}/approval`, { approval_status: status });
      if (status === "approved") announceApproval(toast, updated.auto_draft, lead.company_name);
      else toast.success("Lead rejected", lead.company_name);
      setFlashId(lead.id);
      void fetchLeads(true);
    } catch (err: unknown) {
      toast.error("Couldn't update approval", errorMessage(err, "Try again in a moment."));
    }
  };

  const handleExport = async (format: "csv" | "json") => {
    setIsExporting(true);
    try {
      const params = filterParams();
      params.delete("archived");
      if (isArchivedView) params.append("include_archived", "true");
      params.append("format", format);
      await apiClient.downloadFile(`/leads/export?${params.toString()}`, `leads_export.${format}`);
      toast.success(`Export ready`, `${format.toUpperCase()} file downloaded.`);
    } catch (err: unknown) {
      toast.error(`Couldn't export ${format.toUpperCase()}`, errorMessage(err, "Try again in a moment."));
    } finally {
      setIsExporting(false);
    }
  };

  const handleBulkAction = async (action: BulkAction) => {
    if (selectedIds.length === 0) return;
    setIsBulkRunning(true);
    try {
      const res = await apiClient.post<BulkResult>("/leads/bulk", {
        action,
        lead_ids: selectedIds,
      });
      if (res.total_failed > 0) {
        toast.error(
          `${res.total_failed} lead${res.total_failed === 1 ? "" : "s"} couldn't be ${bulkVerb[action]}`,
          `${res.total_succeeded} succeeded. Disqualified leads can't be bulk-approved; open them to approve with a reason.`
        );
      } else {
        toast.success(
          `${res.total_succeeded} lead${res.total_succeeded === 1 ? "" : "s"} ${bulkVerb[action]}`,
          action === "rescore"
            ? describeBandChanges(res.band_changes)
            : res.drafts_queued
              ? `Writing ${res.drafts_queued} email draft${res.drafts_queued === 1 ? "" : "s"}. They appear in Drafts shortly.`
              : undefined
        );
      }
      setSelectedIds([]);
      void fetchLeads(true);
    } catch (err: unknown) {
      toast.error("Bulk action failed", errorMessage(err, "Try again in a moment."));
    } finally {
      setIsBulkRunning(false);
    }
  };

  const copyDomain = async (domain: string) => {
    try {
      await navigator.clipboard.writeText(domain);
      toast.success("Domain copied", domain);
    } catch {
      toast.error("Couldn't copy", "Your browser blocked clipboard access.");
    }
  };

  const allSelected = leads.length > 0 && selectedIds.length === leads.length;
  const someSelected = selectedIds.length > 0 && !allSelected;

  const toggleAll = () => setSelectedIds(allSelected ? [] : leads.map((l) => l.id));
  const toggleOne = (id: string) =>
    setSelectedIds((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));

  const companyLeft = isClientViewer ? "0px" : CHECKBOX_COL_WIDTH;
  const skeletonColumns = useMemo(
    () => (isClientViewer ? SKELETON_COLUMNS.slice(1, 8) : SKELETON_COLUMNS),
    [isClientViewer]
  );

  const chips: { key: string; label: string; onRemove: () => void }[] = [];
  if (query) chips.push({ key: "q", label: `Search: ${query}`, onRemove: clearSearch });
  if (band !== "all") {
    const label = BAND_OPTIONS.find((o) => o.value === band)?.label ?? band;
    chips.push({ key: "band", label: `Score: ${label}`, onRemove: () => setBand("all") });
  }

  return (
    <>
      <PageHeader
        title="Leads"
        description={
          isClientViewer
            ? "Approved leads shared with your team."
            : "Companies scored on 22 audit signals. Approve a lead before any credits are spent."
        }
        actions={
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="secondary" disabled={isExporting || leads.length === 0} isLoading={isExporting}>
                  <Download className="h-4 w-4" strokeWidth={1.5} />
                  Export
                  <ChevronDown className="h-4 w-4 text-fg-tertiary" strokeWidth={1.5} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[160px]">
                <DropdownMenuItem onSelect={() => void handleExport("csv")}>Export CSV</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void handleExport("json")}>Export JSON</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {!isClientViewer && (
              <Button onClick={() => router.push("/searches/new")}>
                <Search className="h-4 w-4" strokeWidth={1.5} />
                New search
              </Button>
            )}
          </>
        }
      />

      {!isClientViewer && <Tabs value={view} onValueChange={setView} items={VIEW_TABS} />}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-tertiary"
            strokeWidth={1.5}
          />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value);
              dropUrlQuery();
            }}
            placeholder="Search company or domain"
            aria-label="Search leads by company or domain"
            className="focus-ring h-control w-full rounded-control border border-border-strong bg-surface pl-8 pr-3 text-sm text-fg transition-[border-color] duration-fast placeholder:text-fg-tertiary hover:border-fg-tertiary"
          />
        </div>

        <Popover>
          <PopoverTrigger asChild>
            <Button variant="secondary">
              <ListFilter className="h-4 w-4" strokeWidth={1.5} />
              Filter
            </Button>
          </PopoverTrigger>
          <PopoverContent>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="block text-caption font-medium text-fg">Score band</label>
                <Select value={band} onValueChange={setBand} options={BAND_OPTIONS} aria-label="Score band" />
              </div>
              <div className="space-y-1.5">
                <label className="block text-caption font-medium text-fg">Sort by</label>
                <Select value={sort} onValueChange={setSort} options={SORT_OPTIONS} aria-label="Sort leads" />
              </div>
              {hasActiveFilters && (
                <Button variant="ghost" size="sm" className="w-full" onClick={clearFilters}>
                  Clear all filters
                </Button>
              )}
            </div>
          </PopoverContent>
        </Popover>

        {chips.map((chip) => (
          <span
            key={chip.key}
            className="inline-flex h-control-sm items-center gap-1 rounded-control border border-border bg-surface-subtle pl-2.5 pr-1 text-caption text-fg"
          >
            <span className="max-w-[14rem] truncate">{chip.label}</span>
            <button
              type="button"
              onClick={chip.onRemove}
              aria-label={`Remove filter: ${chip.label}`}
              className="focus-ring inline-flex h-5 w-5 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-muted hover:text-fg"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} />
            </button>
          </span>
        ))}

        <div className="ml-auto flex items-center gap-1">
          <span className="mr-2 text-caption text-fg-secondary" aria-live="polite">
            {isLoading ? "Loading…" : `${formatNumber(leads.length)} ${leads.length === 1 ? "lead" : "leads"}`}
          </span>
          <Tooltip content={compact ? "Comfortable rows" : "Compact rows"}>
            <button
              type="button"
              onClick={() => setCompact((c) => !c)}
              aria-label="Toggle compact rows"
              aria-pressed={compact}
              className={cn(
                "focus-ring inline-flex h-control-sm w-8 items-center justify-center rounded-control transition-colors duration-fast hover:bg-surface-subtle",
                compact ? "bg-surface-muted text-fg" : "text-fg-secondary"
              )}
            >
              <Rows3 className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </Tooltip>
          <Tooltip content="Refresh">
            <button
              type="button"
              onClick={() => void fetchLeads()}
              aria-label="Refresh leads"
              className="focus-ring inline-flex h-control-sm w-8 items-center justify-center rounded-control text-fg-secondary transition-colors duration-fast hover:bg-surface-subtle"
            >
              <RotateCw className={cn("h-4 w-4", isLoading && "animate-spin")} strokeWidth={1.5} />
            </button>
          </Tooltip>
        </div>
      </div>

      {/* Table */}
      {error ? (
        <ErrorState title="Couldn't load leads" message={error} onRetry={() => void fetchLeads()} />
      ) : !isLoading && leads.length === 0 ? (
        isArchivedView && !query && band === "all" ? (
          <EmptyState title="No archived leads" description="Leads you archive appear here and can be restored." />
        ) : hasActiveFilters ? (
          <EmptyState
            title="No leads match these filters"
            description="Try a different search or clear the filters."
            actionLabel="Clear filters"
            onAction={clearFilters}
          />
        ) : isClientViewer ? (
          <EmptyState
            title="No approved leads yet"
            description="Leads appear here once your team has reviewed and approved them."
          />
        ) : (
          <EmptyState
            title="No leads yet"
            description="Run a search to find companies and score them."
            actionLabel="Run your first search"
            onAction={() => router.push("/searches/new")}
          />
        )
      ) : (
        <>
          {/* Phone: card list */}
          <ul className="space-y-2 sm:hidden" aria-label="Leads">
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => <li key={i} className="skeleton h-16" aria-hidden="true" />)
              : leads.map((lead) => (
                  <li key={lead.id}>
                    <button
                      type="button"
                      onClick={() => setOpenLeadId(lead.id)}
                      className="focus-ring flex w-full items-center gap-3 rounded-card border border-border bg-surface p-3 text-left"
                    >
                      <Avatar name={lead.company_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-fg">{lead.company_name}</span>
                        <span className="block truncate text-caption text-fg-tertiary">{lead.domain}</span>
                      </span>
                      <span className="flex flex-col items-end gap-1">
                        <StatusBadge tone={getBandTone(lead.score_band)}>{lead.score_band ?? "Not scored"}</StatusBadge>
                        <StatusBadge tone={approvalTone[lead.approval_status]}>{lead.approval_status}</StatusBadge>
                      </span>
                    </button>
                  </li>
                ))}
          </ul>

          {/* Tablet and up: table */}
          <TableContainer className="hidden max-h-[calc(100dvh-var(--topbar-height)-17rem)] sm:block">
            <Table aria-label="Leads" aria-busy={isLoading}>
              <thead>
                <tr>
                  {!isClientViewer && (
                    <Th stickyLeft="0px" className="w-11 px-3">
                      <Checkbox
                        checked={someSelected ? "indeterminate" : allSelected}
                        onCheckedChange={toggleAll}
                        aria-label="Select all leads"
                        disabled={isLoading}
                      />
                    </Th>
                  )}
                  <Th stickyLeft={companyLeft} className="min-w-[260px]">Company</Th>
                  <Th>Industry and location</Th>
                  <Th className="text-right">Score</Th>
                  <Th>Score band</Th>
                  <Th>Stage</Th>
                  <Th>Approval</Th>
                  <Th>Added</Th>
                  {!isClientViewer && <Th className="w-36"><span className="sr-only">Quick actions</span></Th>}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <TableSkeletonRows columns={skeletonColumns} compact={compact} />
                ) : (
                  leads.map((lead) => {
                    const selected = selectedIds.includes(lead.id);
                    const location = [lead.city, lead.country].filter(Boolean).join(", ");
                    return (
                      <tr
                        key={lead.id}
                        onClick={(event) => {
                          if ((event.target as HTMLElement).closest("button,a,input,[role=checkbox]")) return;
                          setOpenLeadId(lead.id);
                        }}
                        onAnimationEnd={() => flashId === lead.id && setFlashId(null)}
                        className={cn(
                          "group cursor-pointer transition-colors duration-fast",
                          selected ? "bg-accent-subtle" : "bg-surface hover:bg-surface-subtle",
                          flashId === lead.id && "row-flash"
                        )}
                      >
                        {!isClientViewer && (
                          <Td stickyLeft="0px" compact={compact} className="w-11">
                            <Checkbox
                              checked={selected}
                              onCheckedChange={() => toggleOne(lead.id)}
                              aria-label={`Select ${lead.company_name}`}
                            />
                          </Td>
                        )}
                        <Td stickyLeft={companyLeft} compact={compact} className="max-w-[320px]">
                          <div className="flex items-center gap-3">
                            <Avatar name={lead.company_name} size="sm" />
                            <div className="min-w-0">
                              <Tooltip content={lead.company_name}>
                                <button
                                  type="button"
                                  onClick={() => setOpenLeadId(lead.id)}
                                  className="focus-ring block max-w-full truncate rounded-control text-left text-sm font-medium text-fg hover:underline"
                                >
                                  {lead.company_name}
                                </button>
                              </Tooltip>
                              <div className="flex items-center gap-1">
                                <Tooltip content={lead.domain}>
                                  <span className="block max-w-[200px] truncate text-caption text-fg-tertiary">{lead.domain}</span>
                                </Tooltip>
                                <button
                                  type="button"
                                  onClick={() => void copyDomain(lead.domain)}
                                  aria-label={`Copy ${lead.domain}`}
                                  className="focus-ring inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-control text-fg-tertiary opacity-0 transition-opacity duration-fast hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
                                >
                                  <Copy className="h-3.5 w-3.5" strokeWidth={1.5} />
                                </button>
                              </div>
                            </div>
                          </div>
                        </Td>
                        <Td compact={compact} className="max-w-[220px]">
                          <Tooltip content={[lead.industry, location].filter(Boolean).join(" · ")}>
                            <div className="min-w-0">
                              <p className="truncate text-sm text-fg">{lead.industry || "—"}</p>
                              {!compact && <p className="truncate text-caption text-fg-tertiary">{location || "—"}</p>}
                            </div>
                          </Tooltip>
                        </Td>
                        <Td compact={compact} className="text-right">
                          <span className="text-sm font-medium tabular-nums text-fg">
                            {typeof lead.overall_score === "number" ? Math.round(lead.overall_score) : "—"}
                          </span>
                        </Td>
                        <Td compact={compact}>
                          <StatusBadge tone={getBandTone(lead.score_band)}>{lead.score_band ?? "Not scored"}</StatusBadge>
                        </Td>
                        <Td compact={compact}>
                          {lead.pipeline_status === "error" ? (
                            <Tooltip content={lead.error_reason || "This website couldn't be audited."}>
                              <span className="whitespace-nowrap text-caption font-medium text-danger">Error</span>
                            </Tooltip>
                          ) : (
                            <span className="whitespace-nowrap text-caption capitalize text-fg-secondary">{lead.pipeline_status}</span>
                          )}
                        </Td>
                        <Td compact={compact}>
                          <StatusBadge tone={approvalTone[lead.approval_status]}>{lead.approval_status}</StatusBadge>
                        </Td>
                        <Td compact={compact}>
                          <Tooltip content={formatDate(lead.created_at)}>
                            <span className="whitespace-nowrap text-caption text-fg-secondary">{formatRelative(lead.created_at)}</span>
                          </Tooltip>
                        </Td>
                        {!isClientViewer && (
                          <Td compact={compact} className="w-36">
                            {!isArchivedView && lead.approval_status === "approved" && (
                              <div className="flex justify-end">
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() => setRevealLead(lead)}
                                  aria-label={`Reveal a contact at ${lead.company_name}`}
                                >
                                  <Mail className="h-4 w-4" strokeWidth={1.5} />
                                  Reveal contact
                                </Button>
                              </div>
                            )}
                            {!isArchivedView && lead.approval_status === "pending" && (
                              <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity duration-fast focus-within:opacity-100 group-hover:opacity-100">
                                <Tooltip
                                  content={
                                    lead.pipeline_status === "error"
                                      ? "Not audited: open the lead to approve with a reason"
                                      : lead.score_band === "disqualified"
                                        ? "Disqualified: open the lead to approve with a reason"
                                        : "Approve"
                                  }
                                >
                                  <span>
                                    <button
                                      type="button"
                                      disabled={lead.score_band === "disqualified" || lead.pipeline_status === "error"}
                                      onClick={() => void handleQuickApproval(lead, "approved")}
                                      aria-label={`Approve ${lead.company_name}`}
                                      className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-control text-fg-secondary transition-colors duration-fast hover:bg-success-subtle hover:text-success disabled:pointer-events-none disabled:opacity-40"
                                    >
                                      <Check className="h-4 w-4" strokeWidth={1.5} />
                                    </button>
                                  </span>
                                </Tooltip>
                                <Tooltip content="Reject">
                                  <button
                                    type="button"
                                    onClick={() => void handleQuickApproval(lead, "rejected")}
                                    aria-label={`Reject ${lead.company_name}`}
                                    className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-control text-fg-secondary transition-colors duration-fast hover:bg-danger-subtle hover:text-danger"
                                  >
                                    <X className="h-4 w-4" strokeWidth={1.5} />
                                  </button>
                                </Tooltip>
                              </div>
                            )}
                          </Td>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </Table>
          </TableContainer>

          {!isLoading && leads.length >= PAGE_SIZE && (
            <p className="text-caption text-fg-tertiary">
              Showing the first {PAGE_SIZE} leads. Use search or filters to narrow the list.
            </p>
          )}
        </>
      )}

      {/* Floating bulk action bar */}
      <div className="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4">
        <AnimatePresence>
          {!isClientViewer && selectedIds.length > 0 && (
            <motion.div
              role="toolbar"
              aria-label="Bulk actions"
              className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface px-3 py-2 shadow-pop"
              initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
              animate={{ opacity: 1, y: 0, transition: { duration: 0.2, ease: [0.16, 1, 0.3, 1] } }}
              exit={{ opacity: 0, y: reduceMotion ? 0 : 8, transition: { duration: 0.14, ease: [0.4, 0, 1, 1] } }}
            >
              <span className="px-1 text-sm font-medium text-fg">{selectedIds.length} selected</span>
              <span className="h-5 w-px bg-border" aria-hidden="true" />
              {isArchivedView ? (
                <Button size="sm" disabled={isBulkRunning} onClick={() => void handleBulkAction("unarchive")}>
                  Restore
                </Button>
              ) : (
                <>
                  <Button size="sm" disabled={isBulkRunning} onClick={() => void handleBulkAction("approve")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="secondary" disabled={isBulkRunning} onClick={() => void handleBulkAction("reject")}>
                    Reject
                  </Button>
                  <Button size="sm" variant="ghost" disabled={isBulkRunning} onClick={() => void handleBulkAction("rescore")}>
                    Re-score
                  </Button>
                  <Button size="sm" variant="ghost" disabled={isBulkRunning} onClick={() => void handleBulkAction("archive")}>
                    Archive
                  </Button>
                </>
              )}
              <Tooltip content="Clear selection">
                <button
                  type="button"
                  onClick={() => setSelectedIds([])}
                  aria-label="Clear selection"
                  className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
                >
                  <X className="h-4 w-4" strokeWidth={1.5} />
                </button>
              </Tooltip>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <RevealContactDialog
        lead={revealLead}
        onClose={() => setRevealLead(null)}
        onRevealed={() => {
          if (revealLead) setFlashId(revealLead.id);
          void fetchLeads(true);
        }}
      />

      <LeadSheet
        leadId={openLeadId}
        onClose={() => setOpenLeadId(null)}
        isClientViewer={Boolean(isClientViewer)}
        onLeadChanged={() => {
          if (openLeadId) setFlashId(openLeadId);
          void fetchLeads(true);
        }}
      />
    </>
  );
}

export default function LeadsPage() {
  return (
    <Suspense fallback={null}>
      <LeadsPipeline />
    </Suspense>
  );
}
