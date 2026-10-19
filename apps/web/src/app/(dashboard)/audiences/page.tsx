"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Check, Plus, RotateCw, X } from "lucide-react";
import { Audience } from "@/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Checkbox } from "@/components/Checkbox";
import { Input, Textarea } from "@/components/Input";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Segmented } from "@/components/Segmented";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState, ErrorState } from "@/components/StateDisplay";
import { useToast } from "@/components/Toast";
import { apiClient } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface GeneratedICPResult {
  name: string;
  description: string;
  ai_rationale?: string;
  filters: {
    verticals?: string[];
    vertical_match?: "or" | "and";
    locations?: string[];
    location_match?: "or" | "and";
    exclude_locations?: string[];
    exclude_verticals?: string[];
    exclude_domains?: string[];
    exclude_existing_crm?: boolean;
    // Backward-compatible fields
    industries?: string[];
    employee_ranges?: string[];
    technologies?: string[];
    keywords?: string[];
    target_roles?: string[];
    [key: string]: any;
  };
  model_used?: string;
  generated_at?: string;
}

const EXAMPLE_PROMPTS = [
  "Small and medium businesses in Ahmedabad and Surat that could benefit from a better website or digital marketing",
  "Mid-market B2B SaaS companies in the US and Canada with 50-200 employees using HubSpot or Salesforce",
  "High-growth E-Commerce brands in North America and UK with 20-100 employees built on Shopify",
  "Healthcare & HealthTech startups in the United States with 25-250 employees needing performance optimization",
];

const HEADCOUNT_PRESETS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"];
const LOCATION_PRESETS = ["Ahmedabad", "Surat", "United States", "Canada", "United Kingdom", "India"];
const VERTICAL_PRESETS = ["Website Development", "Digital Marketing", "B2B SaaS", "E-Commerce", "Fintech"];

interface TagGroupProps {
  title: string;
  tags: string[];
  placeholder?: string;
  presets?: string[];
  /** Exclusion groups use the danger tone so they read differently from inclusions. */
  tone?: "neutral" | "danger";
  actionSlot?: React.ReactNode;
  onAdd: (value: string) => void;
  onRemove: (index: number) => void;
}

