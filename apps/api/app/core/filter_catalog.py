"""
Single source of truth for LeadFlow ICP filter catalog, canonical schema, and validation.
Complies with LeadFlow POC Specification (Section 8.1).

Supported Filter Catalog:
- Canonical Fields:
  * verticals: list[str] - Target industries/verticals
  * vertical_match: 'or' | 'and' - Matching logic (defaults to 'or')
  * locations: list[str] - Target geographic regions/cities (e.g. ['Ahmedabad', 'Surat'])
  * location_match: 'or' | 'and' - Matching logic (defaults to 'or')
  * exclude_locations: list[str] - Locations to drop from sourcing pool
  * exclude_verticals: list[str] - Verticals to drop from sourcing pool
  * exclude_domains: list[str] - Explicit domains to drop from sourcing pool
  * exclude_existing_crm: bool - Whether to skip contacts already synced to CRM (defaults to False)

- Backward-Compatible Extension Fields:
  * industries: list[str] - Extended industry tags
  * employee_ranges: list[str] - Headcount brackets (e.g. ['11-50', '51-200'])
  * technologies: list[str] - Target software/tools detected (e.g. ['HubSpot', 'Shopify'])
  * keywords: list[str] - Thematic search keywords
  * target_roles: list[str] - Target buyer/decision-maker job titles (e.g. ['CEO', 'VP Sales'])

Provider Mapping Compatibility:
- Hunter.io (Discover POST /discover & Company Enrichment GET /companies/find):
  * locations -> headquarters_location (City + ISO country code mapping)
  * verticals, industries -> industry.include
  * exclude_verticals -> industry.exclude & downstream pipeline filtering
  * employee_ranges -> headcount (Native bracket mapping)
  * keywords -> keywords.include
  * technologies -> technologies
  * exclude_domains -> Filtered out during prospect ingestion pipeline
  * exclude_existing_crm -> Filtered out against synced leads in PostgreSQL
  * target_roles -> Used for Hunter /domain-search executive contact filtering
"""

from typing import Any, Dict, List, Optional, Set

CANONICAL_FILTER_FIELDS: Set[str] = {
    "verticals",
    "vertical_match",
    "locations",
    "location_match",
    "exclude_locations",
    "exclude_verticals",
    "exclude_domains",
    "exclude_existing_crm",
}

COMPAT_FILTER_FIELDS: Set[str] = {
    "industries",
    "employee_ranges",
    "technologies",
    "keywords",
    "target_roles",
}

ALL_ALLOWED_FILTER_KEYS: Set[str] = CANONICAL_FILTER_FIELDS | COMPAT_FILTER_FIELDS

LIST_STRING_FIELDS: Set[str] = {
    "verticals",
    "locations",
    "exclude_locations",
    "exclude_verticals",
    "exclude_domains",
    "industries",
    "employee_ranges",
    "technologies",
    "keywords",
    "target_roles",
}


class FilterValidationError(ValueError):
    """Raised when an ICP filter payload fails catalog validation."""
    pass


def validate_and_normalize_filters(raw: Any) -> Dict[str, Any]:
    """
    Validates and normalizes an ICP filter dictionary against the supported catalog.

    Rules:
    - Must be a dictionary.
    - Unsupported keys are strictly rejected.
    - vertical_match and location_match must be 'or' or 'and', defaulting to 'or'.
    - exclude_existing_crm must be a boolean, defaulting to False.
    - List fields must contain valid non-empty strings (whitespace trimmed, deduplicated).
    - Returns a normalized dictionary with canonical defaults applied.
    """
    if not isinstance(raw, dict):
        raise FilterValidationError(f"Filters must be a JSON dictionary, got {type(raw).__name__}.")

    # 1. Reject unsupported keys
    unsupported = set(raw.keys()) - ALL_ALLOWED_FILTER_KEYS
    if unsupported:
        sorted_unsupported = sorted(list(unsupported))
        raise FilterValidationError(
            f"Unsupported filter key(s): {', '.join(sorted_unsupported)}. "
            f"Allowed keys are: {', '.join(sorted(list(ALL_ALLOWED_FILTER_KEYS)))}."
        )

    normalized: Dict[str, Any] = {}

    # 2. Canonical matching modes (defaults to 'or')
    v_match = raw.get("vertical_match")
    if v_match is None or v_match == "":
        normalized["vertical_match"] = "or"
    elif isinstance(v_match, str) and v_match.lower() in ("or", "and"):
        normalized["vertical_match"] = v_match.lower()
    else:
        raise FilterValidationError(
            f"Invalid vertical_match: '{v_match}'. Must be 'or' or 'and'."
        )

    l_match = raw.get("location_match")
    if l_match is None or l_match == "":
        normalized["location_match"] = "or"
    elif isinstance(l_match, str) and l_match.lower() in ("or", "and"):
        normalized["location_match"] = l_match.lower()
    else:
        raise FilterValidationError(
            f"Invalid location_match: '{l_match}'. Must be 'or' or 'and'."
        )

    # 3. Canonical boolean flag (defaults to False)
    exclude_crm = raw.get("exclude_existing_crm")
    if exclude_crm is None:
        normalized["exclude_existing_crm"] = False
    elif isinstance(exclude_crm, bool):
        normalized["exclude_existing_crm"] = exclude_crm
    else:
        raise FilterValidationError(
            f"Invalid exclude_existing_crm: '{exclude_crm}'. Must be a boolean (true/false)."
        )

    # 4. Canonical and compatible list[str] fields
    for field in LIST_STRING_FIELDS:
        val = raw.get(field)
        if val is None:
            normalized[field] = []
        elif isinstance(val, list):
            cleaned: List[str] = []
            for item in val:
                if not isinstance(item, str):
                    raise FilterValidationError(
                        f"Field '{field}' must contain strings only, found {type(item).__name__} ({item})."
                    )
                trimmed = item.strip()
                if trimmed and trimmed not in cleaned:
                    cleaned.append(trimmed)
            normalized[field] = cleaned
        else:
            raise FilterValidationError(
                f"Field '{field}' must be a list of strings, got {type(val).__name__}."
            )

    # 5. Keep canonical 'verticals' and backward-compatible 'industries' synchronized
    if normalized.get("verticals") and not normalized.get("industries"):
        normalized["industries"] = list(normalized["verticals"])
    elif normalized.get("industries") and not normalized.get("verticals"):
        normalized["verticals"] = list(normalized["industries"])

    return normalized


