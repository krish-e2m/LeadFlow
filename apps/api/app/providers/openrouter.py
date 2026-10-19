import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.filter_catalog import FilterValidationError, validate_and_normalize_filters
from app.providers.base import BaseProviderAdapter, ProviderStatus
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS, SIGNAL_CATEGORIES, SIGNAL_LABELS, validate_engine_weights
from app.scoring.engine import ranked_findings


class OpenRouterError(Exception):
    """Base exception for OpenRouter operations."""
    pass


class OpenRouterConfigurationError(OpenRouterError):
    """Raised when OpenRouter is unconfigured."""
    pass


class OpenRouterAuthenticationError(OpenRouterError):
    """Raised on provider authentication failures."""
    pass


class OpenRouterRateLimitError(OpenRouterError):
    """Raised on provider rate limits."""
    pass


class OpenRouterTimeoutError(OpenRouterError):
    """Raised when provider request times out."""
    pass


class OpenRouterAPIError(OpenRouterError):
    """Raised on upstream provider errors."""
    pass


class OpenRouterParsingError(OpenRouterError):
    """Raised when model returns non-JSON or malformed payload."""
    pass


class OpenRouterValidationError(OpenRouterError):
    """Raised when model output fails filter catalog validation."""
    pass


DRAFT_MAX_TOKENS = 1500


