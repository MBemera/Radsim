"""Code intelligence tools for RadSim.

RadSim Principle: One Function, One Purpose
"""

import ast
import re

from .search import grep_search
from .validation import validate_path


def find_definition(symbol, directory_path="."):
    """Find where a symbol is defined (function, class, variable).

    Args:
        symbol: The symbol name to find
        directory_path: Directory to search

    Returns:
        dict with success, definitions
    """
    # Common definition patterns by language
    patterns = [
        rf"def\s+{re.escape(symbol)}\s*\(",  # Python function
        rf"class\s+{re.escape(symbol)}\s*[:\(]",  # Python/JS class
        rf"function\s+{re.escape(symbol)}\s*\(",  # JS function
        rf"const\s+{re.escape(symbol)}\s*=",  # JS const
        rf"let\s+{re.escape(symbol)}\s*=",  # JS let
        rf"var\s+{re.escape(symbol)}\s*=",  # JS var
        rf"func\s+{re.escape(symbol)}\s*\(",  # Go function
        rf"type\s+{re.escape(symbol)}\s+",  # Go type
        rf"fn\s+{re.escape(symbol)}\s*[\(<]",  # Rust function
        rf"struct\s+{re.escape(symbol)}\s*\{{",  # Rust/Go struct
        rf"interface\s+{re.escape(symbol)}\s*\{{",  # Go/TS interface
        rf"export\s+(default\s+)?(function|class|const|let)\s+{re.escape(symbol)}",  # ES6 export
    ]

    combined_pattern = "|".join(f"({p})" for p in patterns)

    result = grep_search(combined_pattern, directory_path)
    if not result["success"]:
        return result

    return {
        "success": True,
        "symbol": symbol,
        "definitions": result["matches"],
        "count": len(result["matches"]),
    }


def find_references(symbol, directory_path="."):
    """Find all references to a symbol.

    Args:
        symbol: The symbol name to find
        directory_path: Directory to search

    Returns:
        dict with success, references
    """
    # Find the symbol as a word boundary
    pattern = rf"\b{re.escape(symbol)}\b"

    result = grep_search(pattern, directory_path)
    if not result["success"]:
        return result

    return {
        "success": True,
        "symbol": symbol,
        "references": result["matches"],
        "count": len(result["matches"]),
    }


def analyze_code(file_path, analysis_type="full"):
    """Analyze Python code using AST for structure and metrics.

    Args:
        file_path: Path to the Python file to analyze
        analysis_type: Type of analysis ('full', 'functions', 'classes', 'imports', 'complexity')

    Returns:
        dict with success, analysis results
    """
    is_safe, path, error = validate_path(file_path)
    if not is_safe:
        return {"success": False, "error": error}

    try:
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        if not str(path).endswith(".py"):
            return {"success": False, "error": "analyze_code only supports Python files (.py)"}

        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        result = {
            "success": True,
            "file": str(path),
            "analysis_type": analysis_type,
        }

        # Extract functions
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "args": [arg.arg for arg in node.args.args],
                    "decorators": [
                        ast.unparse(d) if hasattr(ast, "unparse") else str(d)
                        for d in node.decorator_list
                    ],
                    "docstring": ast.get_docstring(node) or "",
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                }
                # Calculate basic complexity (branches)
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                func_info["complexity"] = complexity
                functions.append(func_info)

        # Extract classes
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name
                    for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "bases": [
                            ast.unparse(b) if hasattr(ast, "unparse") else str(b)
                            for b in node.bases
                        ],
                        "methods": methods,
                        "docstring": ast.get_docstring(node) or "",
                    }
                )

        # Extract imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        {"module": alias.name, "alias": alias.asname, "line": node.lineno}
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(
                        {
                            "module": f"{module}.{alias.name}" if module else alias.name,
                            "from": module,
                            "name": alias.name,
                            "alias": alias.asname,
                            "line": node.lineno,
                        }
                    )

        # Build result based on analysis type
        if analysis_type == "functions":
            result["functions"] = functions
        elif analysis_type == "classes":
            result["classes"] = classes
        elif analysis_type == "imports":
            result["imports"] = imports
        elif analysis_type == "complexity":
            result["functions"] = [
                {"name": f["name"], "complexity": f["complexity"], "line": f["line"]}
                for f in functions
            ]
            total_complexity = sum(f["complexity"] for f in functions)
            result["total_complexity"] = total_complexity
            result["average_complexity"] = (
                round(total_complexity / len(functions), 2) if functions else 0
            )
        else:  # full
            result["functions"] = functions
            result["classes"] = classes
            result["imports"] = imports
            result["lines_of_code"] = len(content.splitlines())
            result["function_count"] = len(functions)
            result["class_count"] = len(classes)
            result["import_count"] = len(imports)

        return result

    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error in file: {e}"}
    except Exception as error:
        return {"success": False, "error": str(error)}