SEARCH_ALLOWED_KEYS: Set[str] = ALL_ALLOWED_FILTER_KEYS | {"domains", "industry"}


def validate_and_normalize_search_params(raw: Any) -> Dict[str, Any]:
    """
    Validates and normalizes query_params supplied when creating a search.
    Supports direct prospect domains plus any valid catalog filters.
    Strictly rejects unsupported keys.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise FilterValidationError(f"Search query_params must be a dictionary, got {type(raw).__name__}.")

    unsupported = set(raw.keys()) - SEARCH_ALLOWED_KEYS
    if unsupported:
        sorted_unsupported = sorted(list(unsupported))
        raise FilterValidationError(
            f"Unsupported search parameter key(s): {', '.join(sorted_unsupported)}. "
            f"Allowed keys are: {', '.join(sorted(list(SEARCH_ALLOWED_KEYS)))}."
        )

    normalized: Dict[str, Any] = {}

    # Handle direct domains
    if "domains" in raw:
        val = raw["domains"]
        if val is None:
            normalized["domains"] = []
        elif isinstance(val, list):
            cleaned_domains: List[str] = []
            for d in val:
                if not isinstance(d, str):
                    raise FilterValidationError(f"Domain item must be a string, got {type(d).__name__}.")
                clean_d = d.strip().replace("https://", "").replace("http://", "").split("/")[0].lower()
                if clean_d and clean_d not in cleaned_domains:
                    cleaned_domains.append(clean_d)
            normalized["domains"] = cleaned_domains
        elif isinstance(val, str):
            cleaned_domains = [
                d.strip().replace("https://", "").replace("http://", "").split("/")[0].lower()
                for d in val.split("\n")
                if d.strip()
            ]
            normalized["domains"] = list(dict.fromkeys(cleaned_domains))
        else:
            raise FilterValidationError(f"Field 'domains' must be a list or string, got {type(val).__name__}.")

    # Handle singular 'industry' alias
    raw_copy = dict(raw)
    if "industry" in raw_copy and "industries" not in raw_copy:
        ind_val = raw_copy.pop("industry")
        if isinstance(ind_val, str):
            raw_copy["industries"] = [ind_val]
        elif isinstance(ind_val, list):
            raw_copy["industries"] = ind_val

    # Normalize remaining filter fields
    filter_keys = set(raw_copy.keys()) - {"domains"}
    if filter_keys:
        filter_subset = {k: raw_copy[k] for k in filter_keys}
        normalized_filters = validate_and_normalize_filters(filter_subset)
        normalized.update(normalized_filters)

    return normalized


def resolve_effective_search_params(
    audience_filters: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Combines persisted audience criteria with user-provided search overrides.
    Precedence:
    1. Base: Persisted audience filters (validated & normalized).
    2. Overrides: Explicit user overrides (e.g. direct domains or manual criteria refinements).
       Only keys explicitly present in the overrides payload replace the audience baseline.
    """
    normalized_audience = validate_and_normalize_filters(audience_filters or {})
    effective: Dict[str, Any] = dict(normalized_audience)

    if overrides:
        normalized_overrides = validate_and_normalize_search_params(overrides)
        explicit_keys = set(overrides.keys())
        if "industry" in explicit_keys:
            explicit_keys.add("industries")
            explicit_keys.add("verticals")
        if "industries" in explicit_keys:
            explicit_keys.add("verticals")
        if "verticals" in explicit_keys:
            explicit_keys.add("industries")

        for key in explicit_keys:
            if key in normalized_overrides:
                val = normalized_overrides[key]
                if val is not None and val != [] and val != "":
                    effective[key] = val
                elif key == "domains" and isinstance(val, list):
                    effective["domains"] = val
                elif isinstance(val, bool):
                    effective[key] = val

    return effective
