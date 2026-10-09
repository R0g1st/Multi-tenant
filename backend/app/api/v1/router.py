from fastapi import APIRouter

from app.api.v1 import audit, auth, employees, organizations, users
from app.api.v1.catalog import departments_router, positions_router

api_router = APIRouter(prefix="/api/v1")
for r in (auth.router, organizations.router, departments_router, positions_router,
          employees.router, users.router, audit.router):
    api_router.include_router(r)
