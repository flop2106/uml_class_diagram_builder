from app.schemas.models import DiagramRequest
from app import services


def _svc(provider: str):
    match provider:
        case "anthropic": from app.services import anthropic_service as s
        case "openai":    from app.services import openai_service    as s
        case "gemini":    from app.services import gemini_service     as s
        case _:           raise ValueError(f"Unknown provider: {provider}")
    return s


async def diagram_from_prompt(request: DiagramRequest) -> str:
    return await _svc(request.model_provider).diagram_from_prompt(request)


async def extract_from_code(provider: str, code: str, filename: str,
                             token: str, model: str) -> str:
    return await _svc(provider).extract_from_code(code, filename, token, model)


async def merge_diagrams(provider: str, snippets: list[str], extra_prompt: str,
                         token: str, model: str) -> str:
    return await _svc(provider).merge_diagrams(snippets, extra_prompt, token, model)


async def review_relationships(provider: str, ast_diagram: str,
                               source_files: list[dict],
                               token: str, model: str) -> str:
    return await _svc(provider).review_relationships(ast_diagram, source_files, token, model)