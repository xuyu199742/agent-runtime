"""创建首个管理员。命令行只接收用户名，密码从安全输入读取。"""

import argparse
import asyncio
from getpass import getpass

from sqlalchemy import select

from app.infrastructure.passwords import hash_password
from app.persistence.database import Permission, Role, User, session_factory


async def create_admin(username: str, display_name: str, password: str) -> str:
    async with session_factory() as db:
        if await db.scalar(select(User.id).where(User.username == username)):
            raise ValueError("用户名已存在")
        permission = await db.get(Permission, "*")
        if permission is None:
            permission = Permission(code="*", description="全部管理权限")
            db.add(permission)
        role = await db.scalar(select(Role).where(Role.name == "admin"))
        if role is None:
            role = Role(name="admin", description="系统管理员")
            db.add(role)
        if permission not in role.permissions:
            role.permissions.append(permission)
        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            roles=[role],
        )
        db.add(user)
        await db.commit()
        return user.id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    password = getpass("管理员密码（至少 12 位）：")
    confirm = getpass("再次输入密码：")
    if password != confirm:
        raise SystemExit("两次密码不一致")
    user_id = asyncio.run(create_admin(args.username, args.display_name, password))
    print(f"管理员已创建：{user_id}")


if __name__ == "__main__":
    main()
