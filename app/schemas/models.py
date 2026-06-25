from pydantic import BaseModel
from typing import Literal, Optional


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class DiagramRequest(BaseModel):
    token: str
    model_provider: Literal["anthropic", "openai", "gemini"]
    model_name: str
    prompt: str
    current_diagram: Optional[str] = None   # passed in for refinement
    history: list[HistoryItem] = []


class CodeFile(BaseModel):
    filename: str
    language: str   # python | javascript | typescript | java | csharp | auto
    content: str


class CodeParseRequest(BaseModel):
    token: str
    model_provider: Literal["anthropic", "openai", "gemini"]
    model_name: str
    files: list[CodeFile]
    additional_prompt: Optional[str] = None
    llm_review: bool = True     # run LLM pass after AST to add semantic relationships


class DiagramResponse(BaseModel):
    mermaid: str
    source: str = "llm"     # "ast" | "llm" | "hybrid"
    provider: Optional[str] = None
    model: Optional[str] = None