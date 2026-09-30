from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.application.auth import Principal
from app.transport.http.common import Audit, Identity
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import CurrentUser, require
from app.transport.schemas.admin import (
    MenuIn,
    PermissionIn,
    RoleIn,
    UserIn,
    menu_out,
    role_out,
    user_out,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-system"])
UserViewer = Annotated[Principal, Depends(require("user:view"))]
UserEditor = Annotated[Principal, Depends(require("user:update"))]
RoleViewer = Annotated[Principal, Depends(require("role:view"))]
RoleEditor = Annotated[Principal, Depends(require("role:update"))]
MenuViewer = Annotated[Principal, Depends(require("menu:view"))]
MenuEditor = Annotated[Principal, Depends(require("menu:update"))]


@router.get("/me/menus")
async def my_menus(user: CurrentUser, identity: Identity):
    if not user.can("admin:access"):
        from fastapi import HTTPException

        raise HTTPException(403, detail="权限不足")
    return [menu_out(menu) for menu in await identity.menus_for_user(user.id)]


@router.get("/users")
async def list_users(
    _user: UserViewer,
    identity: Identity,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = None,
):
    users, total = await identity.list_users(page, page_size, keyword)
    return {
        "items": [user_out(user) for user in users],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/users/{user_id}")
async def get_user(user_id: str, _user: UserViewer, identity: Identity):
    return user_out(await identity.user(user_id))


@router.post("/users", status_code=201)
async def create_user(
    body: UserIn,
    user: UserEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    created = await identity.save_user(
        body.model_dump(exclude={"password", "role_ids"}), body.role_ids, body.password
    )
    await record_action(audit, request, user, "user:create", "user", created.id)
    return user_out(created)


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserIn,
    user: UserEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    updated = await identity.save_user(
        body.model_dump(exclude={"password", "role_ids"}), body.role_ids, body.password, user_id
    )
    await record_action(audit, request, user, "user:update", "user", user_id)
    return user_out(updated)


@router.get("/roles")
async def list_roles(_user: RoleViewer, identity: Identity):
    return [role_out(role) for role in await identity.list_roles()]


@router.get("/roles/{role_id}")
async def get_role(role_id: str, _user: RoleViewer, identity: Identity):
    return role_out(await identity.role(role_id))


@router.post("/roles", status_code=201)
async def create_role(
    body: RoleIn,
    user: RoleEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    role = await identity.save_role(
        body.model_dump(exclude={"permission_codes", "menu_ids"}),
        body.permission_codes,
        body.menu_ids,
    )
    await record_action(audit, request, user, "role:create", "role", role.id)
    return role_out(role)


@router.put("/roles/{role_id}")
async def update_role(
    role_id: str,
    body: RoleIn,
    user: RoleEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    role = await identity.save_role(
        body.model_dump(exclude={"permission_codes", "menu_ids"}),
        body.permission_codes,
        body.menu_ids,
        role_id,
    )
    await record_action(audit, request, user, "role:update", "role", role_id)
    return role_out(role)


@router.get("/permissions")
async def list_permissions(_user: RoleViewer, identity: Identity):
    return await identity.list_permissions()


@router.post("/permissions", status_code=201)
async def save_permission(
    body: PermissionIn,
    user: RoleEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    permission = await identity.save_permission(body.code, body.description)
    await record_action(audit, request, user, "permission:save", "permission", body.code)
    return permission


@router.get("/menus")
async def list_menus(_user: MenuViewer, identity: Identity):
    return [menu_out(menu) for menu in await identity.list_menus()]


@router.post("/menus", status_code=201)
async def create_menu(
    body: MenuIn,
    user: MenuEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    menu = await identity.save_menu(body.model_dump())
    await record_action(audit, request, user, "menu:create", "menu", menu.id)
    return menu_out(menu)


@router.put("/menus/{menu_id}")
async def update_menu(
    menu_id: str,
    body: MenuIn,
    user: MenuEditor,
    identity: Identity,
    audit: Audit,
    request: Request,
):
    menu = await identity.save_menu(body.model_dump(), menu_id)
    await record_action(audit, request, user, "menu:update", "menu", menu_id)
    return menu_out(menu)
