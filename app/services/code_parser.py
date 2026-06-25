"""
code_parser.py
Parses Python source via AST. Other languages fall back to LLM.
Extracts: classes, attributes (with types), methods, inheritance, associations.
Also performs cross-file import analysis to detect module-level relationships.
"""
import ast
import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AttributeInfo:
    name: str
    type_hint: Optional[str] = None
    visibility: str = "+"           # + public  - private  # protected


@dataclass
class MethodInfo:
    name: str
    params: list[str] = field(default_factory=list)
    return_type: Optional[str] = None
    visibility: str = "+"
    is_abstract: bool = False
    is_static: bool = False
    is_class_method: bool = False
    is_property: bool = False


@dataclass
class ClassInfo:
    name: str
    bases: list[str] = field(default_factory=list)
    classifier: str = ""            # <<abstract>> <<interface>> <<enumeration>>
    attributes: list[AttributeInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    filename: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _visibility(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "-"
    if name.startswith("_"):
        return "#"
    return "+"


def _annotation_to_str(node) -> Optional[str]:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Subscript):
        outer = _annotation_to_str(node.value)
        inner = _annotation_to_str(node.slice)
        if outer and inner:
            return f"{outer}~{inner}~"   # Mermaid generic syntax
        return outer
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # Python 3.10+ union: X | Y
        left = _annotation_to_str(node.left)
        right = _annotation_to_str(node.right)
        return f"{left}|{right}" if left and right else left or right
    return None


def _has_decorator(func_node, names: list[str]) -> bool:
    for d in func_node.decorator_list:
        if isinstance(d, ast.Name) and d.id in names:
            return True
        if isinstance(d, ast.Attribute) and d.attr in names:
            return True
    return False


def _classifier_from_bases(bases: list[str]) -> str:
    if any(b in ("ABC", "ABCMeta") for b in bases):
        return "<<abstract>>"
    if any(b in ("Protocol",) for b in bases):
        return "<<interface>>"
    if any(b in ("Enum", "IntEnum", "StrEnum", "Flag") for b in bases):
        return "<<enumeration>>"
    return ""


# ── Python AST parser ─────────────────────────────────────────────────────────

def parse_python(code: str, filename: str = "") -> list[ClassInfo]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    classes: list[ClassInfo] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Resolve base names
        bases = []
        for base in node.bases:
            name = _annotation_to_str(base)
            if name and name != "object":
                bases.append(name)

        cls = ClassInfo(
            name=node.name,
            bases=bases,
            classifier=_classifier_from_bases(bases),
            filename=filename,
        )

        # ── Scan class body ───────────────────────────────────────────────────
        for item in node.body:

            # Class-level annotated assignments: x: int = 0
            if isinstance(item, ast.AnnAssign):
                target = item.target
                attr_name = None
                if isinstance(target, ast.Name):
                    attr_name = target.id
                elif isinstance(target, ast.Attribute) and \
                        isinstance(target.value, ast.Name) and \
                        target.value.id == "self":
                    attr_name = target.attr
                if attr_name:
                    cls.attributes.append(AttributeInfo(
                        name=attr_name,
                        type_hint=_annotation_to_str(item.annotation),
                        visibility=_visibility(attr_name),
                    ))

            # Methods
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_abstract   = _has_decorator(item, ["abstractmethod"])
                is_static     = _has_decorator(item, ["staticmethod"])
                is_cls_method = _has_decorator(item, ["classmethod"])
                is_property   = _has_decorator(item, ["property"])

                vis = _visibility(item.name)

                # Skip first arg (self / cls)
                args = item.args.args[1:] if not is_static else item.args.args
                params = []
                for arg in args:
                    type_str = _annotation_to_str(arg.annotation) if arg.annotation else None
                    params.append(type_str or arg.arg)

                return_type = _annotation_to_str(item.returns) if item.returns else None

                if is_property:
                    # Treat @property as attribute
                    if not any(a.name == item.name for a in cls.attributes):
                        cls.attributes.append(AttributeInfo(
                            name=item.name,
                            type_hint=return_type,
                            visibility=vis,
                        ))
                else:
                    cls.methods.append(MethodInfo(
                        name=item.name,
                        params=params,
                        return_type=return_type,
                        visibility=vis,
                        is_abstract=is_abstract,
                        is_static=is_static,
                        is_class_method=is_cls_method,
                    ))

                # ── Mine __init__ for self.x = ... ───────────────────────────
                if item.name == "__init__":
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.AnnAssign):
                            if isinstance(stmt.target, ast.Attribute) and \
                                    isinstance(stmt.target.value, ast.Name) and \
                                    stmt.target.value.id == "self":
                                aname = stmt.target.attr
                                if not any(a.name == aname for a in cls.attributes):
                                    cls.attributes.append(AttributeInfo(
                                        name=aname,
                                        type_hint=_annotation_to_str(stmt.annotation),
                                        visibility=_visibility(aname),
                                    ))
                        elif isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Attribute) and \
                                        isinstance(target.value, ast.Name) and \
                                        target.value.id == "self":
                                    aname = target.attr
                                    if not any(a.name == aname for a in cls.attributes):
                                        cls.attributes.append(AttributeInfo(
                                            name=aname,
                                            visibility=_visibility(aname),
                                        ))

        classes.append(cls)

    return classes