const TagGroup: React.FC<TagGroupProps> = ({
  title,
  tags,
  placeholder = "Add item",
  presets,
  tone = "neutral",
  actionSlot,
  onAdd,
  onRemove,
}) => {
  const [isAdding, setIsAdding] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isAdding && inputRef.current) inputRef.current.focus();
  }, [isAdding]);

  const commit = () => {
    const trimmed = inputValue.trim();
    if (trimmed) {
      onAdd(trimmed);
      setInputValue("");
    }
    setIsAdding(false);
  };

  const cancel = () => {
    setInputValue("");
    setIsAdding(false);
  };

  const availablePresets = presets ? presets.filter((p) => !tags.includes(p)) : [];

  return (
    <div className="focus-ring-within space-y-2.5 rounded-card border border-border bg-surface p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-caption font-medium text-fg">
          {title} <span className="font-normal text-fg-tertiary">{tags.length}</span>
        </h4>
        <div className="flex items-center gap-2">
          {actionSlot}
          {!isAdding && (
            <button
              type="button"
              onClick={() => setIsAdding(true)}
              className="focus-ring inline-flex items-center gap-1 rounded-control px-1.5 py-0.5 text-xs font-medium text-accent transition-colors duration-fast hover:bg-accent-subtle"
            >
              <Plus className="h-3 w-3" strokeWidth={2} /> Add
            </button>
          )}
        </div>
      </div>

      <div className="flex min-h-7 flex-wrap items-center gap-1.5">
        {tags.map((tag, idx) => (
          <span
            key={`${tag}-${idx}`}
            className={cn(
              "inline-flex h-6 items-center gap-1 rounded-control pl-2 pr-1 text-caption",
              tone === "danger" ? "bg-danger-subtle text-danger" : "bg-neutral-subtle text-fg"
            )}
          >
            <span className="max-w-[10rem] truncate" title={tag}>
              {tag}
            </span>
            <button
              type="button"
              onClick={() => onRemove(idx)}
              aria-label={`Remove ${tag}`}
              className="focus-ring inline-flex h-4 w-4 items-center justify-center rounded-control opacity-60 transition-opacity duration-fast hover:opacity-100"
            >
              <X className="h-3 w-3" strokeWidth={2} />
            </button>
          </span>
        ))}

        {isAdding && (
          <div className="inline-flex items-center gap-1">
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commit();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancel();
                }
              }}
              placeholder={placeholder}
              aria-label={`Add to ${title}`}
              className="focus-ring h-6 w-36 rounded-control border border-border-strong bg-surface px-2 text-caption text-fg placeholder:text-fg-tertiary"
            />
            <button
              type="button"
              onClick={commit}
              aria-label="Add"
              className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-control bg-accent-subtle text-accent"
            >
              <Check className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
            <button
              type="button"
              onClick={cancel}
              aria-label="Cancel"
              className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-control text-fg-tertiary hover:bg-surface-subtle"
            >
              <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
          </div>
        )}

        {tags.length === 0 && !isAdding && <span className="text-caption text-fg-tertiary">Nothing set</span>}
      </div>

      {availablePresets.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
          <span className="text-xs text-fg-tertiary">Suggestions</span>
          {availablePresets.slice(0, 4).map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => onAdd(preset)}
              className="focus-ring rounded-control border border-border px-1.5 py-0.5 text-xs text-fg-secondary transition-colors duration-fast hover:border-border-strong hover:text-fg"
            >
              + {preset}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const MATCH_OPTIONS = [
  { value: "or" as const, label: "Any" },
  { value: "and" as const, label: "All" },
];

const CriteriaLine: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 last:border-b-0">
    <dt className="shrink-0 text-caption text-fg-secondary">{label}</dt>
    <dd className="min-w-0 truncate text-right text-sm text-fg" title={value}>
      {value}
    </dd>
  </div>
);