class OpenRouterAdapter(BaseProviderAdapter):
    """
    OpenRouter AI integration for audit interpretation, personalized proposals,
    and structured outbound draft generation using frontier LLMs.
    """

    def __init__(self):
        super().__init__("openrouter")
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = settings.OPENROUTER_BASE_URL
        self.default_model = settings.OPENROUTER_DEFAULT_MODEL
        self.fast_model = settings.OPENROUTER_FAST_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="OpenRouter API key not configured.",
                last_checked=datetime.now(timezone.utc),
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                is_ok = res.status_code == 200
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_ok,
                    status_message="Connected to OpenRouter"
                    if is_ok
                    else f"Auth error HTTP {res.status_code}",
                    last_checked=datetime.now(timezone.utc),
                )
        except Exception as e:
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Healthcheck error: {str(e)}",
                last_checked=datetime.now(timezone.utc),
            )

    async def generate_outreach_draft(
        self,
        company_name: str,
        domain: str,
        contact_name: Optional[str],
        contact_title: Optional[str],
        score: float,
        score_band: str,
        signal_details: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates personalized B2B outreach draft citing concrete audit findings.
        Returns subject, body, model used, and list of citations.
        """
        if not self.is_configured():
            raise RuntimeError(
                "OpenRouter API key is not configured. AI draft generation cannot proceed."
            )

        chosen_model = model or self.default_model

        # Cite the strongest pain points first (weight x value), never a disabled signal.
        active_citations = [
            {"signal": f["signal"], "label": f["label"], "finding": f["finding"]}
            for f in ranked_findings(signal_details or {})
            if f["finding"]
        ]

        prompt = f"""You are an elite B2B sales development representative writing a high-converting, personalized cold outreach email.

Target Company: {company_name} ({domain})
Recipient: {contact_name or "Leader"} ({contact_title or "Decision Maker"})
Overall Audit Score: {score}/100 ({score_band})

Verified Audit Findings from Technical Crawl:
{json.dumps(active_citations[:4], indent=2)}

Guidelines:
1. Subject line: Short (3-6 words), curiosity-inducing, relevant.
2. Email body: 75-125 words max. Cite 1-2 specific concrete technical findings from the audit findings above.
3. Tone: Direct, consultative, highly professional, zero fluff or generic compliments.
4. Call to Action: Low-friction question (e.g., "Open to seeing the 2-minute diagnostic tear-down?").
5. Return strictly valid JSON with keys: "subject", "body", "citations_used".
"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-Title": settings.OPENROUTER_SITE_NAME,
            "Content-Type": "application/json",
        }

        body = {
            "model": chosen_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You output strictly valid JSON with keys: subject, body, citations_used.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            # Reasoning models spend part of max_tokens thinking; with 500 tokens the email was cut
            # off. Keep reasoning light and out of the reply, and leave room for the JSON.
            "max_tokens": DRAFT_MAX_TOKENS,
            "reasoning": {"effort": "low", "exclude": True},
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=body
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"OpenRouter draft generation failed: HTTP {resp.status_code} - {resp.text}"
                )

            result = resp.json()
            choice = result.get("choices", [{}])[0]
            msg = choice.get("message", {})
            raw_content = msg.get("content") or ""

            import re
            parsed: Dict[str, Any] = {}
            match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            if match:
                try:
                    # strict=False accepts raw line breaks inside strings, which models sometimes emit.
                    parsed = json.loads(match.group(0), strict=False)
                except Exception:
                    parsed = {}

            subject = str(parsed.get("subject") or "").strip()
            body_text = str(parsed.get("body") or "").strip()
            if not subject or not body_text:
                # Never save a generic placeholder as if it were a written email.
                reason = "the reply was cut off" if choice.get("finish_reason") == "length" else "the reply wasn't valid JSON"
                raise OpenRouterParsingError(f"The AI didn't return a usable email ({reason}). Try again.")

            return {
                "subject": subject[:255],
                "body": body_text,
                "citations_used": parsed.get("citations_used", active_citations[:2]),
                "model_used": chosen_model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def generate_icp_criteria(
        self, prompt: str, allow_offline_heuristic: bool = False
    ) -> Dict[str, Any]:
        """
        Parses natural language prompt into structured ICP target criteria.
        Extracts audience name, description, ai_rationale, canonical filters (verticals,
        locations, exclusions, matching modes), and backward-compatible fields.
        Validates all output strictly against filter_catalog.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        # Truthful configuration check: reject if unconfigured unless explicitly in offline testing mode
        if not self.is_configured():
            if allow_offline_heuristic:
                return self._heuristic_icp_parse(prompt)
            raise OpenRouterConfigurationError(
                "OpenRouter API key is not configured. Please configure OPENROUTER_API_KEY in your environment."
            )

        chosen_model = self.fast_model or self.default_model

        system_instruction = (
            "You are an expert B2B go-to-market ICP strategist.\n"
            "Given a target market description or business brief, propose structured ICP parameters strictly as JSON.\n"
            "Return valid JSON ONLY with the exact keys:\n"
            "- name: short descriptive audience title (e.g. 'Gujarat SME Digital Growth')\n"
            "- description: concise 1-sentence summary\n"
            "- ai_rationale: 1-2 sentence evidence-grounded explanation of why these filters match the brief. If the brief describes a service being offered rather than a client industry, explicitly note that the target industry is left broad/unrestricted.\n"
            "- filters: object with the following supported keys ONLY:\n"
            "    * verticals: list of prospective client market verticals (e.g. ['Manufacturing', 'Healthcare', 'B2B SaaS']). Leave empty [] if the brief does not specify the target client's industry.\n"
            "    * vertical_match: 'or' (default) or 'and'\n"
            "    * locations: list of target cities/regions (e.g. ['Ahmedabad', 'Surat']). PRESERVE user requested cities/regions exactly.\n"
            "    * location_match: 'or' (default) or 'and'\n"
            "    * exclude_locations: list of locations to drop\n"
            "    * exclude_verticals: list of verticals to drop\n"
            "    * exclude_domains: list of competitor or client domains to drop\n"
            "    * exclude_existing_crm: boolean (default false)\n"
            "    * industries: list of industry categories (consistent with verticals)\n"
            "    * employee_ranges: list of headcount brackets (e.g. ['11-50', '51-200'])\n"
            "    * technologies: list of relevant software/tools (e.g. ['WordPress', 'Shopify'])\n"
            "    * keywords: list of strategic search keywords (e.g. ['SaaS', 'B2B'])\n"
            "    * target_roles: list of target executive job titles (e.g. ['CEO', 'Founder', 'Managing Director'])\n"
            "CRITICAL RULES:\n"
            "1. DISTINGUISH SERVICE SOLD FROM TARGET CLIENT INDUSTRY: Do NOT confuse the vendor's service with the prospective customer's industry. If the brief mentions selling website development, SEO, digital marketing, or consulting, do NOT put those services into 'verticals' unless the user explicitly stated they want to sell to other agencies.\n"
            "2. DO NOT INVENT INDUSTRIES: If the brief targets general businesses (e.g. 'businesses in Ahmedabad needing websites'), set verticals to [] and explain in ai_rationale that any business industry qualifies.\n"
            "3. vertical_match and location_match MUST default to 'or'.\n"
            "4. Preserve any cities, states, or regions explicitly specified by the user (such as Ahmedabad and Surat).\n"
            "5. Do NOT include markdown code blocks, backticks, or explanatory text outside the JSON object.\n"
            "6. Return valid JSON only."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-Title": settings.OPENROUTER_SITE_NAME,
            "Content-Type": "application/json",
        }

        body = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": f"Parse this ICP criteria prompt into structured filters and rationale:\n\n{prompt.strip()}",
                },
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=body
                )
        except httpx.TimeoutException:
            raise OpenRouterTimeoutError("OpenRouter request timed out after 20 seconds. Please try again.")
        except httpx.RequestError as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            raise OpenRouterAPIError(f"OpenRouter network transport error: {safe_e}")

        # Truthful status code handling
        if resp.status_code in (401, 403):
            raise OpenRouterAuthenticationError(
                f"OpenRouter authentication failed (HTTP {resp.status_code}). Please verify OPENROUTER_API_KEY."
            )
        elif resp.status_code == 429:
            raise OpenRouterRateLimitError(
                "OpenRouter rate limit exceeded (HTTP 429). Please try again shortly."
            )
        elif resp.status_code != 200:
            raise OpenRouterAPIError(
                f"OpenRouter provider returned error HTTP {resp.status_code}."
            )

        try:
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
        except Exception as e:
            raise OpenRouterParsingError(f"Failed to decode response from OpenRouter: {e}")

        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise OpenRouterParsingError("LLM response did not contain a valid JSON object.")

        try:
            parsed = json.loads(match.group(0))
        except Exception as e:
            raise OpenRouterParsingError(f"Malformed JSON returned by LLM: {e}")

        raw_filters = parsed.get("filters")
        if not isinstance(raw_filters, dict):
            raise OpenRouterValidationError("LLM response missing 'filters' object.")

        try:
            validated_filters = validate_and_normalize_filters(raw_filters)
        except FilterValidationError as e:
            raise OpenRouterValidationError(f"Generated filters failed catalog validation: {e}")

        ai_rationale = parsed.get("ai_rationale")
        if not ai_rationale or not str(ai_rationale).strip():
            target_locs = validated_filters.get("locations") or ["target markets"]
            target_verts = (
                validated_filters.get("verticals")
                or validated_filters.get("industries")
                or ["target sector"]
            )
            ai_rationale = (
                f"Targeting {', '.join(target_verts)} in {', '.join(target_locs)} "
                f"with default OR matching for broad addressable reach."
            )

        return {
            "name": str(parsed.get("name") or "Custom ICP Profile").strip(),
            "description": str(parsed.get("description") or prompt.strip()[:150]).strip(),
            "ai_rationale": str(ai_rationale).strip(),
            "filters": validated_filters,
            "model_used": chosen_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _heuristic_icp_parse(self, prompt: str) -> Dict[str, Any]:
        """Deterministic offline keyword extractor for offline testing and dev environments."""
        p_lower = prompt.lower()

        # Detect locations
        known_locs = {
            "ahmedabad": "Ahmedabad",
            "surat": "Surat",
            "mumbai": "Mumbai",
            "delhi": "Delhi",
            "bangalore": "Bangalore",
            "bengaluru": "Bangalore",
            "us": "United States",
            "usa": "United States",
            "united states": "United States",
            "canada": "Canada",
            "uk": "United Kingdom",
            "united kingdom": "United Kingdom",
            "europe": "Europe",
            "germany": "Germany",
            "australia": "Australia",
            "india": "India",
            "north america": "North America",
            "global": "Global",
        }
        detected_locs = [v for k, v in known_locs.items() if k in p_lower]
        if not detected_locs:
            detected_locs = ["United States"]

        # Check if the prompt describes offering services (e.g. web development, marketing, SEO)
        # vs. targeting a specific client business industry
        service_offering_phrases = [
            "benefit from a better website",
            "benefit from a website",
            "need a better website",
            "need a website",
            "needing a better website",
            "needing a website",
            "needing website",
            "better website",
            "website development service",
            "web development service",
            "digital marketing service",
            "marketing service",
            "seo service",
        ]
        is_service_offering = any(phrase in p_lower for phrase in service_offering_phrases)

        # Detect genuine prospective customer verticals/industries
        customer_industry_map = {
            "saas": "B2B SaaS",
            "software": "Computer Software",
            "fintech": "Fintech & Banking",
            "ecommerce": "E-Commerce & Retail",
            "e-commerce": "E-Commerce & Retail",
            "retail": "Retail",
            "healthcare": "Healthcare & MedTech",
            "health": "Healthcare",
            "medtech": "Medical Technology",
            "real estate": "Real Estate",
            "manufacturing": "Manufacturing & Logistics",
            "edtech": "Education & EdTech",
            "education": "Education",
            "hospitality": "Hospitality & Tourism",
        }

        # If user explicitly states they want to target agencies
        if "target agency" in p_lower or "target agencies" in p_lower or "marketing agencies" in p_lower:
            customer_industry_map["agency"] = "Marketing & Advertising"

        detected_industries = []
        for kw, ind in customer_industry_map.items():
            if kw in p_lower and ind not in detected_industries:
                detected_industries.append(ind)

        # Distinguish service sold from customer target industry
        if is_service_offering and not detected_industries:
            detected_industries = []
            rationale_text = (
                f"Targeting businesses in {', '.join(detected_locs)} based on location and company size. "
                f"Target industry was left unrestricted across all sectors because the brief describes a general service offering ('website development / digital marketing') rather than restricting to a specific customer vertical."
            )
        elif not detected_industries:
            detected_industries = []
            rationale_text = (
                f"Targeting organizations in {', '.join(detected_locs)} matching specified criteria. "
                f"Target industry was left unrestricted because the brief did not specify a target customer vertical."
            )
        else:
            rationale_text = (
                f"Generated deterministic filters targeting {', '.join(detected_industries)} in {', '.join(detected_locs)} "
                f"matching headcount criteria."
            )

        # Detect employee ranges
        ranges = []
        if any(w in p_lower for w in ["startup", "early stage", "1-10", "small team"]):
            ranges.append("1-10")
        if any(w in p_lower for w in ["11-50", "20-50", "seed", "boutique", "small and medium", "sme", "smb"]):
            ranges.append("11-50")
        if any(w in p_lower for w in ["50-200", "51-200", "mid-market", "series a", "series b", "medium"]):
            ranges.append("51-200")
        if any(w in p_lower for w in ["201-500", "200-500", "growing"]):
            ranges.append("201-500")
        if any(w in p_lower for w in ["enterprise", "500+", "large", "corporate"]):
            ranges.append("500+")
        if not ranges:
            ranges = ["11-50", "51-200"]

        # Detect technologies
        known_tech = ["hubspot", "salesforce", "shopify", "wordpress", "magento", "stripe", "react", "next.js", "aws", "google analytics"]
        detected_tech = [t.capitalize() for t in known_tech if t in p_lower]

        # Detect roles
        known_roles = ["ceo", "founder", "cto", "cmo", "vp sales", "vp marketing", "head of growth", "director of marketing", "operations manager"]
        detected_roles = [r.title() for r in known_roles if r in p_lower]
        if not detected_roles:
            detected_roles = ["CEO", "Founder", "Managing Director"]

        main_ind = detected_industries[0] if detected_industries else "SMB Discovery"
        main_loc = detected_locs[0] if detected_locs else "Global"
        name = f"{main_loc} {main_ind} ICP"

        raw_filters = {
            "verticals": list(dict.fromkeys(detected_industries)),
            "vertical_match": "or",
            "locations": list(dict.fromkeys(detected_locs)),
            "location_match": "or",
            "exclude_locations": [],
            "exclude_verticals": [],
            "exclude_domains": [],
            "exclude_existing_crm": False,
            "industries": list(dict.fromkeys(detected_industries)),
            "employee_ranges": list(dict.fromkeys(ranges)),
            "technologies": detected_tech,
            "keywords": [w for w in ["SaaS", "Growth", "B2B", "Enterprise", "Marketing", "Website"] if w.lower() in p_lower] or ["B2B"],
            "target_roles": detected_roles,
        }

        normalized = validate_and_normalize_filters(raw_filters)

        return {
            "name": name,
            "description": prompt.strip()[:150],
            "ai_rationale": rationale_text,
            "filters": normalized,
            "model_used": "offline-heuristic-parser",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def generate_engine_weights(
        self, prompt: str, allow_offline_heuristic: bool = False
    ) -> Dict[str, Any]:
        """
        Parses an ideal-client brief into proposed weights for the fixed 22-signal catalog, plus
        qualified/review thresholds and an ideal-client bonus. Never spends Apollo credits or
        touches a lead — this only proposes a configuration for a human to review before saving
        (docs/poc.md 8.2: "AI never auto-runs searches or spends Apollo credits").
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if not self.is_configured():
            if allow_offline_heuristic:
                return self._heuristic_engine_weights(prompt)
            raise OpenRouterConfigurationError(
                "OpenRouter API key is not configured. Please configure OPENROUTER_API_KEY in your environment."
            )

        chosen_model = self.fast_model or self.default_model
        catalog_lines = "\n".join(
            f"  * {key} ({SIGNAL_CATEGORIES[key].value}): \"{SIGNAL_LABELS[key]}\", default weight {DEFAULT_SIGNAL_WEIGHTS[key]}"
            for key in DEFAULT_SIGNAL_WEIGHTS
        )

        system_instruction = (
            "You are an expert B2B lead-qualification strategist configuring a 22-signal scoring engine.\n"
            "The engine scores a company's website and marketing presence on 22 fixed signals (you cannot add, "
            "rename or remove signals — only re-weight them). Every signal is a WEAKNESS: a higher weight means "
            "that weakness, if detected, counts MORE toward making the company a strong lead (someone who needs "
            "the service described in the brief). This is the opposite of 'how good the signal is' — a company "
            "with excellent SEO scores LOW on poor_seo, which is what we want: low score = not a good lead.\n\n"
            "The fixed 22-signal catalog, with key, category and current default weight:\n"
            f"{catalog_lines}\n\n"
            "Given a brief describing the kind of client the user wants to find (what service they sell, what "
            "weaknesses matter most to them), propose:\n"
            "- weights: an object with ALL 22 keys above (you may keep a key at its default if the brief gives no "
            "reason to change it). Raise weights for signals that most strongly indicate this is a good lead for "
            "the stated service; lower (never below 0.1) ones the brief implies don't matter. Stay within 0.1-3.0.\n"
            "- threshold_high: the minimum overall score (0-100) for the 'Qualified' band. Default 75.\n"
            "- threshold_medium: the minimum overall score (0-100) for the 'Review' band; must be less than "
            "threshold_high. Below this is 'Disqualified'. Default 50.\n"
            "- ideal_client_bonus: 0-20 bonus points applied only when BOTH the website-signal group and the "
            "marketing-signal group score 50+. Raise this if the brief explicitly wants clients who need both a "
            "new website AND marketing help; otherwise leave near 0.\n"
            "- ai_rationale: 1-3 sentences explaining which signals you emphasized and why, grounded in the brief.\n\n"
            "Return valid JSON ONLY, no markdown, no backticks, no text outside the JSON object, with exactly "
            "these keys: weights, threshold_high, threshold_medium, ideal_client_bonus, ai_rationale."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-Title": settings.OPENROUTER_SITE_NAME,
            "Content-Type": "application/json",
        }

        body = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": f"Propose engine weights for this ideal-client brief:\n\n{prompt.strip()}",
                },
            ],
            "temperature": 0.2,
            "max_tokens": 1200,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        except httpx.TimeoutException:
            raise OpenRouterTimeoutError("OpenRouter request timed out after 20 seconds. Please try again.")
        except httpx.RequestError as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            raise OpenRouterAPIError(f"OpenRouter network transport error: {safe_e}")

        if resp.status_code in (401, 403):
            raise OpenRouterAuthenticationError(
                f"OpenRouter authentication failed (HTTP {resp.status_code}). Please verify OPENROUTER_API_KEY."
            )
        elif resp.status_code == 429:
            raise OpenRouterRateLimitError("OpenRouter rate limit exceeded (HTTP 429). Please try again shortly.")
        elif resp.status_code != 200:
            raise OpenRouterAPIError(f"OpenRouter provider returned error HTTP {resp.status_code}.")

        try:
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
        except Exception as e:
            raise OpenRouterParsingError(f"Failed to decode response from OpenRouter: {e}")

        import re
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise OpenRouterParsingError("LLM response did not contain a valid JSON object.")

        try:
            parsed = json.loads(match.group(0))
        except Exception as e:
            raise OpenRouterParsingError(f"Malformed JSON returned by LLM: {e}")

        raw_weights = parsed.get("weights")
        if not isinstance(raw_weights, dict):
            raise OpenRouterValidationError("LLM response missing a 'weights' object.")
        try:
            validated_weights = validate_engine_weights(raw_weights)
        except ValueError as e:
            raise OpenRouterValidationError(f"Generated weights failed catalog validation: {e}")

        try:
            threshold_high = float(parsed.get("threshold_high", 75.0))
            threshold_medium = float(parsed.get("threshold_medium", 50.0))
            ideal_client_bonus = float(parsed.get("ideal_client_bonus", 0.0))
        except (TypeError, ValueError):
            raise OpenRouterValidationError("LLM response thresholds/bonus must be numbers.")

        threshold_high = max(0.0, min(100.0, threshold_high))
        threshold_medium = max(0.0, min(100.0, threshold_medium))
        ideal_client_bonus = max(0.0, min(100.0, ideal_client_bonus))
        if threshold_medium > threshold_high:
            threshold_medium = max(0.0, threshold_high - 1.0)

        ai_rationale = str(parsed.get("ai_rationale") or "").strip()
        if not ai_rationale:
            ai_rationale = "Weights adjusted to emphasize the signals most relevant to the stated brief."

        return {
            "weights": validated_weights,
            "threshold_high": threshold_high,
            "threshold_medium": threshold_medium,
            "threshold_low": 25.0,
            "ideal_client_bonus": ideal_client_bonus,
            "ai_rationale": ai_rationale,
            "model_used": chosen_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _heuristic_engine_weights(self, prompt: str) -> Dict[str, Any]:
        """Deterministic offline keyword extractor, for offline testing and dev environments."""
        p_lower = prompt.lower()
        weights = dict(DEFAULT_SIGNAL_WEIGHTS)
        emphasized: List[str] = []

        # Keyword -> signals to raise. A brief can match several groups.
        emphasis_map = {
            "website": ["legacy_platform", "slow_site", "old_design", "not_mobile_friendly", "no_ssl"],
            "design": ["old_design", "weak_ctas"],
            "speed": ["slow_site"],
            "seo": ["poor_seo", "poor_aeo_geo", "low_domain_trust"],
            "search engine": ["poor_seo", "poor_aeo_geo"],
            "content": ["thin_content", "stale_blog", "no_case_studies"],
            "blog": ["stale_blog"],
            "social": ["weak_social"],
            "video": ["no_video"],
            "email": ["weak_email_capture"],
            "newsletter": ["weak_email_capture"],
            "ads": ["ppc_spend"],
            "ppc": ["ppc_spend"],
            "paid search": ["ppc_spend"],
            "press": ["no_press"],
            "pr ": ["no_press"],
            "reputation": ["low_review_rating"],
            "reviews": ["low_review_rating"],
            "hiring": ["hiring"],
            "growing": ["hiring"],
            "analytics": ["no_analytics"],
            "accessibility": ["accessibility"],
            "chat": ["no_live_chat"],
            "mobile": ["not_mobile_friendly"],
            "security": ["no_ssl"],
            "ssl": ["no_ssl"],
        }
        for kw, signal_keys in emphasis_map.items():
            if kw in p_lower:
                for key in signal_keys:
                    weights[key] = min(3.0, round(weights[key] * 1.5, 2))
                    if key not in emphasized:
                        emphasized.append(key)

        both_website_and_marketing = any(
            kw in p_lower for kw in ["website and marketing", "website & marketing", "new website and", "web and marketing"]
        )
        ideal_client_bonus = 10.0 if both_website_and_marketing else 0.0

        if emphasized:
            labels = ", ".join(SIGNAL_LABELS[k] for k in emphasized[:5])
            rationale = f"Raised weights on signals matching the brief: {labels}."
        else:
            rationale = "No specific emphasis detected in the brief; kept the catalog's default weights."
        if both_website_and_marketing:
            rationale += " Added an ideal-client bonus since the brief wants clients needing both services."

        return {
            "weights": weights,
            "threshold_high": 75.0,
            "threshold_medium": 50.0,
            "threshold_low": 25.0,
            "ideal_client_bonus": ideal_client_bonus,
            "ai_rationale": rationale,
            "model_used": "offline-heuristic-parser",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