# ── Cross-file deduplication & correlation ────────────────────────────────────

def correlate(all_classes: list[ClassInfo]) -> list[ClassInfo]:
    """
    Deduplicate classes by name across files, merging attributes/methods
    from duplicate definitions (e.g. same class split across two snippets).
    """
    merged: dict[str, ClassInfo] = {}
    for cls in all_classes:
        if cls.name not in merged:
            merged[cls.name] = cls
        else:
            existing = merged[cls.name]
            existing_attrs   = {a.name for a in existing.attributes}
            existing_methods = {m.name for m in existing.methods}
            for attr in cls.attributes:
                if attr.name not in existing_attrs:
                    existing.attributes.append(attr)
            for method in cls.methods:
                if method.name not in existing_methods:
                    existing.methods.append(method)
    return list(merged.values())


# ── Module-level functions ────────────────────────────────────────────────────

@dataclass
class ModuleInfo:
    name: str                       # e.g. "utils" from "utils.py"
    functions: list[MethodInfo] = field(default_factory=list)
    filename: str = ""


def parse_python_module(code: str, filename: str = "") -> Optional["ModuleInfo"]:
    """Extract top-level (module-level) standalone functions from Python code."""
    import os
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    base = os.path.splitext(os.path.basename(filename))[0] if filename else "module"
    module_name = re.sub(r"[^a-zA-Z0-9]", "_", base) or "module"

    module = ModuleInfo(name=module_name, filename=filename)

    for node in tree.body:          # top-level only, not nested inside classes
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        vis = _visibility(node.name)
        params = []
        for arg in node.args.args:
            type_str = _annotation_to_str(arg.annotation) if arg.annotation else None
            params.append(type_str or arg.arg)
        return_type = _annotation_to_str(node.returns) if node.returns else None
        module.functions.append(MethodInfo(
            name=node.name,
            params=params,
            return_type=return_type,
            visibility=vis,
        ))

    return module if module.functions else None


# ── Language detector ─────────────────────────────────────────────────────────

def detect_language(filename: str, content: str) -> str:
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".go": "go",
        ".rb": "ruby",
    }
    for ext, lang in ext_map.items():
        if filename.lower().endswith(ext):
            return lang
    # Heuristic on content
    if "def " in content and "class " in content:
        return "python"
    if "public class " in content or "private class " in content:
        return "java"
    if "namespace " in content and "class " in content:
        return "csharp"
    return "unknown"


# ── Cross-file import analysis ────────────────────────────────────────────────

