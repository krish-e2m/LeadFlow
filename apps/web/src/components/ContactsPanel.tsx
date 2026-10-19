"use client";

import React, { useState } from "react";
import { Search, UserSearch } from "lucide-react";
import { Contact, ContactDiscoverResult } from "@/types";
import { Button } from "@/components/Button";
import { ContactRevealCard } from "@/components/ContactRevealCard";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";

interface ContactsPanelProps {
  leadId: string;
  contacts: Contact[];
  /** Admins can find and reveal contacts; client viewers only see revealed ones. */
  canEdit: boolean;
  /** Reveals are only allowed once the lead is approved. */
  isApproved: boolean;
  onContactsChanged: () => void;
}

/** The lead's people, with per-person reveal and a Hunter lookup to find more. */
export const ContactsPanel: React.FC<ContactsPanelProps> = ({ leadId, contacts, canEdit, isApproved, onContactsChanged }) => {
  const toast = useToast();
  const [isFinding, setIsFinding] = useState(false);

  const handleFind = async () => {
    setIsFinding(true);
    try {
      const res = await apiClient.post<ContactDiscoverResult>(`/leads/${leadId}/contacts/discover`);
      if (res.created > 0) toast.success("Contacts found", res.message);
      else toast.info("No new contacts", res.message);
      onContactsChanged();
    } catch (err: unknown) {
      toast.error("Couldn't look up contacts", err instanceof Error && err.message ? err.message : "Try again in a moment.");
    } finally {
      setIsFinding(false);
    }
  };

  return (
    <div className="space-y-3">
      {contacts.length > 0 ? (
        contacts.map((contact) => (
          <ContactRevealCard
            key={`${contact.id}-${contact.is_revealed}`}
            contact={contact}
            canReveal={canEdit}
            blockedReason={isApproved ? undefined : "Approve the lead to reveal this contact."}
            onRevealed={() => onContactsChanged()}
          />
        ))
      ) : (
        <div className="flex flex-col items-center rounded-card border border-border px-4 py-8 text-center">
          <UserSearch className="mb-2 h-5 w-5 text-fg-tertiary" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-sm font-medium text-fg">No contacts yet</p>
          <p className="mt-1 max-w-xs text-caption text-fg-secondary">
            {canEdit
              ? "Look up decision-makers at this company with Hunter.io. Emails stay hidden until you reveal them."
              : "Contacts appear here once your team finds them."}
          </p>
        </div>
      )}

      {canEdit && (
        <Button variant={contacts.length > 0 ? "ghost" : "secondary"} className="w-full" isLoading={isFinding} onClick={handleFind}>
          {!isFinding && <Search className="h-4 w-4" strokeWidth={1.5} />}
          {contacts.length > 0 ? "Find more people" : "Find contacts"}
        </Button>
      )}
    </div>
  );
};
