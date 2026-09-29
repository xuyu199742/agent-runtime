from fastapi import APIRouter

from app.transport.http.common import Catalog
from app.transport.schemas import ToolIn, ToolOut

router = APIRouter()


@router.post("/api/tools", response_model=ToolOut, status_code=201)
async def add_tool(body: ToolIn, catalog: Catalog):
    return await catalog.save_tool(body.model_dump())


@router.get("/api/tools", response_model=list[ToolOut])
async def list_tools(catalog: Catalog):
    return await catalog.list_tools()


@router.get("/api/tools/{tool_id}", response_model=ToolOut)
async def get_tool(tool_id: str, catalog: Catalog):
    return await catalog.get_tool(tool_id)


@router.put("/api/tools/{tool_id}", response_model=ToolOut)
async def update_tool(tool_id: str, body: ToolIn, catalog: Catalog):
    return await catalog.save_tool(body.model_dump(), tool_id)


@router.delete("/api/tools/{tool_id}", status_code=204)
async def delete_tool(tool_id: str, catalog: Catalog):
    await catalog.delete_tool(tool_id)
