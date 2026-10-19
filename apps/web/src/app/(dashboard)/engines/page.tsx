"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Plus, RotateCw, Sparkles, SlidersHorizontal } from "lucide-react";
import { Badge, StatusBadge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Input, Textarea } from "@/components/Input";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/StateDisplay";
import { useToast } from "@/components/Toast";
import { Lead, ScoringEngine, ScoringEngineParam } from "@/types";
import { apiClient } from "@/lib/api-client";
import { describeBandChanges, type BandChanges } from "@/lib/utils";

// Re-scoring is compute-only (existing evidence, no provider calls) and the bulk endpoint takes
// at most 100 leads per request.
const RESCORE_BATCH = 100;

interface ProposedEngineWeights {
  weights: Record<string, number>;
  threshold_high: number;
  threshold_medium: number;
  ideal_client_bonus: number;
  ai_rationale: string;
  model_used?: string;
}

// Canonical 22 signals and labels
const SIGNAL_DEFINITIONS: Record<string, { label: string; defaultWeight: number; category: "website" | "marketing" }> = {
  legacy_platform: { label: "Outdated CMS / platform", defaultWeight: 1.5, category: "website" },
  slow_site: { label: "Slow page speed", defaultWeight: 1.3, category: "website" },
  old_design: { label: "Outdated design patterns", defaultWeight: 1.0, category: "website" },
  weak_ctas: { label: "Weak or missing calls to action", defaultWeight: 1.0, category: "website" },
  not_mobile_friendly: { label: "Poor mobile optimization", defaultWeight: 0.8, category: "website" },
  no_ssl: { label: "Missing or insecure SSL", defaultWeight: 1.2, category: "website" },
  thin_content: { label: "Thin homepage content", defaultWeight: 0.7, category: "website" },
  no_analytics: { label: "No web analytics", defaultWeight: 0.6, category: "website" },
  accessibility: { label: "Accessibility issues", defaultWeight: 0.6, category: "website" },
  no_live_chat: { label: "No live chat widget", defaultWeight: 0.5, category: "website" },

  poor_seo: { label: "Weak organic SEO", defaultWeight: 1.4, category: "marketing" },
  poor_aeo_geo: { label: "Missing schema and GEO/AEO data", defaultWeight: 1.0, category: "marketing" },
  low_domain_trust: { label: "Low domain authority", defaultWeight: 0.6, category: "marketing" },
  stale_blog: { label: "Stale or missing blog", defaultWeight: 1.1, category: "marketing" },
  no_press: { label: "No press coverage", defaultWeight: 0.7, category: "marketing" },
  no_case_studies: { label: "No case studies or social proof", defaultWeight: 0.8, category: "marketing" },
  no_video: { label: "No video content", defaultWeight: 0.5, category: "marketing" },
  weak_social: { label: "Weak social presence", defaultWeight: 0.9, category: "marketing" },
  weak_email_capture: { label: "No lead capture or newsletter form", defaultWeight: 0.6, category: "marketing" },
  ppc_spend: { label: "Paid search spend", defaultWeight: 1.2, category: "marketing" },
  hiring: { label: "Open positions", defaultWeight: 1.1, category: "marketing" },
  low_review_rating: { label: "Low review rating (under 3.8)", defaultWeight: 0.8, category: "marketing" },
};

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** The newest parameter set. The API returns versions newest-first, but never rely on the order. */
function latestParams(engine: ScoringEngine): ScoringEngineParam | null {
  if (!engine.params || engine.params.length === 0) return null;
  return engine.params.reduce((latest, param) => (param.version > latest.version ? param : latest));
}

