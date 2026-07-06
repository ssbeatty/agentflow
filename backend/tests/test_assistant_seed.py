"""Guard the built-in assistant's embedded script body.

`ASSISTANT_MAIN_PY` is a big triple-quoted template written verbatim to the
assistant's `main.py` and executed in a subprocess. A stray unescaped quote or a
non-ASCII char landing outside a string literal (e.g. an ellipsis after a `\"`
that collapsed the surrounding string) makes the assistant crash at import with a
SyntaxError — invisible until someone actually runs the assistant. This test
compiles the template so such a typo fails in CI instead.
"""
import ast

from services.assistant_seed import ASSISTANT_MAIN_PY


def test_assistant_main_py_compiles():
    ast.parse(ASSISTANT_MAIN_PY)


def test_assistant_main_py_has_entry_run():
    tree = ast.parse(ASSISTANT_MAIN_PY)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "run" in funcs, "assistant script must define the run() entry point"
