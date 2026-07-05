"""
Giving an agent sandboxed exec: bash + a Python interpreter.

By default an agent has NO way to run commands or code. AgentFlow ships two
sandboxed exec tools, but they are **opt-in** (they run arbitrary
commands/code, so they're never auto-attached — you add them on purpose):

  - `bash_tool()`   → a tool named `bash` that runs a shell command.
  - `python_tool()` → a tool named `python` that runs Python (installed packages
                      like numpy/pandas are importable; the final bare
                      expression is echoed, notebook-style).
  - `exec_tools()`  → just `[bash_tool(), python_tool()]` for the common case.

Hand them to the agent explicitly alongside the normal tools:

      agent = get_agent(tools=get_tools() + exec_tools())

What the sandbox guarantees (see agentflow/_sandbox.py): the child process runs
with a scrubbed environment (NONE of your AgentFlow secrets / LLM keys are
visible to it), CPU / memory / file-size limits, a wall-clock timeout that kills
the whole process group, and a throwaway working directory. It is *process*-level
isolation, not a language jail — the code can still read/write files in its temp
cwd — so only enable it for scripts you trust to have that capability.

Giving the sandbox access to files (both knobs work on run_bash/run_python and
on the tool factories):
  - files={"data.csv": path_or_bytes} copies inputs into the sandbox cwd —
    the code reads "data.csv" by relative path; originals stay untouched.
  - cwd=os.environ["AGENTFLOW_WORKSPACE_DIR"] runs in the persistent workspace
    instead of a throwaway dir (the agent is told its working directory in the
    tool description). The sandboxed code can then modify those files — trade
    isolation for access deliberately.

Prerequisites:
  - Configure an LLM channel in Settings (get_agent needs a default LLM).

How to use:
  1. Copy this file into a new AgentFlow script (main.py); entry function "run".
  2. Open it in /converse and ask things that need computation or a command,
     e.g. "what's the standard deviation of 2,4,4,4,5,5,7,9?" or
     "how many .py files are in the current directory?" — watch the log strip:
     the agent calls the `python` / `bash` tool, then answers from the output.

Input  : {"message": str, "history": [{"role": str, "content": str}]}
Output : {"reply": str}
"""
from agentflow import token, log, get_agent, get_tools, exec_tools

SYSTEM_PROMPT = """You are a careful analyst assistant with two sandboxed tools:
- `python`: run Python for any calculation, data wrangling, or parsing. Prefer
  it over doing arithmetic in your head — compute the answer.
- `bash`: run shell commands to inspect files or shell out to CLIs.
Both run in an isolated sandbox with no access to secrets. Use a tool whenever
running code is more reliable than reasoning, then explain the result plainly."""


async def run(input: dict) -> dict:
    user_msg = input.get("message") or input.get("text") or ""
    if not user_msg:
        return {"reply": "No 'message' in input. Chat via /converse, or test on "
                         "the script page with input like "
                         '{"message": "compute the mean of [3, 1, 4, 1, 5, 9]"}.'}

    # The two exec tools are OPT-IN — get_tools() does NOT include them, so we
    # append them here on purpose. Use `+ [bash_tool()]` for bash only, or
    # `+ [python_tool()]` for python only. Pass timeout=<seconds> to override.
    agent = get_agent(
        system_prompt=SYSTEM_PROMPT,
        tools=get_tools() + exec_tools(),
        reasoning=input.get("reasoning"),
    )

    history = [(m["role"], m["content"]) for m in input.get("history", [])]
    messages = history + [("human", user_msg)]

    full_reply = ""
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                token(content)              # stream tokens to the chat UI
                full_reply += content
        elif kind == "on_tool_start":
            # Shows up as tool "python" or "bash" in the log strip.
            log(f"Using tool: {event['name']}", step="tool")

    return {"reply": full_reply}


# ── Alternative: run code directly, no agent ──────────────────────────────────
# The same sandboxes are plain SDK functions — call them yourself for a fixed
# pipeline (both return {"stdout", "stderr", "returncode", "timed_out"}):
#
#   from agentflow import run_python, run_bash
#
#   def run(input: dict) -> dict:
#       calc = run_python("import statistics; statistics.pstdev([2,4,4,4,5,5,7,9])")
#       files = run_bash("ls -1 *.py | wc -l", timeout=10)
#       return {"reply": f"stdev={calc['stdout'].strip()} "
#                        f"py_files={files['stdout'].strip()}"}