@dataclass
class ImportRelation:
    source_module: str       # diagram node name of the importing file  (e.g. "main")
    target_module: str       # diagram node name of the imported file   (e.g. "generate")
    imported_names: list[str]  # what was imported e.g. ["router", "generate_router"]
    relation_label: str      # human-readable label for the arrow


def _file_to_node_name(filename: str) -> str:
    """Derive a Mermaid-safe node name from a filename. Mirrors ModuleInfo naming."""
    base = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"[^a-zA-Z0-9]", "_", base) or "module"


def _raw_imports(code: str) -> list[tuple[str, list[str]]]:
    """
    Return list of (dotted_module_path, [imported_names]) from a Python file.
    Handles both `import x` and `from x import y, z`.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    results = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, [alias.asname or alias.name.split(".")[-1]]))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [a.name for a in node.names if a.name != "*"]
            if module and names:
                results.append((module, names))
    return results


def analyze_cross_file_imports(files: list,
                               known_class_names: set[str] | None = None) -> list[ImportRelation]:
    """
    Given a list of CodeFile objects (all Python), detect which files import
    from each other and return ImportRelation objects ready for diagram rendering.

    Two levels of relationships are created:
    - Class-level: if an imported name matches a known class → arrow goes directly
                   to that class node  (e.g. generate ..> DiagramRequest : imports)
    - Module-level: for non-class imports (functions, constants, aliases) → arrow
                    goes to the source file's module node  (e.g. generate ..> models)
    """
    if len(files) < 2:
        return []

    known_class_names = known_class_names or set()

    # Build registry: dotted_path → node_name
    registry: dict[str, str] = {}
    for f in files:
        node_name = _file_to_node_name(f.filename)
        clean = f.filename.replace("\\", "/").lstrip("/")
        base  = os.path.splitext(clean)[0]
        parts = base.split("/")
        for i in range(len(parts)):
            dot_path = ".".join(parts[i:])
            registry.setdefault(dot_path, node_name)

    relations: list[ImportRelation] = []

    for f in files:
        source_node = _file_to_node_name(f.filename)
        seen_module_targets: set[str] = set()   # dedup module-level arrows only
        seen_class_targets:  set[str] = set()   # dedup class-level arrows per source

        for module_path, imported_names in _raw_imports(f.content):
            target_node = registry.get(module_path)
            if not target_node:
                target_node = registry.get(module_path.split(".")[-1])
            if not target_node or target_node == source_node:
                continue

            # ── Split imported names into classes vs everything else ──────────
            class_imports = [n for n in imported_names if n in known_class_names]
            other_imports  = [n for n in imported_names if n not in known_class_names]

            # ── Class-level arrows: source_module ..> ClassName ───────────────
            for cls_name in class_imports:
                if cls_name in seen_class_targets:
                    continue
                seen_class_targets.add(cls_name)
                relations.append(ImportRelation(
                    source_module=source_node,
                    target_module=cls_name,      # points directly to the class node
                    imported_names=[cls_name],
                    relation_label="imports",
                ))

            # ── Module-level arrow for non-class imports ──────────────────────
            if other_imports and target_node not in seen_module_targets:
                seen_module_targets.add(target_node)
                shown = other_imports[:2]
                label = "imports " + ", ".join(shown)
                if len(other_imports) > 2:
                    label += f" +{len(other_imports) - 2} more"
                relations.append(ImportRelation(
                    source_module=source_node,
                    target_module=target_node,
                    imported_names=other_imports,
                    relation_label=label,
                ))

            # ── Fallback: if everything imported is a class, still record
            #    a module-level arrow so isolated modules show connections ──────
            elif not other_imports and not class_imports and target_node not in seen_module_targets:
                seen_module_targets.add(target_node)
                relations.append(ImportRelation(
                    source_module=source_node,
                    target_module=target_node,
                    imported_names=imported_names,
                    relation_label="imports",
                ))

    return relations