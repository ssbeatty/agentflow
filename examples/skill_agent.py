"""
Using Skills with an agent.

A **Skill** is a reusable folder of instructions (a `SKILL.md` plus optional
supporting files) that you manage globally under AgentFlow > Tools > Skills —
just like MCP servers. Once you *bind* one or more skills to this script,
`get_agent()` wires them in automatically. You write NO extra code:

  - each bound skill's **name + description** is added to the system prompt, and
  - a built-in **`read_skill`** tool is attached; the agent calls it to load a
    skill's full `SKILL.md` only when the task matches (Agent Skills
    "progressive disclosure" — the model isn't force-fed every instruction).

This keeps prompts small: the agent sees a short menu of skills and pulls in the
full body on demand.

Prerequisites:
  1. AgentFlow > Tools > Skills > New — create a skill (a starter `SKILL.md` is
     seeded for you). Give it a clear `name` + `description`; the description is
     what the agent matches against, so make it specific.
  2. Open this script's right panel and **enable the skill for this script**
     (stored as `script.skill_ids`). A skill runs only when it is bound here
     AND globally `enabled`.
  3. Configure an LLM channel in Settings (get_agent needs a default LLM).

How to use:
  1. Copy this file into a new AgentFlow script (main.py); entry function "run".
  2. Bind your skill(s) in the right panel.
  3. Open the script in /converse and chat. When your request matches a skill's
     description, watch the log strip: the agent calls `read_skill` to load it,
     then answers following those instructions.

Input  : {"message": str, "history": [{"role": str, "content": str}]}
Output : {"reply": str}
"""
from agentflow import token, get_agent, log, list_skills

SYSTEM_PROMPT = """You are a helpful assistant.
You have one or more skills available (listed below). When the user's request
matches a skill's description, call the `read_skill` tool with that skill's name
to load its full instructions, then follow them exactly. If no skill applies,
just answer normally."""


async def run(input: dict) -> dict:
    # Optional: surface which skills are bound to this run in the log strip.
    # (Purely informational — the agent already knows them via the system prompt.)
    bound = list_skills()  # -> [{"name": ..., "description": ...}, ...]
    if bound:
        log("Bound skills: " + ", ".join(s["name"] for s in bound), step="skills")
    else:
        log("No skills bound — enable one in the script's right panel.", step="skills")

    # This is a chat-shaped script: it expects {"message": ...}. In /converse the
    # chat UI sends that automatically; when testing on the script page, put e.g.
    # {"message": "say hi like a pirate"} in the input box. Guard so a missing
    # key returns a helpful reply instead of a KeyError.
    user_msg = input.get("message") or input.get("text") or ""
    if not user_msg:
        return {"reply": "No 'message' in input. Chat via /converse, or test on "
                         "the script page with input like "
                         '{"message": "say hi like a pirate"}.'}

    # get_agent() auto-injects the skill preamble + the `read_skill` tool.
    # Nothing skill-specific to configure here.
    agent = get_agent(system_prompt=SYSTEM_PROMPT)

    history = [(m["role"], m["content"]) for m in input.get("history", [])]
    messages = history + [("human", user_msg)]

    full_reply = ""
    async for event in agent.astream_events({"messages": messages}, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                token(content)          # stream tokens to the chat UI
                full_reply += content

        elif kind == "on_tool_start":
            # The agent loading a skill shows up here as tool "read_skill".
            log(f"Using tool: {event['name']}", step="tool")

    return {"reply": full_reply}


# ── Alternative: use a skill WITHOUT an agent ─────────────────────────────────
# If you don't need a ReAct agent, read a bound skill's instructions directly and
# drive the LLM yourself (or just act on them in plain Python). Handy for a fixed
# pipeline where you always apply the same skill.
#
#   from agentflow import get_llm, get_skill, skill_path
#
#   def run(input: dict) -> dict:
#       instructions = get_skill("my-skill")     # full SKILL.md text, or None
#       if instructions is None:
#           return {"reply": "Skill 'my-skill' is not bound to this script."}
#
#       # Supporting files live next to SKILL.md — read them via skill_path():
#       #   ref = (skill_path("my-skill") / "reference.md").read_text("utf-8")
#
#       llm = get_llm()  # default channel
#       prompt = f"{instructions}\n\nUser request:\n{input['message']}"
#       return {"reply": llm.invoke(prompt).content}