export default function ScoringEnginesPage() {
  const toast = useToast();
  const [engine, setEngine] = useState<ScoringEngine | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [thresholdHigh, setThresholdHigh] = useState(75);
  const [thresholdMedium, setThresholdMedium] = useState(50);
  const [idealBonus, setIdealBonus] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRescoring, setIsRescoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // AI propose: suggests weights/thresholds from a brief. Never auto-saves — the operator
  // reviews the sliders below and clicks Publish, same as a manual edit.
  const [brief, setBrief] = useState("");
  const [isProposing, setIsProposing] = useState(false);
  const [proposeError, setProposeError] = useState<string | null>(null);
  const [aiRationale, setAiRationale] = useState<string | null>(null);

  const fetchEngineData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const engines = await apiClient.get<ScoringEngine[]>("/engines");
      if (engines && engines.length > 0) {
        const active = engines[0];
        setEngine(active);
        const latest = latestParams(active);

        const initial: Record<string, number> = {};
        Object.entries(SIGNAL_DEFINITIONS).forEach(([key, def]) => {
          initial[key] = latest?.weights?.[key] !== undefined ? latest.weights[key] : def.defaultWeight;
        });
        setWeights(initial);
        if (latest) {
          setThresholdHigh(latest.threshold_high);
          setThresholdMedium(latest.threshold_medium);
          setIdealBonus(latest.ideal_client_bonus ?? 0);
        }
      } else {
        setEngine(null);
      }
    } catch (err: unknown) {
      setError(errorMessage(err, "The scoring engine couldn't be loaded."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchEngineData();
  }, [fetchEngineData]);

  const handleCreateDefaultEngine = async () => {
    setIsSaving(true);
    try {
      const defaultWeights: Record<string, number> = {};
      Object.entries(SIGNAL_DEFINITIONS).forEach(([k, v]) => {
        defaultWeights[k] = v.defaultWeight;
      });
      await apiClient.post("/engines", {
        name: "Standard growth scoring profile",
        description: "Canonical 22-signal weighted scoring configuration.",
        initial_weights: defaultWeights,
      });
      toast.success("Scoring engine created");
      await fetchEngineData();
    } catch (err: unknown) {
      setError(errorMessage(err, "The default scoring engine couldn't be created."));
    } finally {
      setIsSaving(false);
    }
  };

  const thresholdsValid = thresholdHigh > thresholdMedium && thresholdMedium >= 0 && thresholdHigh <= 100;

  const handleSave = async () => {
    if (!engine || !thresholdsValid) return;
    setIsSaving(true);
    setError(null);
    try {
      await apiClient.post(`/engines/${engine.id}/params`, {
        weights,
        threshold_high: thresholdHigh,
        threshold_medium: thresholdMedium,
        ideal_client_bonus: idealBonus,
      });
      await fetchEngineData();
      setAiRationale(null);
      toast.success("New version published", "Earlier scores keep the version they were calculated with.");
    } catch (err: unknown) {
      setError(errorMessage(err, "The new weights couldn't be published."));
    } finally {
      setIsSaving(false);
    }
  };

  const handleRescoreLeads = async () => {
    setIsRescoring(true);
    try {
      const leads = await apiClient.get<Lead[]>(`/leads?limit=${RESCORE_BATCH}&sort=newest`);
      const ids = leads
        .filter((l) => l.approval_status !== "rejected" && l.pipeline_status !== "error" && l.score_band !== null)
        .map((l) => l.id);
      if (ids.length === 0) {
        toast.info("Nothing to re-score", "There are no scored leads yet.");
        return;
      }
      const res = await apiClient.post<{ total_succeeded: number; band_changes?: BandChanges | null }>("/leads/bulk", {
        action: "rescore",
        lead_ids: ids,
      });
      toast.success(
        `${res.total_succeeded} lead${res.total_succeeded === 1 ? "" : "s"} re-scored with version ${engine?.active_version}`,
        describeBandChanges(res.band_changes)
      );
    } catch (err: unknown) {
      toast.error("Couldn't re-score leads", errorMessage(err, "Try again in a moment."));
    } finally {
      setIsRescoring(false);
    }
  };

  const handlePropose = async () => {
    if (!brief.trim()) return;
    setIsProposing(true);
    setProposeError(null);
    try {
      const proposed = await apiClient.post<ProposedEngineWeights>("/engines/ai-propose", { prompt: brief.trim() });
      setWeights((prev) => ({ ...prev, ...proposed.weights }));
      setThresholdHigh(proposed.threshold_high);
      setThresholdMedium(proposed.threshold_medium);
      setIdealBonus(proposed.ideal_client_bonus);
      setAiRationale(proposed.ai_rationale);
      toast.success("Weights proposed", "Review the sliders below, then publish when you're happy with them.");
    } catch (err: unknown) {
      setProposeError(errorMessage(err, "The AI couldn't propose weights for that brief."));
    } finally {
      setIsProposing(false);
    }
  };

  const numberInput = (setter: (n: number) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const parsed = parseFloat(e.target.value);
    setter(Number.isNaN(parsed) ? 0 : parsed);
  };

  const renderSection = (category: "website" | "marketing", title: string) => {
    const items = Object.entries(SIGNAL_DEFINITIONS).filter(([, s]) => s.category === category);
    return (
      <section className="space-y-3" aria-label={title}>
        <h2 className="text-sm font-semibold text-fg">
          {title} <span className="font-normal text-fg-tertiary">{items.length}</span>
        </h2>
        <ul className="divide-y divide-border rounded-card border border-border bg-surface">
          {items.map(([key, def]) => {
            const current = weights[key] !== undefined ? weights[key] : def.defaultWeight;
            return (
              <li key={key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_3rem] items-center gap-4 px-4 py-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_3rem]">
                <label htmlFor={`w-${key}`} className="truncate text-sm text-fg">
                  {def.label}
                </label>
                <input
                  id={`w-${key}`}
                  type="range"
                  min="0"
                  max="5"
                  step="0.1"
                  value={current}
                  onChange={(e) => setWeights((prev) => ({ ...prev, [key]: parseFloat(e.target.value) }))}
                  aria-valuetext={current === 0 ? "Off" : `${current.toFixed(1)} times`}
                  className="focus-ring h-1 w-full cursor-pointer accent-accent"
                />
                <span className={`text-right text-sm font-medium ${current === 0 ? "text-fg-tertiary" : "text-fg"}`}>
                  {current === 0 ? "Off" : `${current.toFixed(1)}×`}
                </span>
              </li>
            );
          })}
        </ul>
      </section>
    );
  };

  if (isLoading && !engine) {
    return (
      <>
        <PageHeader title="Scoring engines" />
        <div className="space-y-3" role="status" aria-live="polite">
          <span className="sr-only">Loading scoring engine…</span>
          <Skeleton className="h-28" />
          <Skeleton className="h-64" />
        </div>
      </>
    );
  }

  if (error && !engine) {
    return <ErrorState title="Couldn't load the scoring engine" message={error} onRetry={fetchEngineData} />;
  }

  if (!engine) {
    return (
      <>
        <PageHeader title="Scoring engines" description="Choose how much each of the 22 signals counts toward a lead's score." />
        <EmptyState
          icon={SlidersHorizontal}
          title="No scoring engine yet"
          description="Create the default 22-signal engine, then adjust the weights and score bands."
          actionLabel={isSaving ? "Creating…" : "Create default engine"}
          onAction={handleCreateDefaultEngine}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={engine.name}
        description="Weighted average of the 22 signals. Signals without data are skipped, never counted as zero. Set a weight to 0 to switch a signal off."
        actions={
          <>
            <Badge variant="info">Version {engine.active_version}</Badge>
            <Button variant="secondary" onClick={fetchEngineData} isLoading={isLoading}>
              {!isLoading && <RotateCw className="h-4 w-4" strokeWidth={1.5} />}
              Discard changes
            </Button>
            <Button
              variant="secondary"
              onClick={() => void handleRescoreLeads()}
              isLoading={isRescoring}
              title="Apply the published version to your latest 100 leads. Uses saved evidence, no credits."
            >
              Re-score leads
            </Button>
            <Button onClick={handleSave} isLoading={isSaving} disabled={!thresholdsValid}>
              <Plus className="h-4 w-4" strokeWidth={1.5} />
              Publish version {engine.active_version + 1}
            </Button>
          </>
        }
      />

      {error && (
        <p role="alert" className="rounded-control bg-danger-subtle px-3 py-2.5 text-caption text-danger">
          {error}
        </p>
      )}

      <Card className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-fg">Propose weights from a brief</h2>
          <p className="mt-0.5 text-caption text-fg-secondary">
            Describe the ideal client. AI suggests which of the 22 signals to weight higher — it edits the
            sliders below for you to review, nothing is saved until you publish.
          </p>
        </div>
        <Textarea
          placeholder="e.g. We sell SEO and content marketing to local businesses with an outdated blog and weak search presence."
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={2}
        />
        {proposeError && (
          <p role="alert" className="text-caption text-danger">
            {proposeError}
          </p>
        )}
        {aiRationale && (
          <p className="rounded-control bg-accent-subtle px-3 py-2 text-caption text-fg-secondary">{aiRationale}</p>
        )}
        <Button variant="secondary" onClick={handlePropose} isLoading={isProposing} disabled={!brief.trim()}>
          {!isProposing && <Sparkles className="h-4 w-4" strokeWidth={1.5} />}
          Propose weights
        </Button>
      </Card>

      <Card className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-fg">Score bands</h2>
          <p className="mt-0.5 text-caption text-fg-secondary">A lead lands in the highest band whose minimum score it reaches.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Input
              label="Qualified from"
              type="number"
              min={0}
              max={100}
              step={1}
              value={thresholdHigh}
              onChange={numberInput(setThresholdHigh)}
              error={thresholdHigh <= thresholdMedium ? "Must be above the review score." : undefined}
            />
            <StatusBadge tone="success">Qualified</StatusBadge>
          </div>
          <div className="space-y-1.5">
            <Input label="Review from" type="number" min={0} max={100} step={1} value={thresholdMedium} onChange={numberInput(setThresholdMedium)} />
            <StatusBadge tone="warning">Review</StatusBadge>
          </div>
        </div>
        <p className="text-caption text-fg-tertiary">
          Scores below {thresholdMedium} are <span className="font-medium text-fg-secondary">disqualified</span>.
        </p>

        <div className="border-t border-border pt-4 sm:max-w-xs">
          <Input
            label="Ideal-client bonus"
            helper="Points added when both the website and marketing scores are 50 or higher."
            type="number"
            min={0}
            max={100}
            step={1}
            value={idealBonus}
            onChange={numberInput(setIdealBonus)}
          />
        </div>
      </Card>

      {renderSection("website", "Website signals")}
      {renderSection("marketing", "Marketing signals")}
    </>
  );
}
