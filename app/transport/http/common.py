from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import get_db

Db = Annotated[AsyncSession, Depends(get_db)]
