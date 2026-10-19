from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    CLIENT_VIEWER = "client_viewer"


class PipelineStatus(str, Enum):
    SOURCED = "sourced"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    SCORING = "scoring"
    SCORED = "scored"
    APPROVED = "approved"
    DISQUALIFIED = "disqualified"
    DRAFTING = "drafting"
    DRAFTED = "drafted"
    SYNCED = "synced"


class ScoreBand(str, Enum):
    QUALIFIED = "qualified"
    REVIEW = "review"
    DISQUALIFIED = "disqualified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNSCORED = "unscored"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DraftApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CrmSyncStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class RunType(str, Enum):
    SEARCH = "search"
    ENRICHMENT = "enrichment"
    SCORING = "scoring"
    CRM_SYNC = "crm_sync"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SignalCategory(str, Enum):
    WEBSITE = "website"
    MARKETING = "marketing"
