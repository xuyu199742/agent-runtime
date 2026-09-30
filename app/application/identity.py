from app.domain.errors import InvalidConfiguration, NotFound
from app.persistence.repositories.identity import IdentityRepository


class IdentityService:
    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository

    async def user(self, user_id: str):
        user = await self.repository.get_user(user_id)
        if user is None:
            raise NotFound("用户不存在")
        return user

    async def role(self, role_id: str):
        role = await self.repository.get_role(role_id)
        if role is None:
            raise NotFound("角色不存在")
        return role

    async def menu(self, menu_id: str):
        menu = await self.repository.get_menu(menu_id)
        if menu is None:
            raise NotFound("菜单不存在")
        return menu

    async def list_users(self, page: int, page_size: int, keyword: str | None):
        return await self.repository.list_users(page, page_size, keyword)

    async def list_roles(self):
        return await self.repository.list_roles()

    async def list_permissions(self):
        return await self.repository.list_permissions()

    async def list_menus(self):
        return await self.repository.list_menus()

    async def menus_for_user(self, user_id: str):
        return await self.repository.menus_for_user(user_id)

    async def save_user(
        self, values: dict, role_ids: list[str], password: str | None, user_id: str | None = None
    ):
        roles = [await self.role(role_id) for role_id in role_ids]
        if len(set(role_ids)) != len(roles):
            raise InvalidConfiguration("角色重复")
        user = await self.user(user_id) if user_id else None
        if user is None and password is None:
            raise InvalidConfiguration("新用户必须设置密码")
        return await self.repository.save_user(values, roles, password, user)

    async def save_role(
        self,
        values: dict,
        permission_codes: list[str],
        menu_ids: list[str],
        role_id: str | None = None,
    ):
        permissions = []
        for code in permission_codes:
            permission = await self.repository.get_permission(code)
            if permission is None:
                raise InvalidConfiguration(f"权限不存在：{code}")
            permissions.append(permission)
        menus = [await self.menu(menu_id) for menu_id in menu_ids]
        if len(set(permission_codes)) != len(permissions) or len(set(menu_ids)) != len(menus):
            raise InvalidConfiguration("权限或菜单重复")
        role = await self.role(role_id) if role_id else None
        if role is not None and role.name == "admin" and "*" not in permission_codes:
            raise InvalidConfiguration("不能移除管理员的全部权限")
        return await self.repository.save_role(values, permissions, menus, role)

    async def save_permission(self, code: str, description: str):
        if not code or (code != "*" and ":" not in code):
            raise InvalidConfiguration("权限码必须为 resource:action")
        return await self.repository.save_permission(code, description)

    async def save_menu(self, values: dict, menu_id: str | None = None):
        menu = await self.menu(menu_id) if menu_id else None
        permission_code = values.get("permission_code")
        if permission_code and await self.repository.get_permission(permission_code) is None:
            raise InvalidConfiguration("菜单权限不存在")
        parent_id = values.get("parent_id")
        visited = {menu_id} if menu_id else set()
        while parent_id:
            if parent_id in visited:
                raise InvalidConfiguration("菜单层级不能形成循环")
            visited.add(parent_id)
            parent = await self.menu(parent_id)
            parent_id = parent.parent_id
        return await self.repository.save_menu(values, menu)
