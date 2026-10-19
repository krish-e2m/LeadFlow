"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Mail, PenLine, RotateCw, X } from "lucide-react";
import { Lead, Score } from "@/types";
import { Sheet } from "@/components/Sheet";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/Badge";
import { Tabs } from "@/components/Tabs";
import { Skeleton } from "@/components/Skeleton";
import { Tooltip } from "@/components/Tooltip";
import { Modal } from "@/components/Modal";
import { Textarea } from "@/components/Input";
import { ContactsPanel } from "@/components/ContactsPanel";
import { DraftEditor } from "@/components/DraftEditor";
import { RevealContactDialog } from "@/components/RevealContactDialog";
import { MeterBar, Section } from "@/components/Meter";
import { SignalBreakdown } from "@/components/SignalBreakdown";
import { ErrorState } from "@/components/StateDisplay";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";
import { announceApproval } from "@/lib/autoDraft";
import { useDraftWatcher } from "@/lib/useDraftWatcher";
import { cn, formatDate, formatRelative, getBandTone, type Tone } from "@/lib/utils";

interface LeadSheetProps {
  leadId: string | null;
  onClose: () => void;
  /** Called after an approval or re-score so the list behind the sheet can refresh. */
  onLeadChanged?: () => void;
  isClientViewer: boolean;
}

const approvalTone: Record<string, Tone> = { approved: "success", rejected: "danger", pending: "warning" };


function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

const Fact: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 last:border-b-0">
    <dt className="text-caption text-fg-secondary">{label}</dt>
    <dd className="min-w-0 truncate text-right text-sm text-fg">{value}</dd>
  </div>
);

