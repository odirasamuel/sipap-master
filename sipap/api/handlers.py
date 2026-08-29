"""API Handlers - FastAPI endpoints for SIPAP prediction service.

Pattern adapted from Sentinel's serverless handler patterns.

Provides HTTP API for:
- Prediction requests (POST /predict)
- Health checks (GET /health)
- Sports listing (GET /sports)
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from sipap.core.orchestrator import MainOrchestrator
from sipap.api.subscription import router as subscription_router

# Initialize FastAPI app
app = FastAPI(
    title="SIPAP Prediction API",
    description="Sports Intelligence Platform and Outcome Probability Assessment",
    version="0.1.0",
)

# Register routers
app.include_router(subscription_router, prefix="/api")

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize orchestrator (singleton pattern)
_orchestrator: MainOrchestrator | None = None


def get_orchestrator() -> MainOrchestrator:
    """
    Get or create MainOrchestrator instance.

    Uses singleton pattern for efficiency.

    Returns:
        MainOrchestrator instance
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MainOrchestrator(logger=logger)
    return _orchestrator


# Request/Response Models


class PredictionRequest(BaseModel):
    """Request model for prediction endpoint."""

    sport: str = Field(
        ...,
        description="Sport identifier (e.g., 'soccer', 'basketball')",
        examples=["soccer"],
    )
    match_id: str = Field(
        ...,
        description="Match identifier",
        examples=["Man_United_vs_Liverpool"],
    )
    market: str = Field(
        ...,
        description="Betting market (e.g., '1X2', 'BTTS', 'OU2.5')",
        examples=["1X2"],
    )


class PredictionResponse(BaseModel):
    """Response model for successful prediction."""

    status: str = Field(..., description="Prediction status", examples=["SUCCESS"])
    match_id: str = Field(..., description="Match identifier")
    market: str = Field(..., description="Betting market")
    outcome: str = Field(..., description="Predicted outcome", examples=["Home Win"])
    probability: float = Field(
        ..., description="Outcome probability", ge=0.0, le=1.0, examples=[0.6]
    )
    confidence: float = Field(
        ..., description="Confidence score (0-100)", ge=0.0, le=100.0, examples=[75.0]
    )
    expected_value: dict[str, Any] = Field(
        ..., description="Expected value analysis"
    )
    quality_gate: str = Field(
        ..., description="Quality gate status", examples=["PASSED"]
    )
    recommendation: str = Field(
        ..., description="Final recommendation", examples=["PLACE BET - Positive expected value"]
    )
    reasoning: str = Field(..., description="Aggregated reasoning from agents")
    evidence: list[str] = Field(..., description="Evidence supporting prediction")


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Service health status", examples=["healthy"])
    version: str = Field(..., description="API version", examples=["0.1.0"])
    orchestrator: str = Field(
        ..., description="Orchestrator status", examples=["initialized"]
    )


class SportsResponse(BaseModel):
    """Response model for sports listing."""

    sports: list[str] = Field(
        ..., description="List of supported sports", examples=[["soccer"]]
    )
    count: int = Field(..., description="Number of supported sports", examples=[1])


class ErrorResponse(BaseModel):
    """Response model for errors."""

    status: str = Field(..., description="Error status", examples=["ERROR"])
    error: str = Field(..., description="Error type", examples=["ValueError"])
    message: str = Field(
        ..., description="Error message", examples=["Sport 'basketball' not supported"]
    )
    details: dict[str, Any] | None = Field(
        None, description="Additional error details"
    )


# API Endpoints


@app.get("/health", response_model=HealthResponse, tags=["System"])  # type: ignore[untyped-decorator]
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns service health status and version information.

    Returns:
        Health status response
    """
    try:
        _ = get_orchestrator()  # Verify orchestrator can be initialized
        orchestrator_status = "initialized"
    except Exception as e:
        logger.error(f"Orchestrator health check failed: {e}", exc_info=True)
        orchestrator_status = "error"

    return HealthResponse(
        status="healthy" if orchestrator_status == "initialized" else "degraded",
        version="0.1.0",
        orchestrator=orchestrator_status,
    )


@app.get("/sports", response_model=SportsResponse, tags=["System"])  # type: ignore[untyped-decorator]
async def list_sports() -> SportsResponse:
    """
    List supported sports.

    Returns list of all sports that can be used for predictions.

    Returns:
        Supported sports list
    """
    try:
        orchestrator = get_orchestrator()
        sports = orchestrator.get_supported_sports()

        return SportsResponse(sports=sports, count=len(sports))

    except Exception as e:
        logger.error(f"Failed to list sports: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                status="ERROR",
                error=type(e).__name__,
                message=str(e),
                details=None,
            ).model_dump(),
        ) from e


@app.post(
    "/predict",
    response_model=PredictionResponse,
    status_code=status.HTTP_200_OK,
    tags=["Predictions"],
)  # type: ignore[untyped-decorator]
async def predict(request: PredictionRequest) -> PredictionResponse:
    """
    Generate prediction for a match.

    This endpoint:
    1. Aggregates context from MCP servers
    2. Validates data quality
    3. Runs ensemble prediction
    4. Calculates expected value
    5. Applies quality gates
    6. Saves prediction
    7. Returns recommendation

    Args:
        request: Prediction request with sport, match_id, and market

    Returns:
        Prediction response with recommendation

    Raises:
        HTTPException: If prediction fails or validation fails
    """
    logger.info(
        "Prediction request received",
        extra={
            "sport": request.sport,
            "match_id": request.match_id,
            "market": request.market,
        },
    )

    try:
        orchestrator = get_orchestrator()

        # Generate prediction
        prediction = await orchestrator.predict(
            sport=request.sport,
            match_id=request.match_id,
            market=request.market,
        )

        # Check if prediction failed
        if prediction.get("status") == "FAILED":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=ErrorResponse(
                    status="FAILED",
                    error="PredictionValidationError",
                    message=prediction.get("reason", "Prediction failed"),
                    details={"validation": prediction.get("validation")},
                ).model_dump(),
            )

        # Build response
        return PredictionResponse(
            status="SUCCESS",
            match_id=request.match_id,
            market=request.market,
            outcome=prediction["outcome"],
            probability=prediction["probability"],
            confidence=prediction["confidence"],
            expected_value=prediction["expected_value"],
            quality_gate=prediction["quality_gate"],
            recommendation=prediction["recommendation"],
            reasoning=prediction["reasoning"],
            evidence=prediction["evidence"],
        )

    except ValueError as e:
        # Invalid input (sport not supported, etc.)
        logger.warning(f"Invalid prediction request: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                status="ERROR",
                error="ValueError",
                message=str(e),
                details=None,
            ).model_dump(),
        ) from e

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        # Unexpected error
        logger.error(
            f"Prediction failed with unexpected error: {e}",
            exc_info=True,
            extra={
                "sport": request.sport,
                "match_id": request.match_id,
                "market": request.market,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorResponse(
                status="ERROR",
                error=type(e).__name__,
                message="Internal server error during prediction",
                details={"error": str(e)},
            ).model_dump(),
        ) from e


# Root endpoint


@app.get("/", tags=["System"])  # type: ignore[untyped-decorator]
async def root() -> dict[str, str]:
    """
    Root endpoint with API information.

    Returns:
        API info
    """
    return {
        "service": "SIPAP Prediction API",
        "version": "0.1.0",
        "description": "Sports Intelligence Platform and Outcome Probability Assessment",
        "docs": "/docs",
        "health": "/health",
    }
