"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, RotateCw } from "lucide-react";
import { Lead } from "@/types";
import { Avatar } from "@/components/Brand";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/Badge";
import { EmptyState, ErrorState } from "@/components/StateDisplay";
import { Table, TableContainer, TableSkeletonRows, Td, Th } from "@/components/Table";
import { Tooltip } from "@/components/Tooltip";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { formatDate, formatNumber, formatRelative, getBandTone } from "@/lib/utils";

export default function ClientPortalPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [approvedLeads, setApprovedLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchApprovedLeads = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // The API only ever returns approved leads to client viewers
      setApprovedLeads(await apiClient.get<Lead[]>("/leads?approval_status=approved"));
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : "The approved leads couldn't be loaded.");
      setApprovedLeads([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchApprovedLeads();
  }, [fetchApprovedLeads]);

  return (
    <>
      <PageHeader
        title="Client portal"
        description={`Leads approved for outreach at ${user?.org_name || "your organization"}. This view is read-only.`}
        actions={
          <Button variant="secondary" onClick={fetchApprovedLeads} isLoading={isLoading}>
            {!isLoading && <RotateCw className="h-4 w-4" strokeWidth={1.5} />}
            Refresh
          </Button>
        }
      />

      {error ? (
        <ErrorState title="Couldn't load approved leads" message={error} onRetry={fetchApprovedLeads} />
      ) : !isLoading && approvedLeads.length === 0 ? (
        <EmptyState title="No approved leads yet" description="Leads appear here once your team has reviewed and approved them." />
      ) : (
        <>
          <p className="text-caption text-fg-secondary" aria-live="polite">
            {isLoading ? "Loading…" : `${formatNumber(approvedLeads.length)} approved ${approvedLeads.length === 1 ? "lead" : "leads"}`}
          </p>
          <TableContainer>
            <Table aria-label="Approved leads" aria-busy={isLoading}>
              <thead>
                <tr>
                  <Th stickyLeft="0px" className="min-w-[240px]">Company</Th>
                  <Th>Industry and location</Th>
                  <Th>Score band</Th>
                  <Th>Stage</Th>
                  <Th>Approved</Th>
                  <Th className="w-12">
                    <span className="sr-only">Open</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <TableSkeletonRows columns={["w-48", "w-32", "w-20", "w-20", "w-16", "w-6"]} />
                ) : (
                  approvedLeads.map((lead) => {
                    const location = [lead.city, lead.country].filter(Boolean).join(", ");
                    return (
                      <tr
                        key={lead.id}
                        onClick={() => router.push(`/leads/${lead.id}`)}
                        className="group cursor-pointer bg-surface transition-colors duration-fast hover:bg-surface-subtle"
                      >
                        <Td stickyLeft="0px" className="max-w-[320px]">
                          <div className="flex items-center gap-3">
                            <Avatar name={lead.company_name} size="sm" />
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-fg">{lead.company_name}</p>
                              <p className="truncate text-caption text-fg-tertiary">{lead.domain}</p>
                            </div>
                          </div>
                        </Td>
                        <Td className="max-w-[220px]">
                          <p className="truncate text-sm text-fg">{lead.industry || "—"}</p>
                          <p className="truncate text-caption text-fg-tertiary">{location || "—"}</p>
                        </Td>
                        <Td>
                          <StatusBadge tone={getBandTone(lead.score_band)}>{lead.score_band ?? "Not scored"}</StatusBadge>
                        </Td>
                        <Td>
                          <span className="whitespace-nowrap text-caption capitalize text-fg-secondary">{lead.pipeline_status}</span>
                        </Td>
                        <Td>
                          <Tooltip content={lead.approved_at ? formatDate(lead.approved_at) : ""}>
                            <span className="whitespace-nowrap text-caption text-fg-secondary">
                              {lead.approved_at ? formatRelative(lead.approved_at) : "—"}
                            </span>
                          </Tooltip>
                        </Td>
                        <Td className="w-12">
                          <ArrowUpRight className="h-4 w-4 text-fg-tertiary opacity-0 transition-opacity duration-fast group-hover:opacity-100" strokeWidth={1.5} />
                        </Td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </Table>
          </TableContainer>
        </>
      )}
    </>
  );
}
