"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Lead } from "@/types";
import { apiClient } from "@/lib/api-client";

const FIRST_CHECK_MS = 2500;
const INTERVAL_MS = 3000;
const MAX_CHECKS = 20; // about a minute

interface DraftWatcherOptions {
  /** Called with the reloaded lead once a new draft appears. */
  onReady: (lead: Lead) => void;
  /** Called when no draft appeared within about a minute. */
  onTimeout?: () => void;
}

/**
 * Watches a lead after approval until the automatically queued email draft exists.
 * `start(currentDraftCount)` begins polling; `pending` is true while it waits.
 */
export function useDraftWatcher(leadId: string | null, { onReady, onTimeout }: DraftWatcherOptions) {
  const [pending, setPending] = useState(false);
  const baseline = useRef(0);
  const callbacks = useRef({ onReady, onTimeout });
  callbacks.current = { onReady, onTimeout };

  const start = useCallback((currentDraftCount: number) => {
    baseline.current = currentDraftCount;
    setPending(true);
  }, []);

  const stop = useCallback(() => setPending(false), []);

  useEffect(() => {
    if (!pending || !leadId) return;
    let cancelled = false;
    let checks = 0;
    let timer: number;

    const check = async () => {
      checks += 1;
      try {
        const lead = await apiClient.get<Lead>(`/leads/${leadId}`);
        if (cancelled) return;
        if ((lead.drafts?.length ?? 0) > baseline.current) {
          setPending(false);
          callbacks.current.onReady(lead);
          return;
        }
      } catch {
        /* a failed poll is retried on the next tick */
      }
      if (cancelled) return;
      if (checks >= MAX_CHECKS) {
        setPending(false);
        callbacks.current.onTimeout?.();
        return;
      }
      timer = window.setTimeout(check, INTERVAL_MS);
    };

    timer = window.setTimeout(check, FIRST_CHECK_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [pending, leadId]);

  return { pending, start, stop };
}
