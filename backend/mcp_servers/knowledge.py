from uuid import UUID

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session

from backend.db import engine
from backend.knowledge.search import Question, invoke

mcp = FastMCP("Knowledge MCP")


@mcp.tool()
def knowledge_search(capability: str, question: Question, request_id: UUID) -> dict:
    """Search authorized current synthetic policies and return verbatim citations."""
    with Session(engine()) as db:
        return invoke(db, capability, question, request_id)


if __name__ == "__main__":
    mcp.run()
