from fastapi import Header, HTTPException, status

from app.config import settings


async def run_token_required(x_run_token: str = Header(...)) -> None:
    if not settings.run_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RUN_TOKEN not configured on server",
        )
    if x_run_token != settings.run_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid run token",
        )
