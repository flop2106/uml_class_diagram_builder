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
    "CRITICAL: Mermaid node IDs must contain ONLY letters, digits, and underscores — NEVER a hyphen, dot, "
    "or space. Hyphens break Mermaid's layout engine because they collide with relationship syntax (-->, --|>). "
    'If a filename like "app-config.ts" would be used as a node ID, sanitize it to "app_config" first. '
    "IMPORTANT: every class/interface block MUST show its source filename using this exact syntax: "
    'class ClassName["ClassName (filename.ext)"] {{ ... }} — the node ID stays a clean valid identifier '
    "(no hyphens, dots, or parentheses), only the quoted label carries the ORIGINAL filename unchanged. "
    "Use the exact filename given in the File: header of the input for the label text. "
    "For module-level functions with no class, use a sanitized filename (without extension, hyphens/dots "
    'replaced with underscores) as the node ID with <<module>> classifier, e.g. for "utils-helper.js": '
    'class utils_helper["utils_helper (utils-helper.js)"] {{ <<module>> +parseData(input) }}. '
    "CRITICAL — type syntax: Mermaid does NOT understand TypeScript types. NEVER write a curly brace "
    "{ or } inside an attribute/method line (only the class block's own braces may contain them) — "
    'e.g. "createMatrix(): { include: Array<X> }" must become "createMatrix() object". NEVER write the '
    'optional-parameter marker "?:" — drop the "?". Avoid angle-bracket generics like Array<Foo> or '
    "Promise<void>; use ~Foo~ tilde syntax or simplify to a plain word (object, list, string, number) instead. "
    "Respond ONLY with valid Mermaid classDiagram syntax. No markdown fences. Start with: classDiagram"
)

MERGE_SYSTEM = (
    "Merge the provided Mermaid classDiagram snippets into one coherent diagram. "
    "Deduplicate classes, show cross-file relationships. "
    'PRESERVE filename labels exactly as given (e.g. class Foo["Foo (foo.py)"]) — do not strip them. '
    "If a class appears in multiple snippets with different labels, keep the first one. "
    "CRITICAL: every node ID in the output must contain ONLY letters, digits, and underscores — if any "
    "input snippet has a node ID with a hyphen or dot, rewrite that ID to use underscores instead "
    "(consistently, in both class declarations and relationship lines) while keeping its quoted label unchanged. "
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