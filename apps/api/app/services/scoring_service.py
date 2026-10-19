import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PipelineStatus
from app.models.engine import ScoringEngine, ScoringEngineParam
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.models.score import Score
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.scoring.engine import ScoringEngineCore


class ScoringService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def score_lead(
        self,
        lead: Lead,
        enrichment: Optional[Enrichment] = None,
        engine_id: Optional[uuid.UUID] = None,
    ) -> Score:
        """
        Executes the 22-signal scoring engine against lead enrichment payload.
        Preserves score history without mutating previous calculations.
        Skips missing/None signal values without penalizing the overall prospect score.
        Preserves approval and pipeline status transitions.
        """
        initial_status = lead.pipeline_status
        if lead.pipeline_status in [
            PipelineStatus.SOURCED,
            PipelineStatus.ENRICHING,
            PipelineStatus.ENRICHED,
        ]:
            lead.pipeline_status = PipelineStatus.SCORING
            await self.session.flush()

        # 1. Fetch latest enrichment if not provided
        if not enrichment:
            stmt = (
                select(Enrichment)
                .where(Enrichment.lead_id == lead.id)
                .order_by(Enrichment.version.desc())
            )
            enrichment = (await self.session.execute(stmt)).scalars().first()

        if not enrichment:
            raise ValueError(f"Cannot score lead {lead.id}: no enrichment payload found.")

        # 2. Resolve active scoring engine parameters
        engine_param: Optional[ScoringEngineParam] = None
        if engine_id:
            p_stmt = (
                select(ScoringEngineParam)
                .where(ScoringEngineParam.engine_id == engine_id)
                .order_by(ScoringEngineParam.version.desc())
            )
            engine_param = (await self.session.execute(p_stmt)).scalars().first()

        if not engine_param:
            # Fallback to org default engine or create a baseline param if needed
            eng_stmt = (
                select(ScoringEngine)
                .where(ScoringEngine.org_id == lead.org_id)
                .order_by(ScoringEngine.created_at.asc())
            )
            org_engine = (await self.session.execute(eng_stmt)).scalars().first()
            if not org_engine:
                org_engine = ScoringEngine(
                    org_id=lead.org_id,
                    name="Default B2B ICP Engine",
                    description="Standard 22-signal weighted lead scoring profile",
                    active_version=1,
                )
                self.session.add(org_engine)
                await self.session.flush()

                engine_param = ScoringEngineParam(
                    engine_id=org_engine.id,
                    version=1,
                    weights=dict(DEFAULT_SIGNAL_WEIGHTS),
                    threshold_high=75.0,
                    threshold_medium=50.0,
                    threshold_low=25.0,
                )
                self.session.add(engine_param)
                await self.session.flush()
            else:
                p_stmt = (
                    select(ScoringEngineParam)
                    .where(ScoringEngineParam.engine_id == org_engine.id)
                    .order_by(ScoringEngineParam.version.desc())
                )
                engine_param = (await self.session.execute(p_stmt)).scalars().first()

        # 3. Instantiate Engine and Calculate Scores
        engine_core = ScoringEngineCore(
            weights=engine_param.weights if engine_param else None,
            threshold_high=engine_param.threshold_high if engine_param else 75.0,
            threshold_medium=engine_param.threshold_medium if engine_param else 50.0,
            threshold_low=engine_param.threshold_low if engine_param else 25.0,
            ideal_client_bonus=engine_param.ideal_client_bonus if engine_param else 0.0,
        )

        scoring_output = engine_core.evaluate(enrichment.payload)

        # 4. Persist Historical Score Record
        score_record = Score(
            org_id=lead.org_id,
            lead_id=lead.id,
            enrichment_id=enrichment.id,
            engine_param_id=engine_param.id,
            overall_score=scoring_output.overall_score,
            score_band=scoring_output.score_band,
            website_subscore=scoring_output.website_subscore,
            marketing_subscore=scoring_output.marketing_subscore,
            signal_details=scoring_output.signal_details,
            explanation=scoring_output.explanation,
        )
        self.session.add(score_record)

        # 5. Update Lead State:
        # Score band is always updated to reflect current score calculation.
        lead.score_band = scoring_output.score_band

        # Pipeline status:
        # Only advance to SCORED if lead was in discovery/enrichment pipeline stages.
        # Rescoring MUST NOT downgrade or alter terminal/post-review states (APPROVED, DISQUALIFIED, DRAFTED, SYNCED).
        if initial_status in [
            PipelineStatus.SOURCED,
            PipelineStatus.ENRICHING,
            PipelineStatus.ENRICHED,
            PipelineStatus.SCORING,
        ]:
            lead.pipeline_status = PipelineStatus.SCORED

        await self.session.flush()
        return score_record
