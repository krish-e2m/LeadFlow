"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MailCheck, RotateCw } from "lucide-react";
import { Draft } from "@/types";
import { Button } from "@/components/Button";
import { DraftEditor } from "@/components/DraftEditor";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/StateDisplay";
import { apiClient } from "@/lib/api-client";

export default function DraftStudioPage() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDrafts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setDrafts(await apiClient.get<Draft[]>("/drafts"));
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : "The drafts couldn't be loaded.");
      setDrafts([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDrafts();
  }, [fetchDrafts]);

  const handleUpdateDraft = (updatedDraft: Draft) => {
    setDrafts((prev) => prev.map((d) => (d.id === updatedDraft.id ? updatedDraft : d)));
  };

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <PageHeader
        title="Drafts"
        description="Emails written when you approve a lead. Each cites the audit findings and must be approved before it syncs to HubSpot."
        actions={
          <Button variant="secondary" onClick={fetchDrafts} isLoading={isLoading}>
            {!isLoading && <RotateCw className="h-4 w-4" strokeWidth={1.5} />}
            Refresh
          </Button>
        }
      />

      {isLoading ? (
        <div className="space-y-4" role="status" aria-live="polite">
          <span className="sr-only">Loading drafts…</span>
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48" />
          ))}
        </div>
      ) : error ? (
        <ErrorState title="Couldn't load drafts" message={error} onRetry={fetchDrafts} />
      ) : drafts.length === 0 ? (
        <EmptyState
          icon={MailCheck}
          title="No drafts yet"
          description="Approving a lead writes its email draft automatically. You can also write one from a lead's Drafts tab."
          actionLabel="Go to leads"
          onAction={() => router.push("/leads")}
        />
      ) : (
        <div className="space-y-4">
          {drafts.map((draft) => (
            <DraftEditor key={draft.id} draft={draft} onUpdate={handleUpdateDraft} />
          ))}
        </div>
      )}
    </div>
  );
}
