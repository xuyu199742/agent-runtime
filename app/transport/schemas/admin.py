from pydantic import BaseModel, Field


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=12, repr=False)
    enabled: bool = True
    role_ids: list[str] = Field(default_factory=list)


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    permission_codes: list[str] = Field(default_factory=list)
    menu_ids: list[str] = Field(default_factory=list)


class PermissionIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    description: str = ""


class MenuIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=250)
    parent_id: str | None = None
    component: str | None = None
    icon: str | None = None
    permission_code: str | None = None
    sort_order: int = 0
    visible: bool = True


def user_out(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "enabled": user.enabled,
        "role_ids": [role.id for role in user.roles],
        "created_at": user.created_at,
    }


def role_out(role) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "permission_codes": [permission.code for permission in role.permissions],
        "menu_ids": [menu.id for menu in role.menus],
    }


def menu_out(menu) -> dict:
    return {
        "id": menu.id,
        "name": menu.name,
        "path": menu.path,
        "parent_id": menu.parent_id,
        "component": menu.component,
        "icon": menu.icon,
        "permission_code": menu.permission_code,
        "sort_order": menu.sort_order,
        "visible": menu.visible,
    }
