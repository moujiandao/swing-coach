import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisResponse
from app.services.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.get("/analysis/{analysis_id}", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    """Returns the current state of an analysis. Frontend polls this every 2s."""
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    return AnalysisResponse.model_validate(analysis)


@router.get("/history", response_model=list[AnalysisResponse], status_code=status.HTTP_200_OK)
async def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[AnalysisResponse]:
    """Returns past analyses ordered by most recent first."""
    result = await db.execute(
        select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    )
    analyses = result.scalars().all()
    return [AnalysisResponse.model_validate(a) for a in analyses]
