from fastapi import APIRouter, HTTPException
from app.schemas.models import CodeParseRequest, DiagramResponse
from app.services import llm_factory
from app.services.code_parser import (
    parse_python, parse_python_module, correlate, detect_language,
    analyze_cross_file_imports,
)
from app.services.mermaid_builder import build_mermaid
import httpx

router = APIRouter(prefix="/api", tags=["parse"])


@router.post("/parse", response_model=DiagramResponse)
async def parse_code(request: CodeParseRequest):
    try:
        python_classes = []
        python_modules = []
        llm_snippets   = []
        source_tag     = "ast"

        for f in request.files:
            lang = f.language if f.language != "auto" else detect_language(f.filename, f.content)

            if lang == "python":
                parsed = parse_python(f.content, f.filename)
                python_classes.extend(parsed)
                module = parse_python_module(f.content, f.filename)
                if module:
                    python_modules.append(module)
            else:
                # Non-Python: delegate to LLM for extraction
                snippet = await llm_factory.extract_from_code(
                    request.model_provider,
                    f.content,
                    f.filename,
                    request.token,
                    request.model_name,
                )
                llm_snippets.append(snippet)
                source_tag = "llm"

        # ── Cross-file import analysis (pure AST, no LLM) ────────────────────
        python_files     = [f for f in request.files
                            if (f.language if f.language != "auto"
                                else detect_language(f.filename, f.content)) == "python"]
        known_class_names = {cls.name for cls in python_classes}
        import_relations  = analyze_cross_file_imports(python_files, known_class_names)

        # ── Decide final diagram ──────────────────────────────────────────────
        source_files = [{"filename": f.filename, "content": f.content}
                        for f in request.files]

        if python_classes and not llm_snippets:
            # Pure Python: AST first, then optional LLM review
            merged = correlate(python_classes)
            mermaid = build_mermaid(merged, python_modules, import_relations)
            source_tag = "ast"
            if request.llm_review:
                mermaid = await llm_factory.review_relationships(
                    request.model_provider, mermaid, source_files,
                    request.token, request.model_name,
                )
                source_tag = "hybrid"

        elif python_classes and llm_snippets:
            # Mixed: build AST mermaid and add to LLM snippets for merge
            merged_py = correlate(python_classes)
            ast_mermaid = build_mermaid(merged_py, python_modules, import_relations)
            all_snippets = [ast_mermaid] + llm_snippets
            mermaid = await llm_factory.merge_diagrams(
                request.model_provider,
                all_snippets,
                request.additional_prompt or "",
                request.token,
                request.model_name,
            )
            source_tag = "hybrid"
            if request.llm_review:
                mermaid = await llm_factory.review_relationships(
                    request.model_provider, mermaid, source_files,
                    request.token, request.model_name,
                )

        elif llm_snippets and len(llm_snippets) == 1 and not request.additional_prompt:
            mermaid = llm_snippets[0]

        elif llm_snippets:
            mermaid = await llm_factory.merge_diagrams(
                request.model_provider,
                llm_snippets,
                request.additional_prompt or "",
                request.token,
                request.model_name,
            )
            source_tag = "llm"

        else:
            raise HTTPException(status_code=400, detail="No files provided or no classes found.")

        return DiagramResponse(
            mermaid=mermaid,
            source=source_tag,
            provider=request.model_provider,
            model=request.model_name,
        )

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code,
                            detail=f"LLM API error: {e.response.text}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))