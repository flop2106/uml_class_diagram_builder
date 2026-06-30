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

    return collapse_empty_class_blocks("\n".join(lines))


def collapse_empty_class_blocks(diagram: str) -> str:
    """
    Mermaid's classDiagram parser has been observed to choke on a class
    block whose opening brace is immediately followed by a closing brace
    with nothing in between (no attributes, no methods, no classifier) —
    e.g.:
        class PlatformDeps["PlatformDeps (platform.ts)"] {
        }
    Rather than rely on undocumented parser internals to explain exactly
    why, sidestep the problem: Mermaid also supports declaring a class with
    NO body block at all — a single line like
        class PlatformDeps["PlatformDeps (platform.ts)"]
    is valid syntax and renders identically. Collapse any class block whose
    body is empty (only whitespace) down to that single-line form.

    A class with a classifier (<<module>>, <<interface>>, etc.) or any
    member line is left untouched — only truly empty bodies are affected.
    """
    pattern = re.compile(
        r'class\s+([A-Za-z_][A-Za-z0-9_]*)(\s*\[[^\]]*\])?\s*\{\s*\}'
    )
    return pattern.sub(lambda m: f'class {m.group(1)}{m.group(2) or ""}', diagram)


def sanitize_node_ids(diagram: str) -> str:
    """
    Mermaid classDiagram node IDs must be valid identifiers — letters, digits,
    underscores only. Hyphens or dots in an unquoted node ID are ambiguous with
    relationship syntax (-->, --|>, etc.) and break the dagre layout engine,
    producing 'translate(undefined, NaN)' errors at render time.

    This catches cases where an LLM used a raw filename-derived ID containing
    hyphens (e.g. "app-config") instead of sanitizing it, even though it was
    instructed to. Quoted label text (the part in ["..."]) is left untouched —
    only the bare identifier is rewritten, consistently across every reference
    to it (class declarations, relationship lines).
    """
    # Protect quoted strings so we never rewrite text inside labels
    placeholders: list[str] = []

    def _stash(m):
        placeholders.append(m.group(0))
        return f"\x00Q{len(placeholders) - 1}\x00"

    protected = re.sub(r'"[^"]*"', _stash, diagram)

    # Collect every node ID declared via `class <id>`
    raw_ids = set(re.findall(r'class\s+([A-Za-z_][A-Za-z0-9_.\-]*)', protected))
    mapping = {
        i: re.sub(r'[^A-Za-z0-9_]', '_', i)
        for i in raw_ids
        if re.search(r'[^A-Za-z0-9_]', i)   # only touch IDs with invalid chars
    }

    for old, new in mapping.items():
        protected = re.sub(rf'\b{re.escape(old)}\b', new, protected)

    # Restore quoted strings exactly as they were
    def _restore(m):
        return placeholders[int(m.group(1))]

    return re.sub(r'\x00Q(\d+)\x00', _restore, protected)


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


def sanitize_member_syntax(diagram: str) -> str:
    """
    Defensive cleanup for LLM-generated method/attribute lines using
    TypeScript-style syntax that Mermaid's classDiagram grammar cannot parse:

    - Nested curly-brace object-type literals, e.g.
        +createMatrix(): { include: Array<{ name: string }> }
      Curly braces are reserved by Mermaid to open/close a class block — an
      extra { or } inside a member line throws off the parser's brace count
      for the REST of the diagram, not just that one line.

    - Generic angle brackets, e.g. Array<Foo>, Promise<void>, Record<K, V>
      Mermaid uses ~Type~ for generics; raw < > collides with relationship
      arrow tokens (-->, <|--) and corrupts the diagram's layout (the
      "translate(undefined, NaN)" class of dagre errors).

    - TypeScript optional-parameter markers, e.g. "name?: string"
      Not part of Mermaid's method-parameter grammar.

    Only lines that look like attribute/method members (start with a
    visibility marker +/-/#/~) are touched. Class headers, relationship
    lines, and classifier lines (<<module>>, <<abstract>>) are left as-is.
    """
    out = []
    for line in diagram.split('\n'):
        stripped = line.lstrip()
        if stripped[:1] in ('+', '-', '#', '~'):
            line = _clean_member_line(line)
        out.append(line)
    return '\n'.join(out)


def _clean_member_line(line: str) -> str:
    # Collapse nested curly-brace object-type literals into "object",
    # innermost-first, repeatedly, until none remain.
    prev = None
    while '{' in line and line != prev:
        prev = line
        line = re.sub(r'\{[^{}]*\}', 'object', line)

    # Convert generic angle brackets to Mermaid's tilde syntax, innermost
    # first. Commas inside a generic (Record<K, V>) become spaces since
    # Mermaid's tilde notation doesn't support comma-separated type params.
    prev = None
    while re.search(r'<[^<>]*>', line) and line != prev:
        prev = line
        line = re.sub(
            r'<([^<>]*)>',
            lambda m: '~' + m.group(1).replace(',', ' ').strip() + '~',
            line,
        )

    # Drop TypeScript optional-parameter markers: name?: type → name: type
    line = re.sub(r'(\w)\?\s*:', r'\1:', line)

    return line


def fix_relationship_arrows(diagram: str) -> str:
    """
    Defensive fix for malformed relationship arrow tokens that LLMs
    occasionally emit. The most common: a single dot before the arrowhead
    (" .> ") instead of Mermaid's required two-dot dependency syntax
    (" ..> "). A lone ".>" is not a token Mermaid's grammar recognizes at
    all, so it fails the parser outright rather than just rendering oddly.

    Quoted label text is protected so we never rewrite something that
    happens to contain ".>" inside a string.
    """
    placeholders: list[str] = []

    def _stash(m):
        placeholders.append(m.group(0))
        return f"\x00Q{len(placeholders) - 1}\x00"

    protected = re.sub(r'"[^"]*"', _stash, diagram)

    # Single dot immediately before '>' that is NOT already preceded by
    # another dot (so we don't touch a correct "..>" and turn it into "...>").
    protected = re.sub(r'(?<!\.)\.>', '..>', protected)

    def _restore(m):
        return placeholders[int(m.group(1))]

    return re.sub(r'\x00Q(\d+)\x00', _restore, protected)


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

    text = _ascii_safe('\n'.join(diagram_lines).strip())
    text = sanitize_member_syntax(text)
    text = fix_relationship_arrows(text)
    text = collapse_empty_class_blocks(text)
    return sanitize_node_ids(text)