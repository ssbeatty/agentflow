"""
Deep Agent with multi-file Skills.

`get_deep_agent()` builds a LangChain **Deep Agent** (deepagents) instead of the
plain ReAct agent from `get_agent()`. The difference that matters for skills:

  - `get_agent()`  → one `read_skill` tool that returns a skill's SKILL.md text.
  - `get_deep_agent()` → mounts this run's `skills/` directory through a
    FilesystemBackend, so the agent can **browse and read every file in a skill
    itself** (SKILL.md + supporting files + nested folders) via built-in
    filesystem tools — plus it gets deepagents' planning + sub-agent machinery.

Use this when your skills bundle reference files (templates, data, examples,
sub-docs) that the agent should open on its own, not just the SKILL.md.

Skill selection is identical to get_agent(): bind skills to this script in the
right panel (`script.skill_ids`); they're materialized to `run_dir/skills/<name>/`.

Prerequisites:
  1. AgentFlow > Tools > Skills > New — create a skill, then upload supporting
     files (drag a folder in to keep its structure, e.g. `references/api.md`).
     Reference those files from SKILL.md by their relative path.
  2. Bind the skill to this script (right panel).
  3. Configure an LLM channel in Settings.
  4. `deepagents` is in the baseline venv; if you trimmed it, add `deepagents`
     to this script's requirements.txt.

How to use:
  1. Copy this file into a new AgentFlow script (main.py); entry function "run".
  2. Bind your skill(s); open the script in /converse and chat.
  3. Watch the log strip: the agent uses filesystem tools (ls / read_file) to
     open skill files as it needs them.

Input  : {"message": str, "history": [{"role": str, "content": str}]}
Output : {"reply": str}
"""
from agentflow import token, get_deep_agent, log, list_skills

SYSTEM_PROMPT = """You are a capable assistant with access to skills mounted on
your filesystem under ./skills/. When a request matches a skill, open its
SKILL.md, follow the instructions, and read any supporting files it references
before answering."""


async def run(input: dict) -> dict:
    bound = list_skills()
    if bound:
        log("Bound skills: " + ", ".join(s["name"] for s in bound), step="skills")
    else:
        log("No skills bound — enable one in the script's right panel.", step="skills")

    user_msg = input.get("message") or input.get("text") or ""
    if not user_msg:
        return {"reply": "No 'message' in input. Chat via /converse, or test on "
                         'the script page with input like {"message": "..."}.'}

    # get_deep_agent() mounts run_dir/skills/ and wires deepagents automatically.
    agent = get_deep_agent(system_prompt=SYSTEM_PROMPT)

    history = [(m["role"], m["content"]) for m in input.get("history", [])]
    messages = history + [("human", user_msg)]

    full_reply = ""
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                token(content)
                full_reply += content
        elif kind == "on_tool_start":
            # e.g. ls / read_file as the agent explores a skill's files.
            log(f"Using tool: {event['name']}", step="tool")

    if not full_reply:
        # Some deep-agent configs don't stream text; fall back to the final message.
        result = await agent.ainvoke({"messages": messages})
        msgs = result.get("messages") if isinstance(result, dict) else None
        if msgs:
            full_reply = getattr(msgs[-1], "content", "") or ""

    return {"reply": full_reply}
