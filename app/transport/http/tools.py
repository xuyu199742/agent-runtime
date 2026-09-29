from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.infrastructure.database import ToolDefinition
from app.transport.http.common import Db
from app.transport.schemas import ToolIn, ToolOut

router = APIRouter()


@router.post("/api/tools", response_model=ToolOut, status_code=201)
async def add_tool(body: ToolIn, db: Db):
    tool = ToolDefinition(**body.model_dump())
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.get("/api/tools", response_model=list[ToolOut])
async def list_tools(db: Db):
    return list((await db.scalars(select(ToolDefinition).order_by(ToolDefinition.name))).all())


@router.get("/api/tools/{tool_id}", response_model=ToolOut)
async def get_tool(tool_id: str, db: Db):
    tool = await db.get(ToolDefinition, tool_id)
    if tool is None:
        raise HTTPException(404, detail="工具不存在")
    return tool


@router.put("/api/tools/{tool_id}", response_model=ToolOut)
async def update_tool(tool_id: str, body: ToolIn, db: Db):
    tool = await get_tool(tool_id, db)
    for key, value in body.model_dump().items():
        setattr(tool, key, value)
    await db.commit()
    await db.refresh(tool)
    return tool


@router.delete("/api/tools/{tool_id}", status_code=204)
async def delete_tool(tool_id: str, db: Db):
    tool = await get_tool(tool_id, db)
    await db.delete(tool)
    await db.commit()
