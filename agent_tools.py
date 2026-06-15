"""
Documentation Agent Tools
All tools the agent can call. Implement each function body as needed.
"""
import os
import ast
import json
import difflib
import fnmatch
import subprocess
from pathlib import Path

try:
    import tomllib                  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib     # type: ignore  # pip install tomli
    except ImportError:
        tomllib = None              # TOML parsing unavailable; pyproject.toml / Cargo.toml will be skipped


# ─────────────────────────────────────────────
# FILE SYSTEM TOOLS
# ─────────────────────────────────────────────

EXCLUDED_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "*.egg-info", ".idea", ".vscode",
}

MAX_CHARS = 10000

def read_file(
    working_dir: str,
    file_path: str,
) -> str:
    """
    Read and return the full text content of a file.

    Args:
        file_path:   Path to the file to read (relative to working_dir).

    Returns:
        The file content as a string, or an error message if something went wrong.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

        if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
            return f"PermissionError: '{file_path}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_file_path):
            return f"FileNotFoundError: '{file_path}' does not exist."

        if not os.path.isfile(abs_file_path):
            return f"ValueError: '{file_path}' is not a file."

        with open(abs_file_path, "r", encoding="utf-8") as f:
            content = f.read(MAX_CHARS)

            # After reading the first MAX_CHARS...
            if f.read(1):
                content += f'[...File "{file_path}" truncated at {MAX_CHARS} characters]'

        return content

    except UnicodeDecodeError:
        return f"UnicodeDecodeError: '{file_path}' is not valid UTF-8 and cannot be read as text."
    except OSError as e:
        return f"OSError: could not read '{file_path}': {e}"
    

def list_files(
    working_dir: str,
    directory: str = ".",
    pattern: str = "**/*",
) -> str:
    """
    Recursively list files in a directory matching a glob pattern.
    Automatically excludes common noise directories like node_modules,
    __pycache__, .git, .venv, dist, and build.

    Args:
        directory:   Root directory to search from (relative to working_dir).
                     Defaults to working_dir root.
        pattern:     Glob pattern to filter results.
                     Examples: "**/*.py", "**/*.ts", "src/**/*.js"
                     Defaults to "**/*" (all files).

    Returns:
        Sorted newline-separated string of matching file paths,
        or an error message if something went wrong.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_directory = os.path.realpath(os.path.join(abs_working_dir, directory))

        if not abs_directory.startswith(abs_working_dir + os.sep) and abs_directory != abs_working_dir:
            return f"PermissionError: '{directory}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_directory):
            return f"FileNotFoundError: '{directory}' does not exist."

        if not os.path.isdir(abs_directory):
            return f"ValueError: '{directory}' is not a directory."

        def is_excluded(path: Path) -> bool:
            for part in path.parts:
                for excluded in EXCLUDED_DIRS:
                    if fnmatch.fnmatch(part, excluded):
                        return True
            return False

        root = Path(abs_directory)
        matches = []

        for path in root.glob(pattern):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if is_excluded(relative):
                continue
            matches.append(str(relative))

        matches.sort()

        if not matches:
            return f"No files found in '{directory}' matching pattern '{pattern}'."

        return "\n".join(matches)

    except OSError as e:
        return f"OSError: could not list files in '{directory}': {e}"


