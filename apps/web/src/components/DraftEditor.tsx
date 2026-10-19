"use client";

import React, { useState } from "react";
import { Check, ExternalLink, Mail, Pencil, Send, X } from "lucide-react";
import { CrmSync, Draft } from "@/types";
import { StatusBadge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Textarea } from "@/components/Input";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";
import type { Tone } from "@/lib/utils";

interface DraftEditorProps {
  draft: Draft;
  onUpdate?: (updatedDraft: Draft) => void;
}

const approvalTone: Record<Draft["approval_status"], Tone> = { approved: "success", rejected: "danger", pending: "warning" };

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export const DraftEditor: React.FC<DraftEditorProps> = ({ draft: initialDraft, onUpdate }) => {
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [isEditing, setIsEditing] = useState(false);
  const [subject, setSubject] = useState(initialDraft.subject);
  const [body, setBody] = useState(initialDraft.body);
  const [isLoading, setIsLoading] = useState(false);
  const [isSendingEmail, setIsSendingEmail] = useState(false);
  const [sentRecipient, setSentRecipient] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [synced, setSynced] = useState<CrmSync | null>(null);

  const handleApproval = async (status: "approved" | "rejected") => {
    setIsLoading(true);
    setError(null);
    try {
      const updated = await apiClient.patch<Draft>(`/drafts/${draft.id}/approval`, { approval_status: status });
      setDraft(updated);
      onUpdate?.(updated);
      toast.success(status === "approved" ? "Draft approved" : "Draft rejected");
    } catch (err: unknown) {
      setError(errorMessage(err, "Couldn't update the draft approval. Try again in a moment."));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveEdit = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const updated = await apiClient.patch<Draft>(`/drafts/${draft.id}`, { subject, body });
      setDraft(updated);
      setIsEditing(false);
      onUpdate?.(updated);
      toast.success("Draft saved");
    } catch (err: unknown) {
      setError(errorMessage(err, "Couldn't save your edits. Try again in a moment."));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSyncToHubspot = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiClient.post<CrmSync>(`/leads/${draft.lead_id}/sync-crm`, {
        draft_id: draft.id,
        crm_provider: "hubspot",
      });
      setSynced(result);
      if (result.already_synced) {
        toast.info("Already in HubSpot", "This draft was synced before, so nothing was added again.");
      } else {
        toast.success("Synced to HubSpot", "The company, contact and draft note are in your CRM.");
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "HubSpot sync failed. Check the HubSpot connection and try again."));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendEmail = async () => {
    setIsSendingEmail(true);
    setError(null);
    try {
      const result = await apiClient.post<{ draft_id: string; recipient: string; message_id: string; status: string }>(
        `/drafts/${draft.id}/send`
      );
      setSentRecipient(result.recipient);
      toast.success("Outreach Email Sent", `Delivered to ${result.recipient} via Resend.`);
    } catch (err: unknown) {
      setError(errorMessage(err, "Failed to send email via Resend. Check your Resend configuration and contact email."));
    } finally {
      setIsSendingEmail(false);
    }
  };

  const isApproved = draft.approval_status === "approved";

  return (
    <div className="space-y-4 rounded-card border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <StatusBadge tone={approvalTone[draft.approval_status]}>{draft.approval_status}</StatusBadge>
          <span className="truncate font-mono text-xs text-fg-tertiary">{draft.model_used}</span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setIsEditing((v) => !v)}>
          <Pencil className="h-4 w-4" strokeWidth={1.5} />
          {isEditing ? "Cancel" : "Edit"}
        </Button>
      </div>

      {error && (
        <p role="alert" className="rounded-control bg-danger-subtle px-3 py-2 text-caption text-danger">
          {error}
        </p>
      )}

      {isEditing ? (
        <div className="space-y-3">
          <Input label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <Textarea label="Body" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          <Button onClick={handleSaveEdit} isLoading={isLoading}>
            Save changes
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div>
            <p className="text-xs text-fg-secondary">Subject</p>
            <p className="mt-0.5 text-sm font-medium text-fg">{draft.subject}</p>
          </div>
          <div>
            <p className="text-xs text-fg-secondary">Body</p>
            <p className="mt-0.5 whitespace-pre-wrap text-sm text-fg">{draft.body}</p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <div className="flex items-center gap-2">
          {!isApproved && (
            <Button onClick={() => handleApproval("approved")} isLoading={isLoading}>
              <Check className="h-4 w-4" strokeWidth={1.5} />
              Approve draft
            </Button>
          )}
          {draft.approval_status !== "rejected" && (
            <Button variant="secondary" onClick={() => handleApproval("rejected")} isLoading={isLoading}>
              <X className="h-4 w-4" strokeWidth={1.5} />
              Reject
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {synced && (synced.crm_contact_url || synced.crm_company_url) && (
            <a
              href={(synced.crm_contact_url || synced.crm_company_url) as string}
              target="_blank"
              rel="noreferrer"
              className="focus-ring inline-flex items-center gap-1 rounded-control text-caption font-medium text-accent hover:text-accent-hover"
            >
              Open in HubSpot <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.5} />
            </a>
          )}
          <Button
            variant="secondary"
            onClick={handleSyncToHubspot}
            isLoading={isLoading}
            disabled={!isApproved}
            title={isApproved ? "Sync to HubSpot" : "Approve the draft before syncing"}
          >
            <Send className="h-4 w-4" strokeWidth={1.5} />
            {synced ? "Synced" : "Sync to HubSpot"}
          </Button>

          <Button
            variant="primary"
            onClick={handleSendEmail}
            isLoading={isSendingEmail}
            disabled={!isApproved}
            title={isApproved ? "Send outreach email via Resend" : "Approve the draft before sending"}
          >
            <Mail className="h-4 w-4" strokeWidth={1.5} />
            {sentRecipient ? "Sent via Resend" : "Send Email"}
          </Button>
        </div>
      </div>
    </div>
  );
};
