export type UserRole = "super_admin" | "org_admin" | "client_viewer";

export type PipelineStatus =
  | "sourced"
  | "enriching"
  | "enriched"
  | "scoring"
  | "scored"
  | "approved"
  | "disqualified"
  | "drafting"
  | "drafted"
  | "synced";

export type ScoreBand =
  | "qualified"
  | "review"
  | "disqualified"
  | "high"
  | "medium"
  | "low"
  | "unscored"
  | null;

export type ApprovalStatus = "pending" | "approved" | "rejected";

export type DraftApprovalStatus = "pending" | "approved" | "rejected";

export type CrmSyncStatus = "pending" | "success" | "failed";

export type RunStatus = "pending" | "running" | "completed" | "failed";

export type RunType = "search" | "enrichment" | "scoring" | "crm_sync";

export interface User {
  id: string;
  org_id: string | null;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  settings: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface Audience {
  id: string;
  org_id: string;
  name: string;
  description: string;
  filters: Record<string, unknown>;
  ai_rationale?: string | null;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScoringEngineParam {
  id: string;
  engine_id: string;
  version: number;
  weights: Record<string, number>;
  threshold_high: number;
  threshold_medium: number;
  threshold_low: number;
  ideal_client_bonus?: number;
  created_at: string;
}

export interface ScoringEngine {
  id: string;
  org_id: string;
  name: string;
  description: string;
  active_version: number;
  params?: ScoringEngineParam[];
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: string;
  org_id: string;
  search_id: string | null;
  run_type: RunType;
  status: RunStatus;
  progress_pct: number;
  items_total: number;
  items_processed: number;
  items_succeeded: number;
  items_failed: number;
  error_details: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface SignalDetailItem {
  label: string;
  category: "website" | "marketing";
  weight: number;
  value: number | null;
  status?: "detected" | "not_detected" | "unavailable";
  evidence: string | null;
  provider: string | null;
  is_available: boolean;
  source_url?: string | null;
}

export interface Score {
  id: string;
  lead_id: string;
  overall_score: number | null;
  score_band: ScoreBand;
  website_subscore: number | null;
  marketing_subscore: number | null;
  signal_details: Record<string, SignalDetailItem | any>;
  explanation: string | null;
  created_at: string;
}

export interface Enrichment {
  id: string;
  lead_id: string;
  version: number;
  payload: Record<string, unknown>;
  provider_provenance: Record<string, unknown>;
  created_at: string;
}

export interface Contact {
  id: string;
  lead_id: string;
  first_name: string | null;
  last_name: string | null;
  title: string | null;
  linkedin_url: string | null;
  email: string | null;
  phone: string | null;
  is_revealed: boolean;
  revealed_at: string | null;
  created_at: string;
}

export interface Draft {
  id: string;
  lead_id: string;
  contact_id: string | null;
  subject: string;
  body: string;
  model_used: string;
  audit_citations: Record<string, unknown>;
  approval_status: DraftApprovalStatus;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmSync {
  id: string;
  lead_id: string;
  draft_id: string | null;
  crm_provider: string;
  crm_contact_id: string | null;
  crm_company_id: string | null;
  crm_engagement_id: string | null;
  sync_status: CrmSyncStatus;
  retry_count: number;
  error_message: string | null;
  synced_at: string | null;
  created_at: string;
  already_synced?: boolean;
  crm_company_url?: string | null;
  crm_contact_url?: string | null;
}

export interface Lead {
  id: string;
  org_id: string;
  search_id: string | null;
  domain: string;
  company_name: string;
  industry: string | null;
  country: string | null;
  city: string | null;
  employee_count: number | null;
  pipeline_status: PipelineStatus;
  score_band: ScoreBand;
  approval_status: ApprovalStatus;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  scores?: Score[];
  enrichments?: Enrichment[];
  contacts?: Contact[];
  drafts?: Draft[];
  crm_syncs?: CrmSync[];
  /** Approval responses only: what happened to the automatic email draft. */
  auto_draft?: AutoDraftOutcome | null;
}

export type AutoDraftOutcome = "queued" | "exists" | "disabled" | "not_configured" | "unavailable";

export interface ContactRevealResult {
  contact: Contact;
  credits_remaining: number | null;
  message: string;
  already_revealed?: boolean;
  contacts_discovered?: number;
}

export interface ContactDiscoverResult {
  contacts: Contact[];
  created: number;
  message: string;
}

export interface ProviderStatus {
  name: string;
  is_configured: boolean;
  is_healthy: boolean;
  status_message: string;
  last_checked: string;
}

export interface AuditLog {
  id: string;
  org_id: string | null;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  changes: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface QuotaDetail {
  used: number;
  limit: number;
  remaining: number;
  period: string;
}

export interface UsageOverviewResponse {
  org_id: string | null;
  total_searches_run: number;
  total_leads_sourced: number;
  total_contacts_revealed: number;
  total_ai_drafts_generated: number;
  total_crm_syncs: number;
  credits_used?: number;
  credits_limit?: number;
  monthly_leads?: QuotaDetail;
  daily_contact_reveals?: QuotaDetail;
  daily_draft_generation?: QuotaDetail;
  concurrent_runs?: { used?: number; active?: number; limit: number; remaining: number };
  quotas?: {
    leads_monthly?: QuotaDetail;
    leads_per_search?: { limit: number };
    concurrent_runs?: { active: number; limit: number; remaining: number };
    contact_reveals_daily?: QuotaDetail;
    draft_generation_daily?: QuotaDetail;
    llm_monthly?: { used_usd: number; ceiling_usd: number; remaining_usd: number };
  };
}

export interface UsageMetrics {
  org_id: string | null;
  total_searches_run: number;
  total_leads_sourced: number;
  total_contacts_revealed: number;
  total_ai_drafts_generated: number;
  total_crm_syncs: number;
  credits_used: number;
  credits_limit: number;
}

export interface AccessRequest {
  id: string;
  org_id: string;
  org_name?: string | null;
  email: string;
  full_name: string | null;
  requested_role: UserRole;
  status: ApprovalStatus;
  rejection_reason?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublicOrganizationItem {
  id: string;
  name: string;
  slug: string;
}

