import httpx
from app.schemas.models import DiagramRequest
from app.services.mermaid_builder import clean_llm_mermaid

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

UML_SYSTEM_PROMPT = (
    "You are a UML class diagram generator using Mermaid.js classDiagram syntax. "
    "Respond ONLY with valid Mermaid classDiagram syntax. No explanations, no markdown fences. "
    "Your entire response must start with exactly: classDiagram\n"
    "Relationships: <|-- inheritance, *-- composition, o-- aggregation, --> association, ..> dependency, ..|> realization\n"
    "Visibility: + public, - private, # protected, ~ package\n"
    "Classifiers inside class block: <<abstract>>, <<interface>>, <<enumeration>>"
)

CODE_EXTRACT_SYSTEM = (
    "You are a code analyzer. Extract all classes, interfaces, and their relationships from the provided code. "
    "Respond ONLY with valid Mermaid classDiagram syntax. No markdown fences. Start with: classDiagram"
)

MERGE_SYSTEM = (
    "Merge the provided Mermaid classDiagram snippets into one coherent diagram. "
    "Deduplicate classes, show cross-file relationships. "
    "Respond ONLY with Mermaid classDiagram syntax. Start with: classDiagram"
)


async def _call(messages: list, system: str, token: str, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENAI_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


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
    raw = await _call(
        [{"role": "user", "content": f"File: {filename}\n\n{code}"}],
        CODE_EXTRACT_SYSTEM, token, model
    )
    return clean_llm_mermaid(raw)


async def merge_diagrams(snippets: list[str], extra_prompt: str,
                         token: str, model: str) -> str:
    combined = "\n\n---\n\n".join(snippets)
    if extra_prompt:
        combined += f"\n\nAdditional instructions: {extra_prompt}"
    raw = await _call(
        [{"role": "user", "content": combined}],
        MERGE_SYSTEM, token, model
    )
    return clean_llm_mermaid(raw)


REVIEW_SYSTEM = (
    "You are a software architect. Enhance an AST-generated Mermaid class diagram by adding "
    "semantic relationships visible in the source code: imports, usage, instantiation, orchestration. "
    "Preserve ALL existing class blocks exactly. Only add relationship arrows between existing nodes. "
    "Every arrow must have a label. Return the complete Mermaid classDiagram starting with: classDiagram"
)


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
        REVIEW_SYSTEM, token, model,
    )
    return clean_llm_mermaid(raw)