def write_file(
    working_dir: str,
    file_path: str,
    content: str,
    overwrite: bool = False,
) -> str:
    """
    Write content to a file, creating parent directories if needed.

    Args:
        file_path:   Path to the file to write (relative to working_dir).
        content:     Full text content to write.
        overwrite:   If False (default), returns an error when the file
                     already exists to prevent accidental overwrites.

    Returns:
        A string confirming the write, or an error message if something went wrong.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

        if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
            return f"PermissionError: '{file_path}' resolves outside working directory '{working_dir}'."

        if os.path.exists(abs_file_path) and not overwrite:
            return f"FileExistsError: '{file_path}' already exists. Set overwrite=True to replace it."

        if os.path.isdir(abs_file_path):
            return f"ValueError: '{file_path}' is a directory, not a file."

        os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)

        with open(abs_file_path, "w", encoding="utf-8") as f:
            f.write(content)

        action = "overwritten" if os.path.exists(abs_file_path) else "created"
        return f"Success: '{file_path}' {action} ({len(content)} characters written)."

    except OSError as e:
        return f"OSError: could not write '{file_path}': {e}"


def patch_file(
    working_dir: str,
    file_path: str,
    old_content: str,
    new_content: str,
    allow_multiple: bool = False,
) -> str:
    """
    Replace a specific section of a file without rewriting the whole thing.
    Reads the file, substitutes old_content with new_content, then saves.

    Args:
        file_path:       Path to the file to modify (relative to working_dir).
        old_content:     The exact string to find and replace. Must match
                         the file content byte-for-byte (whitespace included).
        new_content:     The string to insert in place of old_content.
        allow_multiple:  If False (default), raises an error when
                         old_content appears more than once, preventing
                         unintended multi-site edits.

    Returns:
        A string describing the result: number of replacements made.

    Raises:
        ValueError: If old_content is not found in the file, or if it
                    appears more than once and allow_multiple is False.
        FileNotFoundError: If file_path does not exist.
        PermissionError: If the resolved path escapes working_dir.
    """
    # Resolve and jail the path
    abs_working_dir = os.path.realpath(working_dir)
    abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

    if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
        return f"PermissionError: {file_path}' resolves outside working directory '{working_dir}'."
        # raise PermissionError(
        #     f"Access denied: '{file_path}' resolves outside working directory '{working_dir}'."
        # )

    if not os.path.exists(abs_file_path):
        return f"FileNotFoundError: File not found: '{file_path}'."
        # raise FileNotFoundError(f"File not found: '{file_path}'.")

    with open(abs_file_path, "r", encoding="utf-8") as f:
        original = f.read()

    count = original.count(old_content)

    if count == 0:
        return f"ValueError: old_content not found in '{file_path}'. Ensure the string matches the file content exactly (whitespace included)."
        # raise ValueError(
        #     f"old_content not found in '{file_path}'. "
        #     "Ensure the string matches the file content exactly (whitespace included)."
        # )

    if count > 1 and not allow_multiple:
        return f"ValueError: old_content appears {count} times in '{file_path}'. Set allow_multiple=True to replace all occurrences, or provide a more specific string."
        # raise ValueError(
        #     f"old_content appears {count} times in '{file_path}'. "
        #     "Set allow_multiple=True to replace all occurrences, or provide a more specific string."
        # )

    updated = original.replace(old_content, new_content, count if allow_multiple else 1)

    with open(abs_file_path, "w", encoding="utf-8") as f:
        f.write(updated)

    replacements = count if allow_multiple else 1
    return f"Success: made {replacements} replacement(s) in '{file_path}'."


# ─────────────────────────────────────────────
# CODE UNDERSTANDING TOOLS
# ─────────────────────────────────────────────

def parse_symbols(
    working_dir: str,
    file_path: str,
) -> str:
    """
    Parse a source file with the AST and extract all top-level and nested
    symbols: classes, functions, and methods, along with their metadata.

    Args:
        working_dir: The working directory to restrict file access.
        file_path:   Path to the Python source file (relative to working_dir).

    Returns:
        A string representation of the list of symbol dicts, or an error message.
        Each dict contains:
            - name      (str)       : Symbol name, e.g. "MyClass"
            - type      (str)       : One of "class", "function", "method"
            - line      (int)       : Line number where the symbol is defined
            - parent    (str|None)  : Enclosing class name for methods, else None
            - docstring (str|None)  : Existing docstring if present, else None
            - args      (list[str]) : Parameter names (functions/methods only)
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

        if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
            return f"PermissionError: '{file_path}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_file_path):
            return f"FileNotFoundError: '{file_path}' does not exist."

        if not os.path.isfile(abs_file_path):
            return f"ValueError: '{file_path}' is not a file."

        with open(abs_file_path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return f"SyntaxError: could not parse '{file_path}': {e}"

        symbols = []

        def extract_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
            args = [arg.arg for arg in node.args.args]
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")
            return args

        def get_docstring(node: ast.AST) -> str | None:
            return ast.get_docstring(node)

        def visit_node(node: ast.AST, parent_name: str | None = None) -> None:
            if isinstance(node, ast.ClassDef):
                symbols.append({
                    "name":      node.name,
                    "type":      "class",
                    "line":      node.lineno,
                    "parent":    parent_name,
                    "docstring": get_docstring(node),
                    "args":      [],
                })
                for child in ast.iter_child_nodes(node):
                    visit_node(child, parent_name=node.name)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol_type = "method" if parent_name else "function"
                symbols.append({
                    "name":      node.name,
                    "type":      symbol_type,
                    "line":      node.lineno,
                    "parent":    parent_name,
                    "docstring": get_docstring(node),
                    "args":      extract_args(node),
                })
                # Visit nested functions/classes inside this function
                for child in ast.iter_child_nodes(node):
                    visit_node(child, parent_name=None)

        for node in ast.iter_child_nodes(tree):
            visit_node(node)

        if not symbols:
            return f"No symbols found in '{file_path}'."

        lines = [f"Found {len(symbols)} symbol(s) in '{file_path}':\n"]
        for s in symbols:
            lines.append(
                f"  [{s['type'].upper()}] {s['name']} (line {s['line']})"
                + (f" [parent: {s['parent']}]" if s['parent'] else "")
                + (f"\n    args: {s['args']}" if s['args'] else "")
                + (f"\n    docstring: {s['docstring'][:80].strip()}{'...' if len(s['docstring']) > 80 else ''}" if s['docstring'] else "")
            )

        return "\n".join(lines)

    except UnicodeDecodeError:
        return f"UnicodeDecodeError: '{file_path}' is not valid UTF-8 and cannot be read as text."
    except OSError as e:
        return f"OSError: could not read '{file_path}': {e}"


def build_symbol_index(
    working_dir: str,
    pattern: str = "**/*.py",
) -> str:
    """
    Walk all matching source files under working_dir, parse each one
    with parse_symbols(), and build a project-wide lookup table.
    Call this once at agent startup and pass the result to lookup_symbol().

    Args:
        pattern:     Glob pattern to select files. Defaults to "**/*.py".

    Returns:
        A human-readable summary of the index, or an error message.
        Populates and returns the raw index dict for programmatic use.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)

        if not os.path.exists(abs_working_dir):
            return f"FileNotFoundError: working directory '{working_dir}' does not exist."

        if not os.path.isdir(abs_working_dir):
            return f"ValueError: '{working_dir}' is not a directory."

        # Reuse list_files to get all matching files (already excludes noise dirs)
        files_output = list_files(working_dir=working_dir, directory=".", pattern=pattern)

        if files_output.startswith(("PermissionError", "FileNotFoundError", "ValueError", "OSError")):
            return f"Failed to list files: {files_output}"

        if files_output.startswith("No files found"):
            return f"No files matched pattern '{pattern}' under '{working_dir}'."

        file_paths = files_output.strip().split("\n")

        index = {}
        errors = []
        total_symbols = 0

        for rel_path in file_paths:
            parse_output = parse_symbols(working_dir=working_dir, file_path=rel_path)

            if parse_output.startswith(("PermissionError", "FileNotFoundError", "ValueError",
                                        "SyntaxError", "UnicodeDecodeError", "OSError")):
                errors.append(f"  {rel_path}: {parse_output}")
                continue

            # Re-parse directly to get structured data (parse_symbols returns a
            # human-readable string, so we parse the AST again here for the index)
            abs_file_path = os.path.join(abs_working_dir, rel_path)
            try:
                with open(abs_file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (OSError, SyntaxError) as e:
                errors.append(f"  {rel_path}: {e}")
                continue

            # Derive module path from file path: "src/models.py" -> "src.models"
            module = rel_path.replace(os.sep, ".").replace("/", ".")
            if module.endswith(".py"):
                module = module[:-3]
            if module.endswith(".__init__"):
                module = module[:-9]

            def _extract_args(node):
                args = [arg.arg for arg in node.args.args]
                if node.args.vararg:
                    args.append(f"*{node.args.vararg.arg}")
                if node.args.kwarg:
                    args.append(f"**{node.args.kwarg.arg}")
                return args

            def _visit(node, parent_name=None):
                if isinstance(node, ast.ClassDef):
                    index[node.name] = {
                        "file":      rel_path,
                        "module":    module,
                        "line":      node.lineno,
                        "type":      "class",
                        "parent":    parent_name,
                        "args":      [],
                        "docstring": ast.get_docstring(node),
                    }
                    for child in ast.iter_child_nodes(node):
                        _visit(child, parent_name=node.name)

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol_type = "method" if parent_name else "function"
                    index[node.name] = {
                        "file":      rel_path,
                        "module":    module,
                        "line":      node.lineno,
                        "type":      symbol_type,
                        "parent":    parent_name,
                        "args":      _extract_args(node),
                        "docstring": ast.get_docstring(node),
                    }
                    for child in ast.iter_child_nodes(node):
                        _visit(child, parent_name=None)

            for node in ast.iter_child_nodes(tree):
                _visit(node)

            total_symbols = len(index)

        lines = [
            f"Index built: {total_symbols} symbol(s) across {len(file_paths) - len(errors)} file(s)."
        ]
        if errors:
            lines.append(f"\n{len(errors)} file(s) had errors:")
            lines.extend(errors)

        lines.append("\nSymbols indexed:")
        for name, meta in sorted(index.items()):
            lines.append(
                f"  [{meta['type'].upper()}] {name}"
                + (f" (parent: {meta['parent']})" if meta['parent'] else "")
                + f" — {meta['file']}:{meta['line']}"
            )

        # Attach the raw index to the return string via a separator
        # so callers that need the dict can parse it, while the LLM reads the summary
        return "\n".join(lines), index

    except OSError as e:
        return f"OSError: could not build symbol index: {e}"


def lookup_symbol(symbol_name: str, index: dict) -> str:
    """
    Look up a symbol by name in a pre-built symbol index.
    Supports exact match first, then falls back to case-insensitive
    and partial matching, returning ranked suggestions if no exact hit.

    Args:
        symbol_name: The name to search for, e.g. "UserProfile".
        index:       Symbol index returned by build_symbol_index().

    Returns:
        A human-readable string with the symbol's metadata,
        a list of close matches, or a not-found message.
    """
    if not index:
        return "Error: symbol index is empty. Run build_symbol_index() first."

    if not symbol_name or not symbol_name.strip():
        return "Error: symbol_name must be a non-empty string."

    # 1. Exact match
    if symbol_name in index:
        meta = index[symbol_name]
        lines = [f"Symbol '{symbol_name}' found:"]
        lines.append(f"  type:    {meta['type']}")
        lines.append(f"  file:    {meta['file']}:{meta['line']}")
        lines.append(f"  module:  {meta['module']}")
        if meta.get("parent"):
            lines.append(f"  parent:  {meta['parent']}")
        if meta.get("args"):
            lines.append(f"  args:    {meta['args']}")
        if meta.get("docstring"):
            doc = meta["docstring"]
            lines.append(f"  docstring: {doc[:120].strip()}{'...' if len(doc) > 120 else ''}")
        else:
            lines.append(f"  docstring: None")
        return "\n".join(lines)

    # 2. Case-insensitive match
    lower_name = symbol_name.lower()
    case_matches = [k for k in index if k.lower() == lower_name]

    # 3. Partial / substring match
    partial_matches = [k for k in index if lower_name in k.lower() and k not in case_matches]

    if not case_matches and not partial_matches:
        return (
            f"Symbol '{symbol_name}' not found in index ({len(index)} symbols). "
            "Check the name or re-run build_symbol_index() if the codebase has changed."
        )

    lines = [f"No exact match for '{symbol_name}'."]

    if case_matches:
        lines.append(f"\nCase-insensitive match(es):")
        for name in case_matches:
            meta = index[name]
            lines.append(f"  [{meta['type'].upper()}] {name} — {meta['file']}:{meta['line']}")

    if partial_matches:
        lines.append(f"\nPartial match(es):")
        for name in partial_matches[:10]:  # cap at 10 to avoid flooding the LLM
            meta = index[name]
            lines.append(f"  [{meta['type'].upper()}] {name} — {meta['file']}:{meta['line']}")
        if len(partial_matches) > 10:
            lines.append(f"  ... and {len(partial_matches) - 10} more.")

    lines.append("\nUse the exact name shown above to retrieve full metadata.")
    return "\n".join(lines)


def search_usages(
    working_dir: str,
    symbol_name: str,
    pattern: str = "**/*.py",
) -> str:
    """
    Find every place a symbol is referenced across the codebase.
    Useful for adding "Used by:" notes to docstrings and docs.

    Args:
        working_dir:  Root directory to search within (also used as jail).
        symbol_name:  The symbol to search for, e.g. "AuthToken".
        pattern:      Glob pattern selecting which files to scan.

    Returns:
        A human-readable string listing all usages, or an error message.
    """
    if not symbol_name or not symbol_name.strip():
        return "Error: symbol_name must be a non-empty string."

    files_output = list_files(working_dir=working_dir, directory=".", pattern=pattern)

    if files_output.startswith(("PermissionError", "FileNotFoundError", "ValueError", "OSError")):
        return f"Failed to list files: {files_output}"

    if files_output.startswith("No files found"):
        return f"No files matched pattern '{pattern}' under '{working_dir}'."

    file_paths = files_output.strip().split("\n")

    abs_working_dir = os.path.realpath(working_dir)
    usages = []
    errors = []

    for rel_path in file_paths:
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, rel_path))

        try:
            with open(abs_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            errors.append(f"  {rel_path}: skipped (not valid UTF-8)")
            continue
        except OSError as e:
            errors.append(f"  {rel_path}: {e}")
            continue

        for line_number, line_content in enumerate(lines, start=1):
            if symbol_name in line_content:
                usages.append({
                    "file":    rel_path,
                    "line":    line_number,
                    "context": line_content.strip(),
                })

    if not usages and not errors:
        return f"No usages of '{symbol_name}' found across {len(file_paths)} file(s)."

    output_lines = [
        f"Found {len(usages)} usage(s) of '{symbol_name}' across {len(file_paths)} file(s):\n"
    ]

    # Group by file for readability
    current_file = None
    for usage in usages:
        if usage["file"] != current_file:
            current_file = usage["file"]
            output_lines.append(f"  {current_file}:")
        output_lines.append(f"    line {usage['line']:>4}: {usage['context']}")

    if errors:
        output_lines.append(f"\n{len(errors)} file(s) skipped due to errors:")
        output_lines.extend(errors)

    return "\n".join(output_lines)


def get_dependency_graph(
    working_dir: str,
    pattern: str = "**/*.py",
) -> str:
    """
    Resolve all import statements in a project and build a graph of
    inter-file dependencies. Used to generate architecture sections
    in README files and to determine documentation order.

    Args:
        working_dir: Root directory of the project (also used as jail).
        pattern:     Glob pattern selecting which files to analyze.

    Returns:
        A human-readable dependency graph string, or an error message.
    """
    files_output = list_files(working_dir=working_dir, directory=".", pattern=pattern)

    if files_output.startswith(("PermissionError", "FileNotFoundError", "ValueError", "OSError")):
        return f"Failed to list files: {files_output}"

    if files_output.startswith("No files found"):
        return f"No files matched pattern '{pattern}' under '{working_dir}'."

    file_paths = files_output.strip().split("\n")
    abs_working_dir = os.path.realpath(working_dir)

    # Build a set of known project modules from file paths
    # e.g. "src/auth/tokens.py" -> "src.auth.tokens" and "tokens"
    def path_to_module_variants(rel_path: str) -> set[str]:
        module = rel_path.replace(os.sep, ".").replace("/", ".")
        if module.endswith(".py"):
            module = module[:-3]
        if module.endswith(".__init__"):
            module = module[:-9]
        parts = module.split(".")
        # Return all suffixes: "src.auth.tokens", "auth.tokens", "tokens"
        return {".".join(parts[i:]) for i in range(len(parts))}

    # Map every module variant -> canonical rel_path
    module_to_file: dict[str, str] = {}
    for rel_path in file_paths:
        for variant in path_to_module_variants(rel_path):
            module_to_file[variant] = rel_path

    graph: dict[str, list[str]] = {}
    errors: list[str] = []

    def extract_imports(tree: ast.AST) -> list[str]:
        """Return all module names referenced by import statements in the AST."""
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Relative imports: prepend dots to signal relativity
                    level = node.level or 0
                    modules.append("." * level + node.module)
        return modules

    def resolve_relative(importing_file: str, dotted_module: str) -> str | None:
        """Resolve a relative import like '..utils' from a given file."""
        level = len(dotted_module) - len(dotted_module.lstrip("."))
        remainder = dotted_module.lstrip(".")

        parts = importing_file.replace(os.sep, "/").split("/")
        # Go up `level` directories from the importing file's package
        anchor_parts = parts[:-level] if level < len(parts) else []

        if remainder:
            candidate = ".".join(anchor_parts).replace("/", ".") + "." + remainder
        else:
            candidate = ".".join(anchor_parts).replace("/", ".")

        return module_to_file.get(candidate)

    for rel_path in file_paths:
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, rel_path))

        try:
            with open(abs_file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
        except SyntaxError as e:
            errors.append(f"  {rel_path}: SyntaxError: {e}")
            graph[rel_path] = []
            continue
        except UnicodeDecodeError:
            errors.append(f"  {rel_path}: skipped (not valid UTF-8)")
            graph[rel_path] = []
            continue
        except OSError as e:
            errors.append(f"  {rel_path}: OSError: {e}")
            graph[rel_path] = []
            continue

        raw_imports = extract_imports(tree)
        resolved_deps = []

        for mod in raw_imports:
            if mod.startswith("."):
                # Relative import
                resolved = resolve_relative(rel_path, mod)
            else:
                resolved = module_to_file.get(mod)

            if resolved and resolved != rel_path and resolved not in resolved_deps:
                resolved_deps.append(resolved)

        graph[rel_path] = sorted(resolved_deps)

    # Build output
    output_lines = [
        f"Dependency graph for {len(graph)} file(s) "
        f"(pattern: '{pattern}') under '{working_dir}':\n"
    ]

    # Topological sort (Kahn's algorithm) for documentation order
    from collections import deque
    in_degree = {f: 0 for f in graph}
    for deps in graph.values():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue = deque(sorted(f for f, deg in in_degree.items() if deg == 0))
    topo_order = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for dep in graph.get(node, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Detect cycles (any node not in topo_order)
    cyclic_files = [f for f in graph if f not in topo_order]

    output_lines.append("Dependencies per file:")
    for file in topo_order:
        deps = graph[file]
        if deps:
            output_lines.append(f"  {file}:")
            for dep in deps:
                output_lines.append(f"    -> {dep}")
        else:
            output_lines.append(f"  {file}: (no internal dependencies)")

    if cyclic_files:
        output_lines.append(f"\nCyclic dependency detected among {len(cyclic_files)} file(s):")
        for f in cyclic_files:
            output_lines.append(f"  {f} -> {graph[f]}")

    output_lines.append(f"\nSuggested documentation order (leaf modules first):")
    for i, file in enumerate(topo_order, 1):
        output_lines.append(f"  {i:>3}. {file}")

    if errors:
        output_lines.append(f"\n{len(errors)} file(s) had errors:")
        output_lines.extend(errors)

    return "\n".join(output_lines), graph


# ─────────────────────────────────────────────
# CONTEXT & METADATA TOOLS
# ─────────────────────────────────────────────

def read_project_manifest(
    working_dir: str,
    project_root: str = ".",
) -> dict | str:
    """
    Detect and parse the project's package manifest to extract metadata
    for use in README generation. Supports package.json (Node),
    pyproject.toml / setup.py (Python), and Cargo.toml (Rust).

    Args:
        working_dir:  Root directory to restrict file access (not exposed to agent).
        project_root: Root directory of the project (relative to working_dir).
                      Defaults to working_dir root.

    Returns:
        Normalised dict with keys (all optional, None if not found):
            - name         (str)      : Project name
            - version      (str)      : Current version
            - description  (str)      : Short description
            - license      (str)      : License identifier
            - dependencies (list[str]): Runtime dependency names
            - scripts      (dict)     : Named run scripts / entry points
            - manifest_file(str)      : Which file was actually parsed
        Or an error string if no manifest is found or something went wrong.
    """
    try:
        abs_working_dir  = os.path.realpath(working_dir)
        abs_project_root = os.path.realpath(os.path.join(abs_working_dir, project_root))

        if not abs_project_root.startswith(abs_working_dir + os.sep) and abs_project_root != abs_working_dir:
            return f"PermissionError: '{project_root}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_project_root):
            return f"FileNotFoundError: '{project_root}' does not exist."

        if not os.path.isdir(abs_project_root):
            return f"ValueError: '{project_root}' is not a directory."

        result: dict = {
            "name":          None,
            "version":       None,
            "description":   None,
            "license":       None,
            "dependencies":  [],
            "scripts":       {},
            "manifest_file": None,
        }

        # ── package.json (Node / npm / yarn) ──────────────────────────────────
        pkg_json = os.path.join(abs_project_root, "package.json")
        if os.path.isfile(pkg_json):
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            result["manifest_file"] = "package.json"
            result["name"]          = data.get("name")
            result["version"]       = data.get("version")
            result["description"]   = data.get("description")
            result["license"]       = data.get("license")
            result["dependencies"]  = list(data.get("dependencies", {}).keys())
            result["scripts"]       = data.get("scripts", {})
            return result

        # ── pyproject.toml (Python / PEP 621 or Poetry) ───────────────────────
        pyproject = os.path.join(abs_project_root, "pyproject.toml")
        if os.path.isfile(pyproject):
            if tomllib is None:
                result["manifest_file"] = "pyproject.toml"
                result["description"]   = (
                    "pyproject.toml found but tomllib/tomli is unavailable. "
                    "Install tomli (pip install tomli) for full parsing."
                )
                return result
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            # Support both PEP 621 [project] and Poetry [tool.poetry]
            project = data.get("project") or data.get("tool", {}).get("poetry", {})
            lic = project.get("license")
            deps = project.get("dependencies", [])
            result["manifest_file"] = "pyproject.toml"
            result["name"]          = project.get("name")
            result["version"]       = project.get("version")
            result["description"]   = project.get("description")
            result["license"]       = lic if isinstance(lic, str) else (lic.get("text") if isinstance(lic, dict) else None)
            result["dependencies"]  = list(deps.keys()) if isinstance(deps, dict) else list(deps)
            result["scripts"]       = project.get("scripts", {})
            return result

        # ── setup.py (Python / legacy) ─────────────────────────────────────────
        setup_py = os.path.join(abs_project_root, "setup.py")
        if os.path.isfile(setup_py):
            with open(setup_py, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            result["manifest_file"] = "setup.py"
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func_name = (
                    node.func.attr if isinstance(node.func, ast.Attribute) else
                    node.func.id   if isinstance(node.func, ast.Name)      else None
                )
                if func_name != "setup":
                    continue
                for kw in node.keywords:
                    v = kw.value
                    if kw.arg == "name" and isinstance(v, ast.Constant):
                        result["name"] = v.value
                    elif kw.arg == "version" and isinstance(v, ast.Constant):
                        result["version"] = str(v.value)
                    elif kw.arg == "description" and isinstance(v, ast.Constant):
                        result["description"] = v.value
                    elif kw.arg == "license" and isinstance(v, ast.Constant):
                        result["license"] = v.value
                    elif kw.arg == "install_requires" and isinstance(v, ast.List):
                        result["dependencies"] = [
                            elt.value for elt in v.elts if isinstance(elt, ast.Constant)
                        ]
                    elif kw.arg == "entry_points" and isinstance(v, ast.Dict):
                        for k_node, v_node in zip(v.keys, v.values):
                            if isinstance(k_node, ast.Constant) and isinstance(v_node, ast.List):
                                result["scripts"][k_node.value] = [
                                    elt.value for elt in v_node.elts
                                    if isinstance(elt, ast.Constant)
                                ]
            return result

        # ── Cargo.toml (Rust) ──────────────────────────────────────────────────
        cargo = os.path.join(abs_project_root, "Cargo.toml")
        if os.path.isfile(cargo):
            if tomllib is None:
                result["manifest_file"] = "Cargo.toml"
                result["description"]   = (
                    "Cargo.toml found but tomllib/tomli is unavailable. "
                    "Install tomli (pip install tomli) for full parsing."
                )
                return result
            with open(cargo, "rb") as f:
                data = tomllib.load(f)
            package = data.get("package", {})
            result["manifest_file"] = "Cargo.toml"
            result["name"]          = package.get("name")
            result["version"]       = package.get("version")
            result["description"]   = package.get("description")
            result["license"]       = package.get("license")
            result["dependencies"]  = list(data.get("dependencies", {}).keys())
            return result

        return (
            f"FileNotFoundError: No supported manifest file found in '{project_root}'. "
            "Looked for: package.json, pyproject.toml, setup.py, Cargo.toml."
        )

    except json.JSONDecodeError as e:
        return f"ParseError: could not parse JSON manifest: {e}"
    except SyntaxError as e:
        return f"SyntaxError: could not parse setup.py: {e}"
    except OSError as e:
        return f"OSError: could not read manifest in '{project_root}': {e}"


def get_git_context(
    working_dir: str,
    project_root: str = ".",
    max_commits: int = 20,
) -> dict | str:
    """
    Extract git metadata to enrich documentation with project history.
    Reads recent commit messages, the latest tag/version, and top
    contributors for "Recent Changes" and "Authors" README sections.

    Args:
        working_dir:  Root directory to restrict file access (not exposed to agent).
        project_root: Root directory of the git repository (relative to working_dir).
                      Defaults to working_dir root.
        max_commits:  Maximum number of recent commits to return. Defaults to 20.

    Returns:
        Dict containing:
            - commits      (list[dict]): Recent commits, each with
                                         "hash", "message", "author", "date"
            - latest_tag   (str|None)  : Most recent git tag, e.g. "v1.2.0"
            - contributors (list[str]) : Author names sorted by commit count
        Or an error string if the directory is not a git repo or something went wrong.
    """
    try:
        abs_working_dir  = os.path.realpath(working_dir)
        abs_project_root = os.path.realpath(os.path.join(abs_working_dir, project_root))

        if not abs_project_root.startswith(abs_working_dir + os.sep) and abs_project_root != abs_working_dir:
            return f"PermissionError: '{project_root}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_project_root):
            return f"FileNotFoundError: '{project_root}' does not exist."

        if not os.path.isdir(abs_project_root):
            return f"ValueError: '{project_root}' is not a directory."

        def _git(*args: str) -> tuple[str, int]:
            proc = subprocess.run(
                ["git", *args],
                cwd=abs_project_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return proc.stdout.strip(), proc.returncode

        # Verify this is an actual git repository
        _, rc = _git("rev-parse", "--git-dir")
        if rc != 0:
            return f"ValueError: '{project_root}' is not a git repository (or git is not initialised)."

        # ── Recent commits ─────────────────────────────────────────────────────
        log_out, _ = _git(
            "log",
            f"--max-count={max_commits}",
            "--format=%H|%s|%an|%ai",
        )
        commits: list[dict] = []
        for line in (log_out.splitlines() if log_out else []):
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash":    parts[0][:8],
                    "message": parts[1],
                    "author":  parts[2],
                    "date":    parts[3],
                })

        # ── Latest tag ─────────────────────────────────────────────────────────
        tag_out, rc = _git("describe", "--tags", "--abbrev=0")
        latest_tag: str | None = tag_out if rc == 0 and tag_out else None

        # ── Contributors sorted by commit count (descending) ───────────────────
        contrib_out, _ = _git("shortlog", "-sn", "--no-merges", "HEAD")
        contributors: list[str] = []
        for line in (contrib_out.splitlines() if contrib_out else []):
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                contributors.append(parts[1])

        return {
            "commits":      commits,
            "latest_tag":   latest_tag,
            "contributors": contributors,
        }

    except subprocess.TimeoutExpired:
        return "TimeoutError: git command timed out after 15 seconds."
    except FileNotFoundError:
        return "EnvironmentError: 'git' executable not found. Ensure git is installed and in PATH."
    except OSError as e:
        return f"OSError: could not run git in '{project_root}': {e}"


def read_environment_schema(
    working_dir: str,
    project_root: str = ".",
) -> list[dict] | str:
    """
    Parse environment variable definitions from .env.example, .env.sample,
    or similar files to auto-generate a Configuration section in the README.

    Args:
        working_dir:  Root directory to restrict file access (not exposed to agent).
        project_root: Root directory to search for env example files (relative to working_dir).
                      Defaults to working_dir root.

    Returns:
        List of env variable dicts, each containing:
            - name        (str)      : Variable name, e.g. "DATABASE_URL"
            - default     (str|None) : Default value if provided
            - description (str|None) : Inline comment from the file, if any
            - required    (bool)     : True if no default is set
        Or an error string if no env file is found or something went wrong.
    """
    try:
        abs_working_dir  = os.path.realpath(working_dir)
        abs_project_root = os.path.realpath(os.path.join(abs_working_dir, project_root))

        if not abs_project_root.startswith(abs_working_dir + os.sep) and abs_project_root != abs_working_dir:
            return f"PermissionError: '{project_root}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_project_root):
            return f"FileNotFoundError: '{project_root}' does not exist."

        if not os.path.isdir(abs_project_root):
            return f"ValueError: '{project_root}' is not a directory."

        # Candidate filenames in priority order
        candidates = [".env.example", ".env.sample", ".env.template", ".env.defaults"]
        env_file: str | None = None
        for name in candidates:
            candidate = os.path.join(abs_project_root, name)
            if os.path.isfile(candidate):
                env_file = candidate
                break

        if env_file is None:
            return (
                f"FileNotFoundError: No env schema file found in '{project_root}'. "
                f"Looked for: {', '.join(candidates)}."
            )

        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        schema: list[dict] = []
        for raw in lines:
            line = raw.strip()

            # Skip blank lines and standalone comment lines
            if not line or line.startswith("#"):
                continue

            # Split off an inline comment before parsing the key/value
            description: str | None = None
            if "#" in line:
                code_part, _, comment_part = line.partition("#")
                description = comment_part.strip() or None
                line = code_part.strip()

            if not line:
                continue

            # KEY=value  or  KEY=  or  bare KEY
            if "=" in line:
                var_name, _, default_raw = line.partition("=")
                var_name = var_name.strip()
                default: str | None = default_raw.strip() or None
            else:
                var_name = line.strip()
                default = None

            if not var_name:
                continue

            schema.append({
                "name":        var_name,
                "default":     default,
                "description": description,
                "required":    default is None,
            })

        if not schema:
            return f"No environment variable definitions found in '{os.path.basename(env_file)}'."

        return schema

    except UnicodeDecodeError:
        return f"UnicodeDecodeError: env file in '{project_root}' is not valid UTF-8."
    except OSError as e:
        return f"OSError: could not read env file in '{project_root}': {e}"


# ─────────────────────────────────────────────
# VALIDATION TOOLS
# ─────────────────────────────────────────────

def check_syntax(
    working_dir: str,
    file_path: str,
) -> dict | str:
    """
    Verify that a source file is syntactically valid after the agent
    has modified it. Prevents the agent from committing broken files.

    Args:
        working_dir: Root directory to restrict file access (not exposed to agent).
        file_path:   Path to the file to validate (relative to working_dir).

    Returns:
        Dict with:
            - valid   (bool)     : True if the file parses without errors
            - error   (str|None) : Error message if invalid, else None
            - line    (int|None) : Line number of the error if available
        Or an error string if the file cannot be read or is outside working_dir.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

        if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
            return f"PermissionError: '{file_path}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_file_path):
            return f"FileNotFoundError: '{file_path}' does not exist."

        if not os.path.isfile(abs_file_path):
            return f"ValueError: '{file_path}' is not a file."

        with open(abs_file_path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            ast.parse(source, filename=file_path)
            return {"valid": True, "error": None, "line": None}
        except SyntaxError as e:
            return {
                "valid": False,
                "error": f"{type(e).__name__}: {e.msg} (at '{file_path}':{e.lineno})",
                "line":  e.lineno,
            }

    except UnicodeDecodeError:
        return f"UnicodeDecodeError: '{file_path}' is not valid UTF-8 and cannot be read as text."
    except OSError as e:
        return f"OSError: could not read '{file_path}': {e}"


def diff_file(
    working_dir: str,
    file_path: str,
    new_content: str,
) -> str:
    """
    Produce a unified diff between the current content of a file and
    a proposed new version. Use this before writing to let the agent
    review changes and avoid redundant rewrites.

    Args:
        working_dir: Root directory to restrict file access (not exposed to agent).
        file_path:   Path to the existing file to compare against (relative to working_dir).
        new_content: The proposed new content as a string.

    Returns:
        A unified diff string (same format as `diff -u`).
        Returns an empty string if there are no differences.
        Returns an error string if the file cannot be read or is outside working_dir.
    """
    try:
        abs_working_dir = os.path.realpath(working_dir)
        abs_file_path = os.path.realpath(os.path.join(abs_working_dir, file_path))

        if not abs_file_path.startswith(abs_working_dir + os.sep) and abs_file_path != abs_working_dir:
            return f"PermissionError: '{file_path}' resolves outside working directory '{working_dir}'."

        if not os.path.exists(abs_file_path):
            return f"FileNotFoundError: '{file_path}' does not exist."

        if not os.path.isfile(abs_file_path):
            return f"ValueError: '{file_path}' is not a file."

        with open(abs_file_path, "r", encoding="utf-8") as f:
            original = f.read()

        if original == new_content:
            return ""

        diff_lines = difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )

        return "".join(diff_lines)

    except UnicodeDecodeError:
        return f"UnicodeDecodeError: '{file_path}' is not valid UTF-8 and cannot be read as text."
    except OSError as e:
        return f"OSError: could not read '{file_path}': {e}"
