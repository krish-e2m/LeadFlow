"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, ArrowRight, Info, Search } from "lucide-react";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Input, Textarea } from "@/components/Input";
import { PageHeader } from "@/components/PageHeader";
import { RunProgressIndicator } from "@/components/RunProgressIndicator";
import { Select } from "@/components/Select";
import { useToast } from "@/components/Toast";
import { Run, Audience } from "@/types";
import { apiClient } from "@/lib/api-client";

const NO_AUDIENCE = "none";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

const CriteriaRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex items-start justify-between gap-4 border-b border-border py-2.5 last:border-b-0">
    <dt className="w-32 shrink-0 text-caption text-fg-secondary">{label}</dt>
    <dd className="flex min-w-0 flex-1 flex-wrap justify-end gap-1.5">{children}</dd>
  </div>
);

const Tags: React.FC<{ items: string[]; empty: string; variant?: "neutral" | "danger" | "warning" }> = ({
  items,
  empty,
  variant = "neutral",
}) =>
  items.length > 0 ? (
    <>
      {items.map((item) => (
        <Badge key={item} variant={variant} size="sm">
          {item}
        </Badge>
      ))}
    </>
  ) : (
    <span className="text-caption text-fg-tertiary">{empty}</span>
  );

export default function NewSearchPage() {
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState("B2B SaaS Growth Discovery");
  const [limit, setLimit] = useState(25);
  const [domainsText, setDomainsText] = useState("");
  const [audiences, setAudiences] = useState<Audience[]>([]);
  const [selectedAudienceId, setSelectedAudienceId] = useState<string>("");
  const [selectedAudience, setSelectedAudience] = useState<Audience | null>(null);
  const [isLoadingAudience, setIsLoadingAudience] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 1. Fetch available audiences on mount
  useEffect(() => {
    apiClient
      .get<Audience[]>("/audiences")
      .then((data) => setAudiences(data))
      .catch(() => setAudiences([]));
  }, []);

  // 2. Resolve the selected audience's criteria and rationale
  useEffect(() => {
    if (!selectedAudienceId) {
      setSelectedAudience(null);
      return;
    }

    setIsLoadingAudience(true);
    apiClient
      .get<Audience>(`/audiences/${selectedAudienceId}`)
      .then((data) => {
        setSelectedAudience(data);
        // Suggest a job name based on the audience title
        setName((prev) => {
          if (!prev || prev === "B2B SaaS Growth Discovery" || prev.endsWith("Discovery")) {
            return `${data.name} Discovery`;
          }
          return prev;
        });
      })
      .catch(() => {
        setSelectedAudience(audiences.find((a) => a.id === selectedAudienceId) || null);
      })
      .finally(() => setIsLoadingAudience(false));
  }, [selectedAudienceId, audiences]);

  const handleStartSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    const domains = domainsText
      .split(/[\n,]+/)
      .map((d) => d.trim().replace(/^https?:\/\//, "").split("/")[0])
      .filter(Boolean);

    // Either an audience or direct domains are required
    if (!selectedAudienceId && domains.length === 0) {
      setError("Choose an audience or enter at least one domain to search.");
      setIsLoading(false);
      return;
    }

    // Only include domains if the user entered them
    const query_params: Record<string, unknown> = {};
    if (domains.length > 0) {
      query_params.domains = domains;
    }

    try {
      // Submit the async search (the API answers 202 Accepted), then poll its run
      const res = await apiClient.post<{ run_id: string; poll_url: string; message: string }>("/searches", {
        name,
        limit,
        audience_id: selectedAudienceId || null,
        query_params,
      });

      toast.info("Search started", "Leads appear in the table as they are scored.");
      await apiClient.pollRun(res.run_id, (currentRun) => setActiveRun(currentRun), 1500);
    } catch (err: unknown) {
      setError(errorMessage(err, "The search couldn't be started. Try again in a moment."));
    } finally {
      setIsLoading(false);
    }
  };

  const audienceFilters: Record<string, unknown> = selectedAudience?.filters || {};
  const asList = (value: unknown): string[] => (Array.isArray(value) ? (value as string[]) : []);
  const locations = asList(audienceFilters.locations);
  const employeeRanges = asList(audienceFilters.employee_ranges);
  const verticals = asList(audienceFilters.verticals).length ? asList(audienceFilters.verticals) : asList(audienceFilters.industries);
  const targetRoles = asList(audienceFilters.target_roles);
  const excludeDomains = asList(audienceFilters.exclude_domains);
  const excludeVerticals = asList(audienceFilters.exclude_verticals);
  const excludeExistingCrm = Boolean(audienceFilters.exclude_existing_crm);
  const verticalMatch = (audienceFilters.vertical_match as string) || "or";

  const audienceOptions = [
    { value: NO_AUDIENCE, label: "None (enter domains)" },
    ...audiences.map((aud) => ({ value: aud.id, label: `${aud.name} (v${aud.version})` })),
  ];

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <PageHeader
        title="New search"
        description="Find companies that match an audience, or audit specific domains. Results are scored as they arrive."
      />

      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-card border border-border bg-danger-subtle p-4">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" strokeWidth={1.5} />
          <div>
            <p className="text-sm font-medium text-fg">Couldn't start the search</p>
            <p className="mt-0.5 text-caption text-fg-secondary">{error}</p>
          </div>
        </div>
      )}

      <Card>
        <form onSubmit={handleStartSearch} className="space-y-5">
          <Input label="Search name" value={name} onChange={(e) => setName(e.target.value)} required />

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-caption font-medium text-fg">Audience</label>
              <Select
                value={selectedAudienceId || NO_AUDIENCE}
                onValueChange={(v) => setSelectedAudienceId(v === NO_AUDIENCE ? "" : v)}
                options={audienceOptions}
                aria-label="Audience"
              />
            </div>
            <Input
              label="Lead limit"
              helper="Up to 500 per search."
              type="number"
              min={1}
              max={500}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </div>

          {selectedAudience && (
            <div className="rounded-card border border-border bg-surface-subtle p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="truncate text-sm font-medium text-fg">
                  {selectedAudience.name} <span className="font-normal text-fg-tertiary">v{selectedAudience.version}</span>
                </p>
                <Badge variant={selectedAudience.is_active ? "success" : "danger"} size="sm">
                  {selectedAudience.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              {selectedAudience.description && <p className="mt-1 text-caption text-fg-secondary">{selectedAudience.description}</p>}

              <dl className="mt-2">
                <CriteriaRow label="Locations">
                  <Tags items={locations} empty="Any location" />
                </CriteriaRow>
                <CriteriaRow label="Headcount">
                  <Tags items={employeeRanges} empty="Any size" />
                </CriteriaRow>
                <CriteriaRow label={verticals.length > 1 ? `Verticals (${verticalMatch === "and" ? "match all" : "match any"})` : "Verticals"}>
                  <Tags items={verticals} empty="Unrestricted" />
                </CriteriaRow>
                <CriteriaRow label="Target roles">
                  <Tags items={targetRoles} empty="Any role" />
                </CriteriaRow>
                <CriteriaRow label="Exclusions">
                  {excludeExistingCrm && (
                    <Badge variant="warning" size="sm">
                      Already in CRM
                    </Badge>
                  )}
                  <Tags items={[...excludeDomains, ...excludeVerticals]} empty={excludeExistingCrm ? "" : "None"} variant="danger" />
                </CriteriaRow>
              </dl>

              {selectedAudience.ai_rationale && (
                <p className="mt-3 text-caption text-fg-secondary">
                  <span className="font-medium text-fg">Why these filters: </span>
                  {selectedAudience.ai_rationale}
                </p>
              )}

              <p className="mt-3 flex items-start gap-2 text-caption text-fg-secondary">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-fg-tertiary" strokeWidth={1.5} />
                {domainsText.trim()
                  ? "The domains below are audited and checked against this audience's criteria."
                  : "Without domains, Hunter looks for companies matching these locations, headcounts and verticals. Exclusions are applied after discovery."}
              </p>
            </div>
          )}

          <Textarea
            label={selectedAudience ? "Domains (optional)" : "Domains"}
            helper={
              selectedAudience
                ? "Leave empty to discover new companies from the audience. Each domain is audited by the website collectors."
                : "Separate domains with commas or new lines. Each one is audited by the website collectors."
            }
            rows={selectedAudience ? 3 : 4}
            value={domainsText}
            onChange={(e) => setDomainsText(e.target.value)}
            placeholder="example.com, another-example.com"
            className="font-mono"
          />

          <Button type="submit" size="lg" className="w-full" isLoading={isLoading || isLoadingAudience}>
            <Search className="h-4 w-4" strokeWidth={1.5} />
            Start search
          </Button>
        </form>
      </Card>

      {activeRun && (
        <section className="space-y-3" aria-label="Search progress">
          <h2 className="text-sm font-semibold text-fg">Progress</h2>
          <RunProgressIndicator run={activeRun} />

          {activeRun.status === "completed" && (
            <div className="flex justify-end">
              <Button onClick={() => router.push("/leads")}>
                View scored leads <ArrowRight className="h-4 w-4" strokeWidth={1.5} />
              </Button>
            </div>
          )}

          {activeRun.status === "failed" && activeRun.error_details && (
            <div role="alert" className="rounded-card border border-border bg-danger-subtle p-4">
              <p className="text-sm font-medium text-fg">The search failed</p>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-fg-secondary">
                {JSON.stringify(activeRun.error_details, null, 2)}
              </pre>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
