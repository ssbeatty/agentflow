"""
Import a reusable MODULE from a script.

This is the *consumer* side of the module pattern — see `reusable_module.py` for
the module itself. Once you've created a module (package name `textutils`) and
bound it to this script (Config > Resources > add the module), you import it by
its package name just like any library:

    from textutils import strip_tags, word_count

The engine materializes each bound module's files under this script's
`script_dir/modules/<package>/` and puts it on sys.path at run time — no install,
no copy-paste. The module's own requirements install into THIS script's venv, so
after binding a module re-run the venv Install.

Prerequisites:
  1. Create the module `Text Utilities` (package `textutils`) with the code from
     `reusable_module.py`.
  2. Copy THIS file into a new script (main.py), entry function "run".
  3. Config > Resources > add the "Text Utilities" module, then Install the venv.

Input  : {"html": str}
Output : {"text": str, "words": int, "preview": str}
"""
from textutils import strip_tags, word_count, truncate   # from <package> import ...
from agentflow import log


def run(input: dict) -> dict:
    html = input.get("html", "<h1>Hello</h1><p>reusable <b>modules</b> in AgentFlow</p>")

    text = strip_tags(html)
    log("cleaned", data={"chars": len(text)}, step="clean")

    return {
        "text": text,
        "words": word_count(text),
        "preview": truncate(text, 120),
    }
