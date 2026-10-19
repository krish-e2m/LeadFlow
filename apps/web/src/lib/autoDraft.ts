import { AutoDraftOutcome } from "@/types";

interface ToastLike {
  success: (title: string, description?: string) => void;
}

/** Description for the "Lead approved" toast, explaining what happened to the automatic email draft. */
export function approvalMessage(outcome: AutoDraftOutcome | null | undefined, company: string): string {
  switch (outcome) {
    case "queued":
      return `Writing an email draft for ${company}. It appears in Drafts in a few seconds.`;
    case "exists":
      return `${company} already has an email draft.`;
    case "not_configured":
      return "No email draft was written because OpenRouter isn't configured.";
    case "unavailable":
      return "The draft worker isn't running. Write the draft from the lead's Drafts tab.";
    default:
      return company;
  }
}

export function announceApproval(toast: ToastLike, outcome: AutoDraftOutcome | null | undefined, company: string) {
  toast.success("Lead approved", approvalMessage(outcome, company));
}
