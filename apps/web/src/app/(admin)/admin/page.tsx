"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Power, PowerOff, RefreshCw, Server, UserCheck, UserX, X } from "lucide-react";
import { ProviderStatus, AuditLog, Organization, User, AccessRequest } from "@/types";
import { Badge, StatusBadge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input } from "@/components/Input";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { EmptyState, UnavailableState } from "@/components/StateDisplay";
import { Table, TableContainer, Td, Th } from "@/components/Table";
import { Tabs } from "@/components/Tabs";
import { useToast } from "@/components/Toast";
import { Tooltip } from "@/components/Tooltip";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { formatDate, formatRelative, type Tone } from "@/lib/utils";

const requestTone: Record<string, Tone> = { approved: "success", rejected: "danger", pending: "warning" };

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

const roleLabel = (role: string) => (role === "org_admin" ? "Org admin" : role === "super_admin" ? "Super admin" : "Client viewer");

export default function AdminPage() {
  const { user } = useAuth();
  const toast = useToast();

  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [orgUsers, setOrgUsers] = useState<User[]>([]);
  const [accessRequests, setAccessRequests] = useState<AccessRequest[]>([]);
  const [processingReqId, setProcessingReqId] = useState<string | null>(null);
  const [rejectModalReq, setRejectModalReq] = useState<AccessRequest | null>(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [offboardTarget, setOffboardTarget] = useState<Organization | null>(null);
  const [tab, setTab] = useState("requests");
  const [requestFilter, setRequestFilter] = useState<"pending" | "all">("pending");

  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [providersLoaded, setProvidersLoaded] = useState(false);

  const isSuperAdmin = user?.role === "super_admin";
  const isAdmin = user?.role === "super_admin" || user?.role === "org_admin";

  const fetchAdminData = useCallback(async () => {
    setIsLoading(true);
    try {
      // Provider health checks call live services and can take many seconds, so they load on demand.
      const [auditData, usersData, accessRequestsData] = await Promise.all([
        apiClient.get<AuditLog[]>("/admin/audit-logs").catch(() => []),
        apiClient.get<User[]>("/users").catch(() => []),
        apiClient.get<AccessRequest[]>("/access-requests").catch(() => []),
      ]);
      setAuditLogs(auditData);
      setOrgUsers(usersData);
      setAccessRequests(accessRequestsData);

      if (isSuperAdmin) {
        setOrgs(await apiClient.get<Organization[]>("/admin/orgs").catch(() => []));
      }
    } catch (err: unknown) {
      toast.error("Couldn't load admin data", errorMessage(err, "Try refreshing the page."));
    } finally {
      setIsLoading(false);
    }
  }, [isSuperAdmin, toast]);

  useEffect(() => {
    void fetchAdminData();
  }, [fetchAdminData]);

  const loadProviders = useCallback(async (announce: boolean) => {
    setIsRefreshing(true);
    try {
      setProviders(await apiClient.get<ProviderStatus[]>("/admin/providers"));
      setProvidersLoaded(true);
      if (announce) toast.success("Health checks finished");
    } catch (err: unknown) {
      toast.error("Health checks failed", errorMessage(err, "Try again in a moment."));
    } finally {
      setIsRefreshing(false);
    }
  }, [toast]);

  const handleRefreshProviders = () => {
    setTab("providers");
    void loadProviders(true);
  };

  // Run the health checks the first time the Providers tab is opened.
  useEffect(() => {
    if (tab === "providers" && !providersLoaded && !isRefreshing) void loadProviders(false);
  }, [tab, providersLoaded, isRefreshing, loadProviders]);

  const handleOrgAction = async (org: Organization, action: "suspend" | "reactivate" | "offboard") => {
    try {
      await apiClient.post(`/admin/orgs/${org.id}/${action}`);
      toast.success(`${org.name} ${action === "suspend" ? "suspended" : action === "reactivate" ? "reactivated" : "offboarded"}`);
      setOffboardTarget(null);
      void fetchAdminData();
    } catch (err: unknown) {
      toast.error(`Couldn't ${action} ${org.name}`, errorMessage(err, "Try again in a moment."));
    }
  };

  const handleUserToggleActive = async (member: User) => {
    try {
      await apiClient.patch(`/users/${member.id}`, { is_active: !member.is_active });
      toast.success(member.is_active ? "Account deactivated" : "Account activated", member.email);
      void fetchAdminData();
    } catch (err: unknown) {
      toast.error("Couldn't update the account", errorMessage(err, "Try again in a moment."));
    }
  };

  const handleApproveAccessRequest = async (req: AccessRequest) => {
    setProcessingReqId(req.id);
    try {
      await apiClient.post(`/access-requests/${req.id}/approve`);
      toast.success("Access approved", `${req.email} can now sign in.`);
      void fetchAdminData();
    } catch (err: unknown) {
      toast.error("Couldn't approve the request", errorMessage(err, "Try again in a moment."));
    } finally {
      setProcessingReqId(null);
    }
  };

  const handleConfirmRejectRequest = async () => {
    if (!rejectModalReq) return;
    setProcessingReqId(rejectModalReq.id);
    try {
      await apiClient.post(`/access-requests/${rejectModalReq.id}/reject`, { reason: rejectionReason.trim() || undefined });
      toast.success("Request declined", rejectModalReq.email);
      setRejectModalReq(null);
      setRejectionReason("");
      void fetchAdminData();
    } catch (err: unknown) {
      toast.error("Couldn't decline the request", errorMessage(err, "Try again in a moment."));
    } finally {
      setProcessingReqId(null);
    }
  };

  const pendingRequests = useMemo(() => accessRequests.filter((r) => r.status === "pending"), [accessRequests]);
  const filteredRequests = requestFilter === "pending" ? pendingRequests : accessRequests;

  const tabs = [
    { value: "requests", label: "Access requests", count: pendingRequests.length },
    ...(isSuperAdmin ? [{ value: "orgs", label: "Organizations", count: orgs.length }] : []),
    { value: "members", label: "Members", count: orgUsers.length },
    { value: "providers", label: "Providers", count: providersLoaded ? providers.length : undefined },
    { value: "audit", label: "Audit log" },
  ];

  if (user && !isAdmin) {
    return (
      <UnavailableState
        title="Administration isn't available to your account"
        description="Ask an administrator in your organization if you need access."
      />
    );
  }

  return (
    <>
      <PageHeader
        title="Administration"
        description="Review access requests, manage members and organizations, and check connected services."
        actions={
          <>
            <Button variant="secondary" onClick={() => void fetchAdminData()} isLoading={isLoading}>
              {!isLoading && <RefreshCw className="h-4 w-4" strokeWidth={1.5} />}
              Refresh
            </Button>
            <Button variant="secondary" onClick={handleRefreshProviders} isLoading={isRefreshing}>
              {!isRefreshing && <Server className="h-4 w-4" strokeWidth={1.5} />}
              Run health checks
            </Button>
          </>
        }
      />

      <Tabs value={tab} onValueChange={setTab} items={tabs} />

      {isLoading && accessRequests.length === 0 && orgUsers.length === 0 ? (
        <div className="space-y-3" role="status" aria-live="polite">
          <span className="sr-only">Loading administration data…</span>
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </div>
      ) : (
        <>
          {tab === "requests" && (
            <section className="space-y-4" aria-label="Access requests">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-fg-secondary">
                  {isSuperAdmin
                    ? "Requests for admin access and new organizations."
                    : `Requests to join ${user?.org_name || "your organization"} as a client viewer.`}
                </p>
                <div className="flex items-center gap-1 rounded-control border border-border bg-surface-subtle p-0.5">
                  {(
                    [
                      ["pending", `Pending (${pendingRequests.length})`],
                      ["all", `All (${accessRequests.length})`],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setRequestFilter(value)}
                      aria-pressed={requestFilter === value}
                      className={`focus-ring h-7 rounded-control px-3 text-caption font-medium transition-colors duration-fast ${
                        requestFilter === value ? "bg-surface text-fg" : "text-fg-secondary hover:text-fg"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {filteredRequests.length === 0 ? (
                <EmptyState
                  icon={UserCheck}
                  title={requestFilter === "pending" ? "No requests waiting" : "No access requests yet"}
                  description={requestFilter === "pending" ? "New requests appear here for review." : "Requests are listed here once people apply."}
                />
              ) : (
                <TableContainer>
                  <Table aria-label="Access requests">
                    <thead>
                      <tr>
                        <Th>Applicant</Th>
                        <Th>Organization</Th>
                        <Th>Requested role</Th>
                        <Th>Status</Th>
                        <Th>Submitted</Th>
                        <Th className="text-right">
                          <span className="sr-only">Actions</span>
                        </Th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRequests.map((req) => {
                        const isPending = req.status === "pending";
                        const isProcessing = processingReqId === req.id;
                        return (
                          <tr key={req.id} className="group bg-surface transition-colors duration-fast hover:bg-surface-subtle">
                            <Td>
                              <p className="text-sm font-medium text-fg">{req.full_name || "Applicant"}</p>
                              <p className="font-mono text-xs text-fg-tertiary">{req.email}</p>
                            </Td>
                            <Td className="text-sm text-fg">{req.org_name || req.org_id}</Td>
                            <Td>
                              <Badge variant={req.requested_role === "org_admin" ? "warning" : "neutral"} size="sm">
                                {roleLabel(req.requested_role)}
                              </Badge>
                            </Td>
                            <Td>
                              <StatusBadge tone={requestTone[req.status] ?? "neutral"}>{req.status}</StatusBadge>
                              {req.rejection_reason && (
                                <Tooltip content={req.rejection_reason}>
                                  <p className="mt-0.5 max-w-[14rem] truncate text-xs text-fg-tertiary">{req.rejection_reason}</p>
                                </Tooltip>
                              )}
                            </Td>
                            <Td>
                              <Tooltip content={formatDate(req.created_at)}>
                                <span className="text-caption text-fg-secondary">{formatRelative(req.created_at)}</span>
                              </Tooltip>
                            </Td>
                            <Td className="text-right">
                              {isPending ? (
                                <div className="flex items-center justify-end gap-2">
                                  <Button size="sm" isLoading={isProcessing} onClick={() => handleApproveAccessRequest(req)}>
                                    <Check className="h-4 w-4" strokeWidth={1.5} /> Approve
                                  </Button>
                                  <Button size="sm" variant="secondary" disabled={isProcessing} onClick={() => setRejectModalReq(req)}>
                                    <X className="h-4 w-4" strokeWidth={1.5} /> Decline
                                  </Button>
                                </div>
                              ) : (
                                <span className="text-caption text-fg-tertiary">
                                  {req.reviewed_at ? `Reviewed ${formatRelative(req.reviewed_at)}` : "Finalized"}
                                </span>
                              )}
                            </Td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                </TableContainer>
              )}
            </section>
          )}

          {tab === "orgs" && isSuperAdmin && (
            <section className="space-y-4" aria-label="Organizations">
              <p className="text-sm text-fg-secondary">Suspending an organization blocks sign-in immediately. Offboarding keeps its data.</p>
              {orgs.length === 0 ? (
                <EmptyState title="No organizations" description="Organizations appear here once they are created." />
              ) : (
                <TableContainer>
                  <Table aria-label="Organizations">
                    <thead>
                      <tr>
                        <Th>Organization</Th>
                        <Th>Slug</Th>
                        <Th>Status</Th>
                        <Th className="text-right">
                          <span className="sr-only">Actions</span>
                        </Th>
                      </tr>
                    </thead>
                    <tbody>
                      {orgs.map((org) => (
                        <tr key={org.id} className="group bg-surface transition-colors duration-fast hover:bg-surface-subtle">
                          <Td className="text-sm font-medium text-fg">{org.name}</Td>
                          <Td className="font-mono text-caption text-fg-secondary">{org.slug}</Td>
                          <Td>
                            <StatusBadge tone={org.is_active ? "success" : "danger"}>{org.is_active ? "Active" : "Suspended"}</StatusBadge>
                          </Td>
                          <Td className="text-right">
                            <div className="flex items-center justify-end gap-2">
                              {org.is_active ? (
                                <Button size="sm" variant="secondary" onClick={() => handleOrgAction(org, "suspend")}>
                                  <PowerOff className="h-4 w-4" strokeWidth={1.5} /> Suspend
                                </Button>
                              ) : (
                                <Button size="sm" variant="secondary" onClick={() => handleOrgAction(org, "reactivate")}>
                                  <Power className="h-4 w-4" strokeWidth={1.5} /> Reactivate
                                </Button>
                              )}
                              <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={() => setOffboardTarget(org)}>
                                Offboard
                              </Button>
                            </div>
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </TableContainer>
              )}
            </section>
          )}

          {tab === "members" && (
            <section className="space-y-4" aria-label="Members">
              <p className="text-sm text-fg-secondary">People with access to your organization.</p>
              {orgUsers.length === 0 ? (
                <EmptyState title="No members yet" description="Approved access requests create members." />
              ) : (
                <TableContainer>
                  <Table aria-label="Members">
                    <thead>
                      <tr>
                        <Th>Name</Th>
                        <Th>Email</Th>
                        <Th>Role</Th>
                        <Th>Status</Th>
                        <Th className="text-right">
                          <span className="sr-only">Actions</span>
                        </Th>
                      </tr>
                    </thead>
                    <tbody>
                      {orgUsers.map((member) => (
                        <tr key={member.id} className="group bg-surface transition-colors duration-fast hover:bg-surface-subtle">
                          <Td className="text-sm font-medium text-fg">{member.full_name || "—"}</Td>
                          <Td className="font-mono text-caption text-fg-secondary">{member.email}</Td>
                          <Td>
                            <Badge size="sm">{roleLabel(member.role)}</Badge>
                          </Td>
                          <Td>
                            <StatusBadge tone={member.is_active ? "success" : "danger"}>{member.is_active ? "Active" : "Deactivated"}</StatusBadge>
                          </Td>
                          <Td className="text-right">
                            {member.id !== user?.id && (
                              <Button size="sm" variant="ghost" onClick={() => handleUserToggleActive(member)}>
                                {member.is_active ? (
                                  <>
                                    <UserX className="h-4 w-4" strokeWidth={1.5} /> Deactivate
                                  </>
                                ) : (
                                  <>
                                    <UserCheck className="h-4 w-4" strokeWidth={1.5} /> Activate
                                  </>
                                )}
                              </Button>
                            )}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </TableContainer>
              )}
            </section>
          )}

          {tab === "providers" && (
            <section className="space-y-4" aria-label="Providers">
              <p className="text-sm text-fg-secondary">Services that are not configured are skipped and their signals stay unavailable.</p>
              {isRefreshing && !providersLoaded ? (
                <div className="space-y-3" role="status" aria-live="polite">
                  <span className="sr-only">Checking providers…</span>
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-11" />
                  ))}
                  <p className="text-caption text-fg-tertiary">Checking each connected service. This can take up to half a minute.</p>
                </div>
              ) : providers.length === 0 ? (
                <EmptyState title="No providers checked yet" description="Run the health checks to see each connection." actionLabel="Run health checks" onAction={handleRefreshProviders} />
              ) : (
                <TableContainer>
                  <Table aria-label="Providers">
                    <thead>
                      <tr>
                        <Th>Provider</Th>
                        <Th>Status</Th>
                        <Th>Details</Th>
                        <Th>Last checked</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {providers.map((p) => (
                        <tr key={p.name} className="group bg-surface transition-colors duration-fast hover:bg-surface-subtle">
                          <Td className="font-mono text-sm font-medium text-fg">{p.name}</Td>
                          <Td>
                            <StatusBadge tone={p.is_healthy ? "success" : p.is_configured ? "danger" : "neutral"}>
                              {p.is_healthy ? "Healthy" : p.is_configured ? "Error" : "Not configured"}
                            </StatusBadge>
                          </Td>
                          <Td className="max-w-[28rem]">
                            <Tooltip content={p.status_message}>
                              <p className="truncate text-caption text-fg-secondary">{p.status_message}</p>
                            </Tooltip>
                          </Td>
                          <Td>
                            <Tooltip content={formatDate(p.last_checked)}>
                              <span className="whitespace-nowrap text-caption text-fg-secondary">{formatRelative(p.last_checked)}</span>
                            </Tooltip>
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </TableContainer>
              )}
            </section>
          )}

          {tab === "audit" && (
            <section className="space-y-4" aria-label="Audit log">
              <p className="text-sm text-fg-secondary">Who changed what, and when. Entries can't be edited.</p>
              {auditLogs.length === 0 ? (
                <EmptyState title="No audit entries yet" description="Approvals, reveals, exports and settings changes are recorded here." />
              ) : (
                <TableContainer className="max-h-[calc(100dvh-var(--topbar-height)-20rem)]">
                  <Table aria-label="Audit log">
                    <thead>
                      <tr>
                        <Th>When</Th>
                        <Th>Action</Th>
                        <Th>Entity</Th>
                        <Th>Details</Th>
                        <Th>IP address</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLogs.map((log) => (
                        <tr key={log.id} className="group bg-surface transition-colors duration-fast hover:bg-surface-subtle">
                          <Td>
                            <Tooltip content={formatDate(log.created_at)}>
                              <span className="whitespace-nowrap text-caption text-fg-secondary">{formatRelative(log.created_at)}</span>
                            </Tooltip>
                          </Td>
                          <Td className="whitespace-nowrap font-mono text-caption font-medium text-fg">{log.action}</Td>
                          <Td className="text-caption text-fg-secondary">{log.entity_type}</Td>
                          <Td className="max-w-[24rem]">
                            <Tooltip content={JSON.stringify(log.changes)}>
                              <p className="truncate font-mono text-xs text-fg-tertiary">{JSON.stringify(log.changes)}</p>
                            </Tooltip>
                          </Td>
                          <Td className="font-mono text-xs text-fg-tertiary">{log.ip_address || "internal"}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </TableContainer>
              )}
            </section>
          )}
        </>
      )}

      <Modal
        isOpen={!!rejectModalReq}
        onClose={() => {
          setRejectModalReq(null);
          setRejectionReason("");
        }}
        title="Decline this request?"
        description={rejectModalReq ? `${rejectModalReq.email} asked for ${roleLabel(rejectModalReq.requested_role).toLowerCase()} access.` : undefined}
      >
        <div className="space-y-4">
          <Input
            label="Reason (optional)"
            helper="Shown to the applicant."
            placeholder="e.g. We couldn't verify this organization."
            value={rejectionReason}
            onChange={(e) => setRejectionReason(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setRejectModalReq(null);
                setRejectionReason("");
              }}
            >
              Cancel
            </Button>
            <Button variant="destructive" isLoading={!!processingReqId} onClick={handleConfirmRejectRequest}>
              Decline request
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={!!offboardTarget}
        onClose={() => setOffboardTarget(null)}
        title={offboardTarget ? `Offboard ${offboardTarget.name}?` : "Offboard organization"}
        description="Members lose access. Leads, scores and audit history are kept."
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOffboardTarget(null)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => offboardTarget && handleOrgAction(offboardTarget, "offboard")}>
            Offboard organization
          </Button>
        </div>
      </Modal>
    </>
  );
}
