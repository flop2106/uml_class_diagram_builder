"""
mermaid_builder.py
Converts a list of ClassInfo + ModuleInfo → valid Mermaid classDiagram syntax.
Also handles cross-class association detection from type hints.
"""
import os
import re
from app.services.code_parser import ClassInfo, ModuleInfo, ImportRelation

# Dunder methods to suppress in the diagram (too noisy)
_SKIP_METHODS = {"__init__", "__str__", "__repr__", "__eq__", "__hash__",
                 "__lt__", "__le__", "__gt__", "__ge__", "__len__",
                 "__iter__", "__next__", "__enter__", "__exit__"}

# Built-in / stdlib types to ignore when detecting associations
_BUILTIN_TYPES = {
    "str", "int", "float", "bool", "bytes", "None", "NoneType",
    "list", "List", "dict", "Dict", "set", "Set", "tuple", "Tuple",
    "Optional", "Union", "Any", "Type", "Callable", "Iterator",
    "Generator", "Iterable", "Sequence", "Mapping",
    "datetime", "date", "time", "timedelta", "Path",
    "UUID", "Enum", "ABC", "Protocol", "object",
}


def _class_header(node_id: str, filename: str) -> str:
    """
    Build a Mermaid class header with an optional filename label.
    Uses Mermaid 10.x label syntax:  class NodeId["NodeId (file.py)"]
    Node ID stays clean for relationship arrows; label carries the filename.
    """
    if filename:
        basename = os.path.basename(filename)
        return f'    class {node_id}["{node_id} ({basename})"]'
    return f"    class {node_id}"


def _extract_type_refs(type_hint: str) -> list[str]:
    """Pull out bare class names from a type hint string (e.g. List~MyClass~ → MyClass)."""
    if not type_hint:
        return []
    # Strip Mermaid generic syntax ~...~ and split on common separators
    raw = re.sub(r"[~\[\]<>|,]", " ", type_hint)
    return [w for w in raw.split() if w and w[0].isupper() and w not in _BUILTIN_TYPES]


def build_mermaid(classes: list[ClassInfo],
                  modules: list[ModuleInfo] | None = None,
                  import_relations: list[ImportRelation] | None = None) -> str:
    if not classes and not modules:
        return "classDiagram\n    note \"No classes or functions found\""

    known_classes = {c.name for c in classes}
    known_modules = {m.name for m in (modules or [])}
    known_nodes   = known_classes | known_modules

    lines = ["classDiagram"]

    # ── Class blocks ──────────────────────────────────────────────────────────
    for cls in classes:
        lines.append(_class_header(cls.name, cls.filename) + " {")

        if cls.classifier:
            lines.append(f"        {cls.classifier}")

        for attr in cls.attributes:
            type_str = f" {attr.type_hint}" if attr.type_hint else ""
            lines.append(f"        {attr.visibility}{attr.name}{type_str}")

        for method in cls.methods:
            if method.name in _SKIP_METHODS:
                continue
            params_str = ", ".join(method.params) if method.params else ""
            ret = f" {method.return_type}" if method.return_type else ""
            suffix = "*" if method.is_abstract else ""
            lines.append(f"        {method.visibility}{method.name}({params_str}){ret}{suffix}")

        lines.append("    }")

    # ── Module blocks (standalone functions) ──────────────────────────────────
    for mod in (modules or []):
        if not mod.functions:
            continue
        lines.append(_class_header(mod.name, mod.filename) + " {")
        lines.append("        <<module>>")
        for func in mod.functions:
            if func.name in _SKIP_METHODS:
                continue
            params_str = ", ".join(func.params) if func.params else ""
            ret = f" {func.return_type}" if func.return_type else ""
            lines.append(f"        {func.visibility}{func.name}({params_str}){ret}")
        lines.append("    }")

    lines.append("")

    # ── Relationships ─────────────────────────────────────────────────────────

    # 1. Inheritance
    for cls in classes:
        for base in cls.bases:
            if base in known_classes and base not in ("ABC", "Enum", "Protocol", "object"):
                lines.append(f"    {base} <|-- {cls.name}")
            elif base in ("ABC",):
                pass    # already shown via <<abstract>>

    # 2. Associations (attribute type points to a known class)
    for cls in classes:
        seen_assoc: set[str] = set()
        for attr in cls.attributes:
            for ref in _extract_type_refs(attr.type_hint or ""):
                if ref in known_classes and ref != cls.name and ref not in seen_assoc:
                    rel = "*--" if not (attr.type_hint or "").startswith(
                        ("List", "list", "Dict", "dict", "Set", "set")) else "o--"
                    lines.append(f"    {cls.name} {rel} {ref} : {attr.name}")
                    seen_assoc.add(ref)

    # 3. Import relationships (cross-file, module-level)
    if import_relations:
        lines.append("")
        lines.append("    %% import relationships")
        seen_import: set[tuple[str, str]] = set()
        for rel in import_relations:
            pair = (rel.source_module, rel.target_module)
            if pair in seen_import:
                continue
            # Only draw arrow if both nodes actually exist in the diagram
            if rel.source_module in known_nodes and rel.target_module in known_nodes:
                lines.append(f"    {rel.source_module} ..> {rel.target_module} : {rel.relation_label}")
                seen_import.add(pair)

    return "\n".join(lines)


