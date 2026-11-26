from fastapi import HTTPException


class GenerationServiceError(RuntimeError):
    """Safe, expected failure from a configured generation provider."""


class GenerationConfigurationError(GenerationServiceError):
    pass


class GenerationUpstreamError(GenerationServiceError):
    pass


class GenerationResponseError(GenerationServiceError):
    pass


class GenerationEmptyResponseError(GenerationResponseError):
    pass


def raise_generation_http_error(
    exc: GenerationServiceError, *, service: str
) -> None:
    """Map internal generation failures to a stable, non-secret API contract."""
    if isinstance(exc, GenerationConfigurationError):
        raise HTTPException(
            status_code=503, detail=f"{service} service is not configured"
        ) from exc
    if isinstance(exc, GenerationEmptyResponseError):
        raise HTTPException(
            status_code=502, detail=f"{service} service returned empty content"
        ) from exc
    if isinstance(exc, GenerationResponseError):
        raise HTTPException(
            status_code=502,
            detail=f"{service} service returned an invalid response",
        ) from exc
    raise HTTPException(
        status_code=502,
        detail=f"{service} service is temporarily unavailable",
    ) from exc
