# server/permissions.py
from typing import Union
from fastapi import Depends, HTTPException, status
from models import User, UserRole
from auth import get_current_user

RoleLike = Union[UserRole, str]

def _as_str(role: RoleLike) -> str:
    # Accept either Enum (UserRole.admin) or raw "admin"/"user"
    return role.value if hasattr(role, "value") else str(role)

def require_roles(*roles: RoleLike):
    """
    Usage:
      - @app.get("/admin/...", dependencies=[Depends(require_roles(UserRole.admin))])
      - or: Depends(require_roles("admin"))
    """
    allowed = { _as_str(r) for r in roles }

    def checker(current_user: User = Depends(get_current_user)) -> User:
        current = _as_str(getattr(current_user, "role", "user"))
        if current not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: insufficient role"
            )
        return current_user

    return checker