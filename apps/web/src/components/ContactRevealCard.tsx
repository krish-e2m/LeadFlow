"use client";

import React, { useState } from "react";
import { Eye, Linkedin, Lock, Mail, Phone } from "lucide-react";
import { Contact } from "@/types";
import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/Badge";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";

interface ContactRevealCardProps {
  contact: Contact;
  onRevealed?: (updatedContact: Contact) => void;
  /** False hides the reveal button (client viewers). */
  canReveal?: boolean;
  /** Shown instead of the reveal button when revealing isn't allowed yet. */
  blockedReason?: string;
}

export const ContactRevealCard: React.FC<ContactRevealCardProps> = ({
  contact: initialContact,
  onRevealed,
  canReveal = true,
  blockedReason,
}) => {
  const toast = useToast();
  const [contact, setContact] = useState<Contact>(initialContact);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fullName = [contact.first_name, contact.last_name].filter(Boolean).join(" ") || "Decision maker";

  const handleConfirmReveal = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<{ contact: Contact }>(`/contacts/${contact.id}/reveal`, {
        confirm_credit_spend: true,
      });
      setContact(res.contact);
      onRevealed?.(res.contact);
      setIsModalOpen(false);
      toast.success("Contact revealed", `${fullName} is now visible. 1 credit used.`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Couldn't reveal this contact. Try again in a moment.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-medium text-fg">{fullName}</h4>
          <p className="truncate text-caption text-fg-secondary">{contact.title || "Executive"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <StatusBadge tone={contact.is_revealed ? "success" : "neutral"}>
            {contact.is_revealed ? "Revealed" : "Masked"}
          </StatusBadge>
          {contact.linkedin_url && (
            <a
              href={contact.linkedin_url}
              target="_blank"
              rel="noreferrer"
              aria-label={`${fullName} on LinkedIn`}
              className="focus-ring rounded-control text-fg-tertiary transition-colors duration-fast hover:text-accent"
            >
              <Linkedin className="h-4 w-4" strokeWidth={1.5} />
            </a>
          )}
        </div>
      </div>

      <dl className="mt-3 space-y-2 border-t border-border pt-3 text-caption">
        <div className="flex items-center gap-2">
          <dt className="sr-only">Email</dt>
          <Mail className="h-4 w-4 shrink-0 text-fg-tertiary" strokeWidth={1.5} />
          <dd className="min-w-0 truncate font-mono text-fg">
            {contact.is_revealed ? contact.email : contact.email || "••••@company.com"}
          </dd>
          {!contact.is_revealed && <Lock className="h-3.5 w-3.5 shrink-0 text-fg-tertiary" strokeWidth={1.5} />}
        </div>
        <div className="flex items-center gap-2">
          <dt className="sr-only">Phone</dt>
          <Phone className="h-4 w-4 shrink-0 text-fg-tertiary" strokeWidth={1.5} />
          <dd className="min-w-0 truncate font-mono text-fg">
            {contact.is_revealed ? contact.phone || "Not on file" : "Hidden until revealed"}
          </dd>
        </div>
      </dl>

      {!contact.is_revealed && canReveal && blockedReason && (
        <p className="mt-3 text-caption text-fg-tertiary">{blockedReason}</p>
      )}

      {!contact.is_revealed && canReveal && !blockedReason && (
        <Button variant="secondary" size="sm" className="mt-3 w-full" onClick={() => setIsModalOpen(true)}>
          <Eye className="h-4 w-4" strokeWidth={1.5} />
          Reveal contact (1 credit)
        </Button>
      )}

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Reveal this contact?"
        description="This shows the verified email and phone number and uses 1 credit. It can't be undone."
      >
        <div className="space-y-4">
          <p className="text-sm text-fg-secondary">
            You're about to reveal contact details for <span className="font-medium text-fg">{fullName}</span>.
          </p>
          {error && <p className="rounded-control bg-danger-subtle px-3 py-2 text-caption text-danger">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button isLoading={isLoading} onClick={handleConfirmReveal}>
              Reveal (1 credit)
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
