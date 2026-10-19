"use client";

import React, { useEffect, useState } from "react";
import { Copy, Mail, Phone } from "lucide-react";
import { ContactRevealResult } from "@/types";
import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";

interface RevealContactDialogProps {
  /** The company to reveal a contact for; null closes the dialog. */
  lead: { id: string; company_name: string; domain: string } | null;
  onClose: () => void;
  onRevealed?: (result: ContactRevealResult) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * One-click company reveal: confirms the credit spend, then shows the revealed person's
 * work email and phone with copy buttons.
 */
export const RevealContactDialog: React.FC<RevealContactDialogProps> = ({ lead, onClose, onRevealed }) => {
  const toast = useToast();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ContactRevealResult | null>(null);

  useEffect(() => {
    if (lead) {
      setError(null);
      setResult(null);
    }
  }, [lead]);

  const handleReveal = async () => {
    if (!lead) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<ContactRevealResult>(`/leads/${lead.id}/reveal-contact`, {
        confirm_credit_spend: true,
      });
      setResult(res);
      onRevealed?.(res);
    } catch (err: unknown) {
      setError(errorMessage(err, "The contact couldn't be revealed. Try again in a moment."));
    } finally {
      setIsLoading(false);
    }
  };

  const copy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label} copied`, value);
    } catch {
      toast.error("Couldn't copy", "Your browser blocked clipboard access.");
    }
  };

  const contact = result?.contact;
  const name = contact ? [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Contact" : "";

  return (
    <Modal
      isOpen={lead !== null}
      onClose={onClose}
      title={result ? "Contact revealed" : `Reveal a contact at ${lead?.company_name ?? "this company"}?`}
      description={
        result
          ? result.message
          : `LeadFlow looks up the top decision-maker at ${lead?.domain ?? "this domain"} with Hunter.io and shows their verified work email. This uses 1 reveal credit.`
      }
    >
      {contact ? (
        <div className="space-y-4">
          <div className="rounded-card border border-border p-4">
            <p className="text-sm font-medium text-fg">{name}</p>
            <p className="text-caption text-fg-secondary">{contact.title || "Title unknown"}</p>
            <dl className="mt-3 space-y-2 border-t border-border pt-3 text-caption">
              {[
                { icon: Mail, label: "Email", value: contact.email },
                { icon: Phone, label: "Phone", value: contact.phone },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} className="flex items-center gap-2">
                  <dt className="sr-only">{label}</dt>
                  <Icon className="h-4 w-4 shrink-0 text-fg-tertiary" strokeWidth={1.5} aria-hidden="true" />
                  <dd className="min-w-0 flex-1 truncate font-mono text-fg">{value || "Not on file"}</dd>
                  {value && (
                    <button
                      type="button"
                      onClick={() => void copy(value, label)}
                      aria-label={`Copy ${label.toLowerCase()}`}
                      className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-control text-fg-tertiary transition-colors duration-fast hover:bg-surface-subtle hover:text-fg"
                    >
                      <Copy className="h-3.5 w-3.5" strokeWidth={1.5} />
                    </button>
                  )}
                </div>
              ))}
            </dl>
          </div>
          {result?.credits_remaining !== null && result?.credits_remaining !== undefined && (
            <p className="text-caption text-fg-tertiary">{result.credits_remaining} reveals left today.</p>
          )}
          <div className="flex justify-end">
            <Button onClick={onClose}>Done</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {error && (
            <p role="alert" className="rounded-control bg-danger-subtle px-3 py-2 text-caption text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button isLoading={isLoading} onClick={handleReveal}>
              Reveal contact (1 credit)
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
};