export const LeadSheet: React.FC<LeadSheetProps> = ({ leadId, onClose, onLeadChanged, isClientViewer }) => {
  const toast = useToast();
  const [lead, setLead] = useState<Lead | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState("overview");
  const [pendingAction, setPendingAction] = useState<"approved" | "rejected" | "rescore" | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [revealOpen, setRevealOpen] = useState(false);
  const [isDrafting, setIsDrafting] = useState(false);

  const load = useCallback(async (id: string) => {
    setIsLoading(true);
    setLoadError(null);
    try {
      setLead(await apiClient.get<Lead>(`/leads/${id}`));
    } catch (err: unknown) {
      setLead(null);
      setLoadError(errorMessage(err, "This lead couldn't be loaded. It may have been removed or you may not have access."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!leadId) return;
    setLead(null);
    setTab("overview");
    void load(leadId);
  }, [leadId, load]);

  /** Reload in place (no skeleton) after contacts or drafts change. */
  const refresh = useCallback(async () => {
    if (!leadId) return;
    try {
      setLead(await apiClient.get<Lead>(`/leads/${leadId}`));
    } catch {
      /* keep the current view; the next action will surface any error */
    }
  }, [leadId]);

  const draftWatcher = useDraftWatcher(leadId, {
    onReady: (updated) => {
      setLead(updated);
      toast.success("Email draft ready", `Review it in the Drafts tab for ${updated.company_name}.`);
      onLeadChanged?.();
    },
    onTimeout: () => toast.info("The draft is taking longer than usual", "Check the Drafts page in a minute."),
  });
  const stopDraftWatcher = draftWatcher.stop;

  useEffect(() => {
    stopDraftWatcher();
  }, [leadId, stopDraftWatcher]);

  const latestScore: Score | null = lead?.scores && lead.scores.length > 0 ? lead.scores[0] : null;

  const signalRatio = useMemo(() => {
    const meta = latestScore?.signal_details["_metadata"] as { available_signals_ratio?: string } | undefined;
    return meta?.available_signals_ratio ?? null;
  }, [latestScore]);

  const activity = useMemo(() => {
    if (!lead) return [];
    const events: { at: string; label: string }[] = [{ at: lead.created_at, label: "Sourced" }];
    if (latestScore) {
      const score = latestScore.overall_score !== null ? `${latestScore.overall_score.toFixed(1)}` : "n/a";
      events.push({ at: latestScore.created_at, label: `Scored ${score}${latestScore.score_band ? ` · ${latestScore.score_band}` : ""}` });
    }
    if (lead.approved_at) events.push({ at: lead.approved_at, label: `Marked ${lead.approval_status}` });
    (lead.drafts ?? []).forEach((d) => events.push({ at: d.created_at, label: `Draft generated · ${d.approval_status}` }));
    (lead.crm_syncs ?? []).forEach((s) => s.synced_at && events.push({ at: s.synced_at, label: `Synced to ${s.crm_provider}` }));
    return events.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  }, [lead, latestScore]);

  const submitApproval = async (status: "approved" | "rejected", reason?: string) => {
    if (!lead) return;
    setPendingAction(status);
    try {
      const updated = await apiClient.patch<Lead>(`/leads/${lead.id}/approval`, {
        approval_status: status,
        manual_override: Boolean(reason),
        override_reason: reason,
      });
      setLead((current) => (current ? { ...current, ...updated } : updated));
      if (status === "approved") {
        announceApproval(toast, updated.auto_draft, lead.company_name);
        if (updated.auto_draft === "queued") draftWatcher.start(lead.drafts?.length ?? 0);
      } else {
        toast.success("Lead rejected", lead.company_name);
      }
      onLeadChanged?.();
      setOverrideOpen(false);
      setOverrideReason("");
    } catch (err: unknown) {
      toast.error("Couldn't update approval", errorMessage(err, "Try again in a moment."));
    } finally {
      setPendingAction(null);
    }
  };

  const handleApprove = () => {
    if (!lead) return;
    const needsOverride =
      lead.score_band === "disqualified" ||
      lead.pipeline_status === "disqualified" ||
      lead.pipeline_status === "error" ||
      lead.approval_status === "rejected";
    if (needsOverride) {
      setOverrideOpen(true);
      return;
    }
    void submitApproval("approved");
  };

  const handleRescore = async () => {
    if (!lead) return;
    setPendingAction("rescore");
    try {
      // The endpoint returns the new Score record, not the lead, so reload the lead to show it.
      await apiClient.post<Score>(`/leads/${lead.id}/rescore`);
      await load(lead.id);
      toast.success("Score recalculated", lead.company_name);
      onLeadChanged?.();
    } catch (err: unknown) {
      toast.error("Couldn't re-score this lead", errorMessage(err, "Try again in a moment."));
    } finally {
      setPendingAction(null);
    }
  };

  const handleGenerateDraft = async () => {
    if (!lead) return;
    setIsDrafting(true);
    try {
      await apiClient.post(`/leads/${lead.id}/drafts`, {});
      await refresh();
      toast.success("Email draft ready", "Review and approve it before syncing.");
      onLeadChanged?.();
    } catch (err: unknown) {
      toast.error("Couldn't write the draft", errorMessage(err, "Try again in a moment."));
    } finally {
      setIsDrafting(false);
    }
  };

  const bandTone = getBandTone(lead?.score_band);
  const isApproved = lead?.approval_status === "approved";
  const contacts = lead?.contacts ?? [];
  const drafts = lead?.drafts ?? [];
  const tabs = [
    { value: "overview", label: "Overview" },
    { value: "contacts", label: "Contacts", count: contacts.length },
    { value: "drafts", label: "Drafts", count: drafts.length },
    { value: "signals", label: "Signals" },
    { value: "activity", label: "Activity" },
  ];
  const score = latestScore?.overall_score ?? null;

  const footer =
    lead && !isClientViewer ? (
      <div className="flex flex-wrap items-center gap-2">
        {isApproved ? (
          <Button disabled={pendingAction !== null} onClick={() => setRevealOpen(true)}>
            <Mail className="h-4 w-4" strokeWidth={1.5} />
            Reveal contact
          </Button>
        ) : (
          <Button isLoading={pendingAction === "approved"} disabled={pendingAction !== null} onClick={handleApprove}>
            <Check className="h-4 w-4" strokeWidth={1.5} />
            Approve
          </Button>
        )}
        <Button
          variant="secondary"
          isLoading={pendingAction === "rejected"}
          disabled={lead.approval_status === "rejected" || pendingAction !== null}
          onClick={() => void submitApproval("rejected")}
        >
          <X className="h-4 w-4" strokeWidth={1.5} />
          Reject
        </Button>
        <Button variant="ghost" isLoading={pendingAction === "rescore"} disabled={pendingAction !== null} onClick={handleRescore}>
          <RotateCw className="h-4 w-4" strokeWidth={1.5} />
          Re-score
        </Button>
      </div>
    ) : undefined;

  const headerActions = lead ? (
    <Tooltip content="Open full page">
      <Link
        href={`/leads/${lead.id}`}
        aria-label="Open full page"
        className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
      >
        <ArrowUpRight className="h-4 w-4" strokeWidth={1.5} />
      </Link>
    </Tooltip>
  ) : undefined;

  return (
    <>
      <Sheet
        open={leadId !== null}
        onOpenChange={(open) => !open && onClose()}
        title={lead?.company_name ?? "Lead"}
        description={lead?.domain}
        footer={footer}
        headerActions={headerActions}
      >
        {isLoading && !lead ? (
          <div className="space-y-4" role="status" aria-live="polite">
            <span className="sr-only">Loading lead…</span>
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-1 w-full" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : loadError ? (
          <ErrorState title="Couldn't load this lead" message={loadError} onRetry={leadId ? () => void load(leadId) : undefined} />
        ) : lead ? (
          <div className="space-y-6">
            <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 text-caption">
              <div className="flex items-center gap-2">
                <dt className="text-fg-tertiary">Band</dt>
                <dd>
                  <StatusBadge tone={bandTone}>{lead.score_band ?? "Not scored"}</StatusBadge>
                </dd>
              </div>
              <div className="flex items-center gap-2">
                <dt className="text-fg-tertiary">Stage</dt>
                <dd className="font-medium capitalize text-fg">{lead.pipeline_status}</dd>
              </div>
              <div className="flex items-center gap-2">
                <dt className="text-fg-tertiary">Approval</dt>
                <dd>
                  <StatusBadge tone={approvalTone[lead.approval_status] ?? "neutral"}>{lead.approval_status}</StatusBadge>
                </dd>
              </div>
            </dl>

            <Tabs value={tab} onValueChange={setTab} items={tabs} />

            {tab === "overview" && (
              <div className="space-y-6">
                <Section title="Score">
                  {latestScore && score !== null ? (
                    <div className="space-y-4">
                      <div className="flex items-end justify-between gap-4">
                        <p className="text-3xl font-semibold text-fg">
                          {score.toFixed(1)}
                          <span className="ml-1 text-sm font-normal text-fg-tertiary">/ 100</span>
                        </p>
                        {signalRatio && <p className="text-caption text-fg-secondary">{signalRatio} signals available</p>}
                      </div>
                      <MeterBar value={score} strong={lead.score_band === "qualified"} />
                      <div className="grid grid-cols-2 gap-4 pt-1">
                        {[
                          { label: "Website", value: latestScore.website_subscore },
                          { label: "Marketing", value: latestScore.marketing_subscore },
                        ].map((row) => (
                          <div key={row.label} className="space-y-1.5">
                            <div className="flex items-baseline justify-between text-caption">
                              <span className="text-fg-secondary">{row.label}</span>
                              <span className="font-medium text-fg">{row.value !== null ? row.value.toFixed(1) : "—"}</span>
                            </div>
                            <MeterBar value={row.value} strong={(row.value ?? 0) >= 50} />
                          </div>
                        ))}
                      </div>
                      {latestScore.explanation && (
                        <p className="whitespace-pre-line rounded-card bg-surface-subtle p-3 text-caption text-fg-secondary">
                          {latestScore.explanation}
                        </p>
                      )}
                    </div>
                  ) : lead.pipeline_status === "error" ? (
                    <p className="rounded-card bg-danger-subtle p-3 text-sm text-fg">
                      We couldn&apos;t audit this website, so it has no score.
                      {lead.error_reason && <span className="mt-1 block text-caption text-fg-secondary">{lead.error_reason}</span>}
                    </p>
                  ) : (
                    <p className="text-sm text-fg-secondary">This lead hasn't been scored yet.</p>
                  )}
                </Section>

                <Section title="Company">
                  <dl>
                    <Fact label="Domain" value={lead.domain} />
                    <Fact label="Industry" value={lead.industry || "—"} />
                    <Fact
                      label="Location"
                      value={[lead.city, lead.country].filter(Boolean).join(", ") || "—"}
                    />
                    <Fact
                      label="Employees"
                      value={lead.employee_count !== null ? new Intl.NumberFormat("en-US").format(lead.employee_count) : "—"}
                    />
                    <Fact
                      label="Added"
                      value={
                        <Tooltip content={formatDate(lead.created_at)}>
                          <span>{formatRelative(lead.created_at)}</span>
                        </Tooltip>
                      }
                    />
                  </dl>
                </Section>
              </div>
            )}

            {tab === "signals" && (
              <div>
                {latestScore ? (
                  <SignalBreakdown signals={latestScore.signal_details} compact />
                ) : (
                  <p className="text-sm text-fg-secondary">Signals appear here once the lead has been scored.</p>
                )}
              </div>
            )}

            {tab === "contacts" && (
              <ContactsPanel
                leadId={lead.id}
                contacts={contacts}
                canEdit={!isClientViewer}
                isApproved={isApproved}
                onContactsChanged={() => void refresh()}
              />
            )}

            {tab === "drafts" && (
              <div className="space-y-3">
                {draftWatcher.pending && (
                  <div className="space-y-2 rounded-card border border-border p-4" role="status" aria-live="polite">
                    <p className="text-sm font-medium text-fg">Writing an email draft…</p>
                    <p className="text-caption text-fg-secondary">This usually takes a few seconds. You can keep working.</p>
                    <Skeleton className="h-3 w-3/4" />
                    <Skeleton className="h-3 w-2/3" />
                  </div>
                )}

                {drafts.map((draft) =>
                  isClientViewer ? (
                    <div key={draft.id} className="space-y-1.5 rounded-card border border-border p-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="truncate text-sm font-medium text-fg">{draft.subject}</p>
                        <StatusBadge tone={approvalTone[draft.approval_status] ?? "neutral"}>{draft.approval_status}</StatusBadge>
                      </div>
                      <p className="line-clamp-3 text-caption text-fg-secondary">{draft.body}</p>
                    </div>
                  ) : (
                    <DraftEditor key={draft.id} draft={draft} onUpdate={() => void refresh()} />
                  )
                )}

                {drafts.length === 0 && !draftWatcher.pending && (
                  <p className="text-sm text-fg-secondary">
                    {isApproved ? "No draft yet." : "Approving this lead writes an email draft automatically."}
                  </p>
                )}

                {!isClientViewer && isApproved && !draftWatcher.pending && (
                  <Button
                    variant={drafts.length > 0 ? "ghost" : "secondary"}
                    className="w-full"
                    isLoading={isDrafting}
                    onClick={handleGenerateDraft}
                  >
                    {!isDrafting && <PenLine className="h-4 w-4" strokeWidth={1.5} />}
                    {drafts.length > 0 ? "Write another draft" : "Write draft"}
                  </Button>
                )}
              </div>
            )}

            {tab === "activity" && (
              <ol className="space-y-3">
                {activity.map((event, index) => (
                  <li key={`${event.at}-${index}`} className="flex items-start gap-3">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-fg-tertiary" aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm capitalize text-fg">{event.label}</p>
                      <Tooltip content={formatDate(event.at)}>
                        <p className="w-fit text-caption text-fg-tertiary">{formatRelative(event.at)}</p>
                      </Tooltip>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ) : null}
      </Sheet>

      <RevealContactDialog
        lead={revealOpen && lead ? lead : null}
        onClose={() => setRevealOpen(false)}
        onRevealed={() => {
          void refresh();
          onLeadChanged?.();
        }}
      />

      <Modal
        isOpen={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        title="Approve a disqualified lead?"
        description="This lead scored below the review threshold or was rejected. Approving it needs a reason, which is saved in the audit log."
      >
        <div className="space-y-4">
          <Textarea
            label="Reason for override"
            placeholder="Why should this lead move forward?"
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOverrideOpen(false)}>
              Cancel
            </Button>
            <Button
              isLoading={pendingAction === "approved"}
              disabled={!overrideReason.trim()}
              onClick={() => void submitApproval("approved", overrideReason.trim())}
            >
              Approve with override
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
};