def _ascii_safe(text: str) -> str:
    """
    Replace common non-ASCII characters that LLMs emit with ASCII equivalents,
    then drop any remaining non-ASCII. Mermaid syntax is ASCII-only so this
    is lossless for valid diagram content.
    """
    replacements = {
        '\u2026': '...',   # … ellipsis
        '\u2013': '-',     # – en dash
        '\u2014': '--',    # — em dash
        '\u2018': "'",     # ' left single quote
        '\u2019': "'",     # ' right single quote
        '\u201c': '"',     # " left double quote
        '\u201d': '"',     # " right double quote
        '\u00ab': '<<',    # « left guillemet
        '\u00bb': '>>',    # » right guillemet
        '\u2192': '-->',   # → arrow
        '\u2190': '<--',   # ← arrow
        '\u00b7': '*',     # · middle dot
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Drop anything still non-ASCII
    return text.encode('ascii', errors='ignore').decode('ascii')


def clean_llm_mermaid(raw: str) -> str:
    """
    Robustly extract a valid Mermaid classDiagram from LLM output.
    Handles: markdown fences, prose preambles, trailing explanations,
    and non-ASCII characters that break downstream encoding.
    """
    text = raw.strip()

    # Priority 1: content inside a ```mermaid ... ``` or ``` ... ``` block
    fenced = re.search(r'```(?:mermaid)?\s*\n(.*?)```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    else:
        # Strip any stray fences
        text = re.sub(r'```[a-z]*\n?', '', text)
        text = text.replace('```', '').strip()

    # Priority 2: find "classDiagram" and discard everything before it
    match = re.search(r'^[ \t]*classDiagram\b', text, re.MULTILINE | re.IGNORECASE)
    if match:
        text = text[match.start():].strip()
    elif 'classDiagram' in text:
        text = text[text.index('classDiagram'):].strip()
    else:
        text = 'classDiagram\n' + text.strip()

    # Priority 3: strip trailing prose after the diagram
    lines = text.splitlines()
    diagram_lines = []
    for line in lines:
        stripped = line.strip()
        if (diagram_lines
                and len(stripped) > 60
                and not stripped.startswith(('%', 'class ', 'note ', '<<'))
                and re.match(r'^[A-Z][a-z]', stripped)
                and '--' not in stripped
                and ':' not in stripped):
            break
        diagram_lines.append(line)

    return _ascii_safe('\n'.join(diagram_lines).strip())