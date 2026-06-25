from fastapi import APIRouter, HTTPException
from app.schemas.models import DiagramRequest, DiagramResponse
from app.services import llm_factory
import httpx

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/diagram", response_model=DiagramResponse)
async def diagram_from_prompt(request: DiagramRequest):
    try:
        mermaid = await llm_factory.diagram_from_prompt(request)
        return DiagramResponse(
            mermaid=mermaid,
            source="llm",
            provider=request.model_provider,
            model=request.model_name,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code,
                            detail=f"LLM API error: {e.response.text}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
