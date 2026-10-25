from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

class AppError(Exception):

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = (status, code, message)

async def app_error_handler(request: Request, exc: AppError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status,
        content={'error': {'code': exc.code, 'message': exc.message}},
    )
