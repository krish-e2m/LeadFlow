"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Check, ExternalLink, Mail, RotateCw, PenLine, X } from "lucide-react";
import { Lead, Score, Contact, Draft } from "@/types";
import { Button } from "@/components/Button";
import { StatusBadge } from "@/components/Badge";
import { Card } from "@/components/Card";
import { ContactsPanel } from "@/components/ContactsPanel";
import { RevealContactDialog } from "@/components/RevealContactDialog";
import { DraftEditor } from "@/components/DraftEditor";
import { Modal } from "@/components/Modal";
import { MeterBar, Section } from "@/components/Meter";
import { PageHeader } from "@/components/PageHeader";
import { SignalBreakdown } from "@/components/SignalBreakdown";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/StateDisplay";
import { Textarea } from "@/components/Input";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";
import { announceApproval } from "@/lib/autoDraft";
import { useDraftWatcher } from "@/lib/useDraftWatcher";
import { useAuth } from "@/lib/auth-context";
import { formatNumber, getBandTone, type Tone } from "@/lib/utils";

const approvalTone: Record<string, Tone> = { approved: "success", rejected: "danger", pending: "warning" };

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function LeadDetailPage() {
  const params = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const leadId = params.id as string;

  const [lead, setLead] = useState<Lead | null>(null);
  const [latestScore, setLatestScore] = useState<Score | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isDrafting, setIsDrafting] = useState(false);
  const [isRescoring, setIsRescoring] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<"approved" | "rejected" | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [revealOpen, setRevealOpen] = useState(false);

  const isClientViewer = user?.role === "client_viewer";

  const loadLeadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Lead>(`/leads/${leadId}`);
      setLead(data);
      setLatestScore(data.scores && data.scores.length > 0 ? data.scores[0] : null);
      setContacts(data.contacts || []);
      setDrafts(data.drafts || []);
    } catch (err: unknown) {
      setError(errorMessage(err, "This lead couldn't be loaded. It may have been removed, or you may not have access."));
      setLead(null);
    } finally {
      setIsLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void loadLeadData();
  }, [loadLeadData]);

  /** Reload without the loading skeleton (after reveals, drafts and approvals). */
  const refreshLead = useCallback(async () => {
    try {
      const data = await apiClient.get<Lead>(`/leads/${leadId}`);
      setLead(data);
      setLatestScore(data.scores && data.scores.length > 0 ? data.scores[0] : null);
      setContacts(data.contacts || []);
      setDrafts(data.drafts || []);
    } catch {
      /* keep the current view */
    }
  }, [leadId]);

  const draftWatcher = useDraftWatcher(leadId, {
    onReady: (updated) => {
      setDrafts(updated.drafts || []);
      setLead((current) => (current ? { ...current, pipeline_status: updated.pipeline_status } : updated));
      toast.success("Email draft ready", "Review it under Outreach drafts.");
    },
    onTimeout: () => toast.info("The draft is taking longer than usual", "Refresh the page in a minute."),
  });

  const submitApproval = async (status: "approved" | "rejected", reason?: string) => {
    setPendingApproval(status);
    try {
      const updated = await apiClient.patch<Lead>(`/leads/${leadId}/approval`, {
        approval_status: status,
        manual_override: Boolean(reason),
        override_reason: reason,
      });
      setLead((current) => (current ? { ...current, ...updated } : updated));
      if (status === "approved") {
        announceApproval(toast, updated.auto_draft, lead?.company_name ?? "This lead");
        if (updated.auto_draft === "queued") draftWatcher.start(drafts.length);
      } else {
        toast.success("Lead rejected", lead?.company_name);
      }
      setOverrideOpen(false);
      setOverrideReason("");
    } catch (err: unknown) {
      toast.error("Couldn't update approval", errorMessage(err, "Try again in a moment."));
    } finally {
      setPendingApproval(null);
    }
  };

  const handleApprove = () => {
    const needsOverride =
      lead?.score_band === "disqualified" || lead?.pipeline_status === "disqualified" || lead?.approval_status === "rejected";
    if (needsOverride) {
      setOverrideOpen(true);
      return;
    }
    void submitApproval("approved");
  };

  const handleRescoreLead = async () => {
    setIsRescoring(true);
    try {
      // The endpoint returns the new Score record (not the lead), so reload the lead to show it.
      await apiClient.post(`/leads/${leadId}/rescore`);
      const refreshed = await apiClient.get<Lead>(`/leads/${leadId}`);
      setLead(refreshed);
      setLatestScore(refreshed.scores && refreshed.scores.length > 0 ? refreshed.scores[0] : null);
      toast.success("Score recalculated", refreshed.company_name);
    } catch (err: unknown) {
      toast.error("Couldn't re-score this lead", errorMessage(err, "Try again in a moment."));
    } finally {
      setIsRescoring(false);
    }
  };

  const handleGenerateDraft = async () => {
    setIsDrafting(true);
    setDraftError(null);
    try {
      const newDraft = await apiClient.post<Draft>(`/leads/${leadId}/drafts`, {});
      setDrafts((prev) => [newDraft, ...prev]);
      toast.success("Draft generated", "Review and approve it before syncing.");
    } catch (err: unknown) {
      setDraftError(errorMessage(err, "Couldn't generate a draft. Try again in a moment."));
    } finally {
      setIsDrafting(false);
    }
  };

  if (isLoading && !lead) {
    return (
      <div className="space-y-6" role="status" aria-live="polite">
        <span className="sr-only">Loading lead…</span>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="mx-auto max-w-xl space-y-4 py-12">
        <ErrorState title="Couldn't load this lead" message={error ?? "This lead doesn't exist in your organization."} onRetry={loadLeadData} />
        <div className="text-center">
          <Link href="/leads">
            <Button variant="ghost">
              <ArrowLeft className="h-4 w-4" strokeWidth={1.5} /> Back to leads
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const score = latestScore?.overall_score ?? null;
  const location = [lead.city, lead.country].filter(Boolean).join(", ");
  const facts = [
    lead.industry || "Industry unknown",
    location || "Location unknown",
    lead.employee_count ? `${formatNumber(lead.employee_count)} employees` : "Headcount unknown",
  ].join(" · ");

  return (
    <>
      <Link
        href="/leads"
        className="focus-ring inline-flex w-fit items-center gap-1.5 rounded-control text-caption font-medium text-fg-secondary transition-colors duration-fast hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.5} /> Leads
      </Link>

      <PageHeader
        title={lead.company_name}
        description={facts}
        actions={
          <>
            <a href={`https://${lead.domain}`} target="_blank" rel="noreferrer">
              <Button variant="secondary" tabIndex={-1}>
                {lead.domain}
                <ExternalLink className="h-4 w-4 text-fg-tertiary" strokeWidth={1.5} />
              </Button>
            </a>
            {!isClientViewer && (
              <>
                <Button variant="secondary" onClick={handleRescoreLead} isLoading={isRescoring} title="Re-evaluate the 22 signals with the active engine weights">
                  <RotateCw className="h-4 w-4" strokeWidth={1.5} />
                  Re-score
                </Button>
                {lead.approval_status !== "rejected" && (
                  <Button variant="secondary" onClick={() => void submitApproval("rejected")} isLoading={pendingApproval === "rejected"}>
                    <X className="h-4 w-4" strokeWidth={1.5} />
                    Reject
                  </Button>
                )}
                {lead.approval_status !== "approved" ? (
                  <Button onClick={handleApprove} isLoading={pendingApproval === "approved"}>
                    <Check className="h-4 w-4" strokeWidth={1.5} />
                    Approve lead
                  </Button>
                ) : (
                  <Button onClick={() => setRevealOpen(true)}>
                    <Mail className="h-4 w-4" strokeWidth={1.5} />
                    Reveal contact
                  </Button>
                )}
              </>
            )}
          </>
        }
      />

      {/* Score */}
      <Card className="space-y-5">
        <dl className="flex flex-wrap items-center gap-x-8 gap-y-2 text-caption">
          <div className="flex items-center gap-2">
            <dt className="text-fg-tertiary">Band</dt>
            <dd>
              <StatusBadge tone={getBandTone(lead.score_band)}>{lead.score_band ?? "Not scored"}</StatusBadge>
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

        {latestScore ? (
          <div className="grid gap-6 md:grid-cols-[1fr_1fr_1fr_1.4fr]">
            <div className="space-y-2">
              <p className="text-caption text-fg-secondary">Overall score</p>
              <p className="text-3xl font-semibold text-fg">
                {score !== null ? score.toFixed(1) : "—"}
                {score !== null && <span className="ml-1 text-sm font-normal text-fg-tertiary">/ 100</span>}
              </p>
              <MeterBar value={score} strong={lead.score_band === "qualified"} label="Overall score" />
            </div>
            {[
              { label: "Website", value: latestScore.website_subscore },
              { label: "Marketing", value: latestScore.marketing_subscore },
            ].map((row) => (
              <div key={row.label} className="space-y-2">
                <p className="text-caption text-fg-secondary">{row.label} subscore</p>
                <p className="text-xl font-semibold text-fg">{row.value !== null ? row.value.toFixed(1) : "—"}</p>
                <MeterBar value={row.value} strong={(row.value ?? 0) >= 50} label={`${row.label} subscore`} />
              </div>
            ))}
            <div className="space-y-1 md:border-l md:border-border md:pl-6">
              <p className="text-caption text-fg-secondary">Why this score</p>
              <p className="whitespace-pre-line text-caption text-fg">{latestScore.explanation || "Calculated across the verified signals."}</p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-fg-secondary">This lead hasn't been scored yet. Current stage: {lead.pipeline_status}.</p>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          {latestScore && latestScore.signal_details && Object.keys(latestScore.signal_details).length > 0 && (
            <Section title="Audit signals" description="Each signal shows the evidence the score is based on.">
              <SignalBreakdown signals={latestScore.signal_details} />
            </Section>
          )}

          {!isClientViewer && (
            <Section
              title="Outreach drafts"
              description="Drafts cite verified findings. Approve a lead before generating one."
              actions={
                <Button
                  onClick={handleGenerateDraft}
                  isLoading={isDrafting}
                  disabled={lead.approval_status !== "approved" || draftWatcher.pending}
                  title={lead.approval_status !== "approved" ? "Approve the lead first" : "Generate a draft"}
                >
                  <PenLine className="h-4 w-4" strokeWidth={1.5} />
                  Generate draft
                </Button>
              }
            >
              {lead.approval_status !== "approved" && (
                <p className="rounded-control bg-warning-subtle px-3 py-2 text-caption text-warning">
                  Approving this lead writes an email draft automatically.
                </p>
              )}
              {draftWatcher.pending && (
                <div className="space-y-2 rounded-card border border-border bg-surface p-4" role="status" aria-live="polite">
                  <p className="text-sm font-medium text-fg">Writing an email draft…</p>
                  <p className="text-caption text-fg-secondary">This usually takes a few seconds.</p>
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-3 w-2/3" />
                </div>
              )}
              {draftError && (
                <p role="alert" className="rounded-control bg-danger-subtle px-3 py-2 text-caption text-danger">
                  {draftError}
                </p>
              )}
              {drafts.length > 0 ? (
                <div className="space-y-3">
                  {drafts.map((d) => (
                    <DraftEditor
                      key={d.id}
                      draft={d}
                      onUpdate={(updated) => setDrafts((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))}
                    />
                  ))}
                </div>
              ) : (
                !draftWatcher.pending && <p className="text-sm text-fg-secondary">No drafts yet.</p>
              )}
            </Section>
          )}
        </div>

        <aside className="space-y-3">
          <Section title="Contacts" description="Emails and phone numbers stay hidden until you reveal them.">
            <ContactsPanel
              leadId={lead.id}
              contacts={contacts}
              canEdit={!isClientViewer}
              isApproved={lead.approval_status === "approved"}
              onContactsChanged={() => void refreshLead()}
            />
          </Section>
        </aside>
      </div>

      <RevealContactDialog
        lead={revealOpen ? lead : null}
        onClose={() => setRevealOpen(false)}
        onRevealed={() => void refreshLead()}
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
              isLoading={pendingApproval === "approved"}
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
}
