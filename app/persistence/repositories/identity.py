from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.passwords import hash_password
from app.persistence.database import Menu, Permission, Role, User


class IdentityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_user(self, user_id: str):
        return await self.db.get(User, user_id)

    async def get_role(self, role_id: str):
        return await self.db.get(Role, role_id)

    async def get_menu(self, menu_id: str):
        return await self.db.get(Menu, menu_id)

    async def get_permission(self, code: str):
        return await self.db.get(Permission, code)

    async def list_users(self, page: int, page_size: int, keyword: str | None):
        statement = select(User)
        if keyword:
            statement = statement.where(User.username.ilike(f"%{keyword}%"))
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.scalars(
                statement.order_by(User.username).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return list(rows), total or 0

    async def list_roles(self):
        return list((await self.db.scalars(select(Role).order_by(Role.name))).all())

    async def list_permissions(self):
        return list((await self.db.scalars(select(Permission).order_by(Permission.code))).all())

    async def list_menus(self):
        return list(
            (await self.db.scalars(select(Menu).order_by(Menu.sort_order, Menu.name))).all()
        )

    async def save_user(
        self,
        values: dict,
        roles: list[Role],
        password: str | None,
        user=None,
    ):
        if user is None:
            user = User()
            self.db.add(user)
        for key, value in values.items():
            setattr(user, key, value)
        user.roles = roles
        if password is not None:
            user.password_hash = hash_password(password)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def save_role(
        self, values: dict, permissions: list[Permission], menus: list[Menu], role=None
    ):
        if role is None:
            role = Role()
            self.db.add(role)
        for key, value in values.items():
            setattr(role, key, value)
        role.permissions = permissions
        role.menus = menus
        await self.db.commit()
        await self.db.refresh(role)
        return role

    async def save_permission(self, code: str, description: str):
        permission = await self.db.get(Permission, code)
        if permission is None:
            permission = Permission(code=code)
            self.db.add(permission)
        permission.description = description
        await self.db.commit()
        return permission

    async def save_menu(self, values: dict, menu=None):
        if menu is None:
            menu = Menu()
            self.db.add(menu)
        for key, value in values.items():
            setattr(menu, key, value)
        await self.db.commit()
        await self.db.refresh(menu)
        return menu

    async def menus_for_user(self, user_id: str):
        user = await self.db.get(User, user_id)
        seen = set()
        menus = []
        for role in user.roles:
            for menu in role.menus:
                if menu.visible and menu.id not in seen:
                    seen.add(menu.id)
                    menus.append(menu)
        return sorted(menus, key=lambda item: (item.sort_order, item.name))