export default function AudiencesPage() {
  const toast = useToast();
  const [audiences, setAudiences] = useState<Audience[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Modal Form fields
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [aiRationale, setAiRationale] = useState("");
  const [verticals, setVerticals] = useState("Website Development, Digital Marketing");
  const [verticalMatch, setVerticalMatch] = useState<"or" | "and">("or");
  const [locations, setLocations] = useState("Ahmedabad, Surat");
  const [locationMatch, setLocationMatch] = useState<"or" | "and">("or");
  const [excludeLocations, setExcludeLocations] = useState("");
  const [excludeVerticals, setExcludeVerticals] = useState("");
  const [excludeDomains, setExcludeDomains] = useState("");
  const [excludeExistingCrm, setExcludeExistingCrm] = useState(false);
  const [employeeRanges, setEmployeeRanges] = useState("11-50, 51-200");
  const [technologies, setTechnologies] = useState("");
  const [targetRoles, setTargetRoles] = useState("");
  const [keywords, setKeywords] = useState("");

  // AI Prompt State
  const [aiPrompt, setAiPrompt] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [aiResult, setAiResult] = useState<GeneratedICPResult | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAudiences = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<Audience[]>("/audiences");
      setAudiences(res);
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : "The audiences couldn't be loaded.");
      setAudiences([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAudiences();
  }, [fetchAudiences]);

  // Handle AI generation from prompt
  const handleGenerateFromPrompt = async (promptText?: string) => {
    const textToUse = promptText || aiPrompt;
    if (!textToUse || !textToUse.trim()) return;

    setIsGenerating(true);
    setAiError(null);
    setAiResult(null); // Clear stale results immediately so failures are truthful

    try {
      // Uses the documented /ai-propose endpoint (or aliased /generate-ai-criteria)
      const res = await apiClient.post<GeneratedICPResult>("/audiences/ai-propose", {
        prompt: textToUse.trim(),
      });
      setAiResult(res);
    } catch (err: unknown) {
      setAiError(err instanceof Error && err.message ? err.message : "Couldn't generate criteria. Check that OpenRouter is configured, then try again.");
    } finally {
      setIsGenerating(false);
    }
  };

  // Tag manipulation for AI result
  const handleRemoveTag = (category: keyof GeneratedICPResult["filters"], tagIndex: number) => {
    if (!aiResult) return;
    const currentList = (aiResult.filters[category] as string[]) || [];
    const updatedList = currentList.filter((_, idx) => idx !== tagIndex);
    setAiResult({
      ...aiResult,
      filters: {
        ...aiResult.filters,
        [category]: updatedList,
      },
    });
  };

  const handleAddTag = (category: keyof GeneratedICPResult["filters"], newTag: string) => {
    if (!aiResult || !newTag.trim()) return;
    const trimmed = newTag.trim();
    const currentList = (aiResult.filters[category] as string[]) || [];
    if (currentList.some((t) => t.toLowerCase() === trimmed.toLowerCase())) return;
    setAiResult({
      ...aiResult,
      filters: {
        ...aiResult.filters,
        [category]: [...currentList, trimmed],
      },
    });
  };

  const handleToggleMatchMode = (modeKey: "vertical_match" | "location_match") => {
    if (!aiResult) return;
    const current = aiResult.filters[modeKey] || "or";
    const next = current === "or" ? "and" : "or";
    setAiResult({
      ...aiResult,
      filters: {
        ...aiResult.filters,
        [modeKey]: next,
      },
    });
  };

  const handleToggleCrmExclusion = (checked: boolean) => {
    if (!aiResult) return;
    setAiResult({
      ...aiResult,
      filters: {
        ...aiResult.filters,
        exclude_existing_crm: checked,
      },
    });
  };

  const handleUpdateNameOrDescription = (field: "name" | "description", val: string) => {
    if (!aiResult) return;
    setAiResult({
      ...aiResult,
      [field]: val,
    });
  };

  // One-click save directly from AI generated result
  const handleSaveAiResult = async () => {
    if (!aiResult) return;
    setIsSubmitting(true);
    try {
      await apiClient.post("/audiences", {
        name: aiResult.name || "Custom AI Audience",
        description: aiResult.description || "",
        filters: aiResult.filters,
        ai_rationale: aiResult.ai_rationale || null,
      });
      toast.success("Audience saved", aiResult.name);
      setAiResult(null);
      setAiPrompt("");
      fetchAudiences();
    } catch (err: unknown) {
      toast.error("Couldn't save the audience", err instanceof Error && err.message ? err.message : "Try again in a moment.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Load AI generated result into editor modal for fine-tuning
  const handleEditAiResultInModal = () => {
    if (!aiResult) return;
    setName(aiResult.name || "");
    setDescription(aiResult.description || "");
    setAiRationale(aiResult.ai_rationale || "");
    setVerticals(((aiResult.filters.verticals?.length ? aiResult.filters.verticals : aiResult.filters.industries) || []).join(", "));
    setVerticalMatch(aiResult.filters.vertical_match || "or");
    setLocations((aiResult.filters.locations || []).join(", "));
    setLocationMatch(aiResult.filters.location_match || "or");
    setExcludeLocations((aiResult.filters.exclude_locations || []).join(", "));
    setExcludeVerticals((aiResult.filters.exclude_verticals || []).join(", "));
    setExcludeDomains((aiResult.filters.exclude_domains || []).join(", "));
    setExcludeExistingCrm(Boolean(aiResult.filters.exclude_existing_crm));
    setEmployeeRanges((aiResult.filters.employee_ranges || []).join(", "));
    setTechnologies((aiResult.filters.technologies || []).join(", "));
    setTargetRoles((aiResult.filters.target_roles || []).join(", "));
    setKeywords((aiResult.filters.keywords || []).join(", "));
    setIsModalOpen(true);
  };

  const handleOpenEmptyModal = () => {
    setName("");
    setDescription("");
    setAiRationale("");
    setVerticals("Website Development, Digital Marketing");
    setVerticalMatch("or");
    setLocations("Ahmedabad, Surat");
    setLocationMatch("or");
    setExcludeLocations("");
    setExcludeVerticals("");
    setExcludeDomains("");
    setExcludeExistingCrm(false);
    setEmployeeRanges("11-50, 51-200");
    setTechnologies("");
    setTargetRoles("");
    setKeywords("");
    setIsModalOpen(true);
  };

  const handleCreateAudience = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const splitClean = (str: string) =>
        str
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);

      const parsedVerts = splitClean(verticals);
      const parsedLocs = splitClean(locations);

      const filters = {
        verticals: parsedVerts,
        vertical_match: verticalMatch,
        locations: parsedLocs,
        location_match: locationMatch,
        exclude_locations: splitClean(excludeLocations),
        exclude_verticals: splitClean(excludeVerticals),
        exclude_domains: splitClean(excludeDomains),
        exclude_existing_crm: excludeExistingCrm,
        industries: parsedVerts,
        employee_ranges: splitClean(employeeRanges),
        technologies: splitClean(technologies),
        target_roles: splitClean(targetRoles),
        keywords: splitClean(keywords),
      };

      await apiClient.post("/audiences", {
        name,
        description,
        filters,
        ai_rationale: aiRationale || null,
      });

      setIsModalOpen(false);
      handleOpenEmptyModal();
      toast.success("Audience saved", name);
      fetchAudiences();
    } catch (err: unknown) {
      toast.error("Couldn't create the audience", err instanceof Error && err.message ? err.message : "Try again in a moment.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const totalCriteriaCount = aiResult
    ? ((aiResult.filters.verticals?.length || aiResult.filters.industries?.length || 0) +
       (aiResult.filters.locations?.length || 0) +
       (aiResult.filters.exclude_locations?.length || 0) +
       (aiResult.filters.exclude_verticals?.length || 0) +
       (aiResult.filters.exclude_domains?.length || 0) +
       (aiResult.filters.employee_ranges?.length || 0) +
       (aiResult.filters.technologies?.length || 0) +
       (aiResult.filters.target_roles?.length || 0) +
       (aiResult.filters.keywords?.length || 0))
    : 0;

  const listOf = (value: unknown): string[] => (Array.isArray(value) ? (value as string[]) : []);

  return (
    <>
      <PageHeader
        title="Audiences"
        description="Saved ideal customer profiles. Describe a market in plain English and review the filters before saving."
        actions={
          <>
            <Button variant="secondary" onClick={fetchAudiences} isLoading={isLoading}>
              {!isLoading && <RotateCw className="h-4 w-4" strokeWidth={1.5} />}
              Refresh
            </Button>
            <Button onClick={handleOpenEmptyModal}>
              <Plus className="h-4 w-4" strokeWidth={1.5} />
              New audience
            </Button>
          </>
        }
      />

      {/* Generator */}
      <Card className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-fg">Describe your target market</h2>
          <p className="mt-0.5 text-caption text-fg-secondary">
            AI proposes locations, verticals, exclusions and headcount. It never runs a search or spends credits.
          </p>
        </div>

        <Textarea
          aria-label="Target market description"
          rows={3}
          value={aiPrompt}
          onChange={(e) => setAiPrompt(e.target.value)}
          placeholder="e.g. I run a website development agency. Find small businesses in Ahmedabad and Surat that could benefit from a better website."
        />

        <div className="space-y-1.5">
          <p className="text-xs text-fg-secondary">Try an example</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_PROMPTS.map((example, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setAiPrompt(example);
                  handleGenerateFromPrompt(example);
                }}
                className="focus-ring max-w-full truncate rounded-control border border-border px-2.5 py-1 text-left text-caption text-fg-secondary transition-colors duration-fast hover:border-border-strong hover:text-fg"
                title={example}
              >
                {example.length > 70 ? `${example.substring(0, 70)}…` : example}
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end">
          <Button onClick={() => handleGenerateFromPrompt()} isLoading={isGenerating} disabled={!aiPrompt.trim()}>
            Generate criteria
          </Button>
        </div>

        {aiError && (
          <div role="alert" className="rounded-control bg-danger-subtle px-3 py-2.5 text-caption text-danger">
            <span className="font-medium">Couldn't generate criteria. </span>
            {aiError}
          </div>
        )}

        {aiResult && (
          <div className="space-y-4 rounded-card border border-accent bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
              <div className="min-w-0 flex-1 space-y-1">
                <input
                  type="text"
                  value={aiResult.name}
                  onChange={(e) => handleUpdateNameOrDescription("name", e.target.value)}
                  placeholder="Audience name"
                  aria-label="Audience name"
                  className="focus-ring w-full max-w-md rounded-control border border-transparent bg-transparent px-1 py-0.5 text-xl font-semibold text-fg hover:border-border focus:border-border"
                />
                <input
                  type="text"
                  value={aiResult.description}
                  onChange={(e) => handleUpdateNameOrDescription("description", e.target.value)}
                  placeholder="Add a short description"
                  aria-label="Audience description"
                  className="focus-ring w-full rounded-control border border-transparent bg-transparent px-1 py-0.5 text-sm text-fg-secondary hover:border-border focus:border-border"
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-fg-tertiary">
                {aiResult.model_used && <span className="font-mono">{aiResult.model_used}</span>}
                <Badge size="sm">
                  {totalCriteriaCount} {totalCriteriaCount === 1 ? "filter" : "filters"}
                </Badge>
              </div>
            </div>

            {aiResult.ai_rationale && (
              <p className="text-sm text-fg-secondary">
                <span className="font-medium text-fg">Why these filters: </span>
                {aiResult.ai_rationale}
              </p>
            )}

            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              <TagGroup
                title="Verticals"
                tags={aiResult.filters.verticals || aiResult.filters.industries || []}
                placeholder="e.g. Website development"
                presets={VERTICAL_PRESETS}
                actionSlot={
                  <Segmented
                    size="sm"
                    aria-label="Vertical match mode"
                    value={aiResult.filters.vertical_match || "or"}
                    onValueChange={() => handleToggleMatchMode("vertical_match")}
                    options={MATCH_OPTIONS}
                  />
                }
                onAdd={(tag) => {
                  handleAddTag("verticals", tag);
                  handleAddTag("industries", tag);
                }}
                onRemove={(idx) => {
                  handleRemoveTag("verticals", idx);
                  handleRemoveTag("industries", idx);
                }}
              />
              <TagGroup
                title="Locations"
                tags={aiResult.filters.locations || []}
                placeholder="e.g. Ahmedabad"
                presets={LOCATION_PRESETS}
                actionSlot={
                  <Segmented
                    size="sm"
                    aria-label="Location match mode"
                    value={aiResult.filters.location_match || "or"}
                    onValueChange={() => handleToggleMatchMode("location_match")}
                    options={MATCH_OPTIONS}
                  />
                }
                onAdd={(tag) => handleAddTag("locations", tag)}
                onRemove={(idx) => handleRemoveTag("locations", idx)}
              />
              <TagGroup
                title="Headcount"
                tags={aiResult.filters.employee_ranges || []}
                placeholder="e.g. 51-200"
                presets={HEADCOUNT_PRESETS}
                onAdd={(tag) => handleAddTag("employee_ranges", tag)}
                onRemove={(idx) => handleRemoveTag("employee_ranges", idx)}
              />
              <TagGroup
                title="Exclude locations"
                tone="danger"
                tags={aiResult.filters.exclude_locations || []}
                placeholder="e.g. California"
                onAdd={(tag) => handleAddTag("exclude_locations", tag)}
                onRemove={(idx) => handleRemoveTag("exclude_locations", idx)}
              />
              <TagGroup
                title="Exclude verticals"
                tone="danger"
                tags={aiResult.filters.exclude_verticals || []}
                placeholder="e.g. Non-profits"
                onAdd={(tag) => handleAddTag("exclude_verticals", tag)}
                onRemove={(idx) => handleRemoveTag("exclude_verticals", idx)}
              />
              <TagGroup
                title="Exclude domains"
                tone="danger"
                tags={aiResult.filters.exclude_domains || []}
                placeholder="e.g. competitor.com"
                onAdd={(tag) => handleAddTag("exclude_domains", tag)}
                onRemove={(idx) => handleRemoveTag("exclude_domains", idx)}
              />
              <TagGroup
                title="Tech stack"
                tags={aiResult.filters.technologies || []}
                placeholder="e.g. WordPress"
                onAdd={(tag) => handleAddTag("technologies", tag)}
                onRemove={(idx) => handleRemoveTag("technologies", idx)}
              />
              <TagGroup
                title="Target roles"
                tags={aiResult.filters.target_roles || []}
                placeholder="e.g. Managing Director"
                onAdd={(tag) => handleAddTag("target_roles", tag)}
                onRemove={(idx) => handleRemoveTag("target_roles", idx)}
              />
              <TagGroup
                title="Keywords"
                tags={aiResult.filters.keywords || []}
                placeholder="e.g. B2B, SME"
                onAdd={(tag) => handleAddTag("keywords", tag)}
                onRemove={(idx) => handleRemoveTag("keywords", idx)}
              />
            </div>

            <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-fg">
              <Checkbox
                checked={Boolean(aiResult.filters.exclude_existing_crm)}
                onCheckedChange={(checked) => handleToggleCrmExclusion(checked === true)}
              />
              Skip companies already synced to HubSpot
            </label>

            <p className="text-caption text-fg-tertiary">
              Match modes default to “Any” for the widest reach. Choose “All” to require every value.
            </p>

            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
              <Button variant="ghost" onClick={() => setAiResult(null)}>
                Discard
              </Button>
              <Button variant="secondary" onClick={handleEditAiResultInModal}>
                Edit in dialog
              </Button>
              <Button onClick={handleSaveAiResult} isLoading={isSubmitting}>
                Save audience
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Saved audiences */}
      <section className="space-y-3" aria-label="Saved audiences">
        <h2 className="text-sm font-semibold text-fg">
          Saved audiences <span className="font-normal text-fg-tertiary">{audiences.length}</span>
        </h2>

        {isLoading ? (
          <div className="grid gap-4 md:grid-cols-2" role="status" aria-live="polite">
            <span className="sr-only">Loading audiences…</span>
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-48" />
            ))}
          </div>
        ) : error ? (
          <ErrorState title="Couldn't load audiences" message={error} onRetry={fetchAudiences} />
        ) : audiences.length === 0 ? (
          <EmptyState
            title="No audiences yet"
            description="Describe a market above, or create one manually."
            actionLabel="New audience"
            onAction={handleOpenEmptyModal}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {audiences.map((aud) => {
              const filters = (aud.filters || {}) as Record<string, unknown>;
              const verts = listOf(filters.verticals).length ? listOf(filters.verticals) : listOf(filters.industries);
              const locs = listOf(filters.locations);
              const emps = listOf(filters.employee_ranges);
              const techs = listOf(filters.technologies);
              const roles = listOf(filters.target_roles);
              const kw = listOf(filters.keywords);
              const exclLocs = listOf(filters.exclude_locations);
              const exclDoms = listOf(filters.exclude_domains);
              const exclVerts = listOf(filters.exclude_verticals);
              const matchWord = (key: string) => (filters[key] === "and" ? "all" : "any");
              const exclusions = [
                exclLocs.length ? `${exclLocs.length} ${exclLocs.length === 1 ? "location" : "locations"}` : null,
                exclVerts.length ? `${exclVerts.length} ${exclVerts.length === 1 ? "vertical" : "verticals"}` : null,
                exclDoms.length ? `${exclDoms.length} ${exclDoms.length === 1 ? "domain" : "domains"}` : null,
                filters.exclude_existing_crm ? "already in CRM" : null,
              ].filter(Boolean);

              return (
                <Card key={aud.id} className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate text-sm font-semibold text-fg">{aud.name}</h3>
                      <p className="mt-0.5 line-clamp-2 text-caption text-fg-secondary">{aud.description || "No description."}</p>
                    </div>
                    <Badge size="sm">v{aud.version}</Badge>
                  </div>

                  {aud.ai_rationale && <p className="text-caption text-fg-secondary">{aud.ai_rationale}</p>}

                  <dl>
                    <CriteriaLine label={`Verticals (${matchWord("vertical_match")})`} value={verts.length ? verts.join(", ") : "All verticals"} />
                    <CriteriaLine label={`Locations (${matchWord("location_match")})`} value={locs.length ? locs.join(", ") : "Anywhere"} />
                    {emps.length > 0 && <CriteriaLine label="Headcount" value={emps.join(", ")} />}
                    {techs.length > 0 && <CriteriaLine label="Tech stack" value={techs.join(", ")} />}
                    {roles.length > 0 && <CriteriaLine label="Roles" value={roles.join(", ")} />}
                    {kw.length > 0 && <CriteriaLine label="Keywords" value={kw.join(", ")} />}
                    {exclusions.length > 0 && <CriteriaLine label="Excludes" value={exclusions.join(", ")} />}
                  </dl>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Editor dialog */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Audience editor"
        description="Filters used to discover and match companies. Separate values with commas."
        className="max-w-2xl"
      >
        <form onSubmit={handleCreateAudience} className="space-y-4">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Gujarat SME digital growth" required />
          <Input
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Website and marketing prospects in Gujarat"
          />
          <Textarea
            label="Rationale (optional)"
            rows={2}
            value={aiRationale}
            onChange={(e) => setAiRationale(e.target.value)}
            placeholder="Why these filters were chosen"
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Input label="Verticals" value={verticals} onChange={(e) => setVerticals(e.target.value)} placeholder="Website development, Digital marketing" />
              <div className="flex items-center gap-2">
                <span className="text-caption text-fg-secondary">Match</span>
                <Segmented size="sm" aria-label="Vertical match" value={verticalMatch} onValueChange={setVerticalMatch} options={MATCH_OPTIONS} />
              </div>
            </div>
            <div className="space-y-2">
              <Input label="Locations" value={locations} onChange={(e) => setLocations(e.target.value)} placeholder="Ahmedabad, Surat" />
              <div className="flex items-center gap-2">
                <span className="text-caption text-fg-secondary">Match</span>
                <Segmented size="sm" aria-label="Location match" value={locationMatch} onValueChange={setLocationMatch} options={MATCH_OPTIONS} />
              </div>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Headcount ranges" value={employeeRanges} onChange={(e) => setEmployeeRanges(e.target.value)} placeholder="11-50, 51-200" />
            <Input label="Exclude locations" value={excludeLocations} onChange={(e) => setExcludeLocations(e.target.value)} placeholder="California, London" />
            <Input label="Exclude verticals" value={excludeVerticals} onChange={(e) => setExcludeVerticals(e.target.value)} placeholder="Government, Non-profit" />
            <Input label="Exclude domains" value={excludeDomains} onChange={(e) => setExcludeDomains(e.target.value)} placeholder="competitor.com" />
            <Input label="Technologies" value={technologies} onChange={(e) => setTechnologies(e.target.value)} placeholder="WordPress, Shopify" />
            <Input label="Target roles" value={targetRoles} onChange={(e) => setTargetRoles(e.target.value)} placeholder="CEO, Founder" />
          </div>
          <Input label="Keywords" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="SME, Growth, Marketing" />

          <label className="flex w-fit cursor-pointer items-center gap-2 text-sm text-fg">
            <Checkbox checked={excludeExistingCrm} onCheckedChange={(checked) => setExcludeExistingCrm(checked === true)} />
            Skip existing CRM contacts
          </label>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" type="button" onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isSubmitting}>
              Save audience
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
