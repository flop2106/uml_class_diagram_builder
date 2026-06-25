import httpx
from app.schemas.models import DiagramRequest
from app.services.mermaid_builder import clean_llm_mermaid

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

UML_SYSTEM_PROMPT = """You are a UML class diagram generator using Mermaid.js classDiagram syntax.
Respond ONLY with valid Mermaid classDiagram syntax. No explanations, no markdown fences, no prose.
Your entire response must start with exactly: classDiagram

Relationship symbols:
  <|--  inheritance (parent left, child right)
  *--   composition
  o--   aggregation
  -->   association
  ..>   dependency
  ..|>  realization / interface implementation

Visibility: + public   - private   # protected   ~ package

Examples:
  +String name
  -int count
  #List~String~ tags
  +calculate(amount Float) Float
  +getInstance() ClassName
  +~T~process(item T) T

Classifiers (place inside class block on first line):
  <<abstract>>
  <<interface>>
  <<enumeration>>
  <<service>>
"""

CODE_EXTRACT_PROMPT = """Analyze the provided source code carefully.
Extract ALL classes, interfaces, enums, abstract classes and their:
- Attributes with types and visibility
- Methods with parameter types and return types
- All relationships: inheritance, implementation, composition, aggregation, association

Respond ONLY with valid Mermaid classDiagram syntax.
No markdown fences, no explanations. Start with exactly: classDiagram"""

MERGE_PROMPT = """You are given multiple Mermaid classDiagram snippets extracted from different code files.
Merge them into a single coherent Mermaid classDiagram that:
1. Deduplicates classes that appear in multiple snippets
2. Shows cross-file relationships (associations, dependencies)
3. Preserves all attributes, methods and relationships

Respond ONLY with the merged Mermaid classDiagram syntax. No fences, no explanations.
Start with exactly: classDiagram"""


async def _call(messages: list, system: str, token: str, model: str) -> str:
    headers = {
        "x-api-key": token,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(ANTHROPIC_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["content"][0]["text"]


async def diagram_from_prompt(request: DiagramRequest) -> str:
    messages = [{"role": i.role, "content": i.content} for i in request.history]
    user_content = request.prompt
    if request.current_diagram:
        user_content = (
            f"Current diagram:\n{request.current_diagram}\n\n"
            f"Update request: {request.prompt}"
        )
    messages.append({"role": "user", "content": user_content})
    raw = await _call(messages, UML_SYSTEM_PROMPT, request.token, request.model_name)
    return clean_llm_mermaid(raw)


async def extract_from_code(code: str, filename: str, token: str, model: str) -> str:
    prompt = f"File: {filename}\n\n{code}"
    raw = await _call(
        [{"role": "user", "content": prompt}],
        CODE_EXTRACT_PROMPT, token, model
    )
    return clean_llm_mermaid(raw)


REVIEW_PROMPT = """You are a software architect reviewing source code to identify semantic relationships between modules and classes.

You are given:
1. An AST-generated Mermaid classDiagram — structurally accurate (classes, methods, attributes are correct)
2. The original source files

Your job is to ENHANCE the diagram by adding relationships the AST parser cannot detect:
- Import dependencies: module A imports from module B → A ..> B : imports
- Usage/instantiation: A creates instances of B or calls B → A --> B : uses
- Orchestration: A registers/includes/wires B (e.g. FastAPI include_router, dependency injection) → A --> B : includes
- Inheritance or implementation visible only at runtime
- Any other meaningful semantic relationship from the code

STRICT RULES:
- Preserve ALL existing class blocks, attributes and methods EXACTLY as written
- ONLY add relationship lines between already-existing nodes in the diagram
- Never invent new classes — only add arrows between what already exists
- Every relationship must have a label describing it e.g.: : imports, : includes, : creates
- Return the COMPLETE enhanced Mermaid classDiagram starting with exactly: classDiagram
"""


async def review_relationships(ast_diagram: str, source_files: list[dict],
                               token: str, model: str) -> str:
    files_text = "\n\n".join(
        f"# File: {f['filename']}\n```\n{f['content']}\n```"
        for f in source_files
    )
    user_content = (
        f"Source files:\n{files_text}\n\n"
        f"AST-generated diagram:\n{ast_diagram}\n\n"
        "Enhance the diagram by adding all semantic relationships you can identify."
    )
    raw = await _call(
        [{"role": "user", "content": user_content}],
        REVIEW_PROMPT, token, model,
    )
    return clean_llm_mermaid(raw)


async def merge_diagrams(snippets: list[str], extra_prompt: str,
                         token: str, model: str) -> str:
    combined = "\n\n---\n\n".join(snippets)
    user_msg = combined
    if extra_prompt:
        user_msg = f"{combined}\n\nAdditional instructions: {extra_prompt}"
    raw = await _call(
        [{"role": "user", "content": user_msg}],
        MERGE_PROMPT, token, model
    )
    return clean_llm_mermaid(raw)