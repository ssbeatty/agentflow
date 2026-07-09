"""Conversation threading (durable per-conversation agent state).

A /converse conversation is a LangGraph thread (thread_id == conversation id)
persisted to workspace/threads.db, so a chat agent keeps context across turns and
reads a bound skill only ONCE instead of every turn. These tests drive the real
`agentflow` SDK path (get_agent + stream_agent) with a fake tool-capable model —
no LLM, no network — plus the backend rollback helpers in
`services.conversation_threads`.
"""
import asyncio
import os
from pathlib import Path

import nest_asyncio
nest_asyncio.apply()

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class _RecordingModel(BaseChatModel):
    """A tool-capable fake chat model that records what it was asked to generate,
    so a test can assert the model saw prior turns (cross-turn memory)."""

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        _RecordingModel.seen.append([str(getattr(m, "content", "")) for m in messages])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw):
        _RecordingModel.seen.append([str(getattr(m, "content", "")) for m in messages])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    @property
    def _llm_type(self):
        return "recording"

    def bind_tools(self, tools, **kw):
        return self


def _setup(tmp_path, monkeypatch, thread_id="conv-1"):
    """Point the SDK at an isolated workspace + thread + fake model."""
    import agentflow as af

    _RecordingModel.seen = []
    af._THREAD_CHECKPOINTERS.clear()           # no cross-test connection reuse
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGENTFLOW_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("AGENTFLOW_THREAD_ID", thread_id)
    monkeypatch.delenv("AGENTFLOW_THREAD_CHECKPOINT", raising=False)
    monkeypatch.setenv("AGENTFLOW_EXECUTION_ID", "test")
    monkeypatch.setattr(af, "get_llm", lambda *a, **k: _RecordingModel())
    af._injected_tools = []
    return af, ws


def test_state_persists_across_turns(tmp_path, monkeypatch):
    """Turn 2 must see turn 1 without it being re-sent — the checkpointer supplies
    it. This is the mechanism that makes a read skill stick after one read."""
    af, ws = _setup(tmp_path, monkeypatch)

    async def go():
        agent = af.get_agent(system_prompt="SYS", tools=[])
        assert af._agent_checkpointer(agent) is not None, "checkpointer not attached"

        await af.stream_agent(agent, [("human", "remember apple")])
        await af.stream_agent(agent, [("human", "second turn")])

        # both turns persisted in the thread
        st = await agent.aget_state({"configurable": {"thread_id": "conv-1"}})
        assert len(st.values["messages"]) >= 4
        # the model on turn 2 saw turn 1's content (cross-turn memory)
        turn2_input = " ".join(_RecordingModel.seen[-1])
        assert "remember apple" in turn2_input
        # the durable db really exists on disk
        assert (ws / "threads.db").exists()

    asyncio.run(go())


def test_only_new_message_is_sent(tmp_path, monkeypatch):
    """A script that still prepends history (history + [new]) must not double it:
    stream_agent reduces to the current turn, the checkpointer holds the rest."""
    af, _ = _setup(tmp_path, monkeypatch)

    async def go():
        agent = af.get_agent(tools=[])
        await af.stream_agent(agent, [("human", "turn one")])
        # simulate a script wrongly re-feeding the whole visible history
        await af.stream_agent(
            agent,
            [("human", "turn one"), ("assistant", "ok"), ("human", "turn two")],
        )
        st = await agent.aget_state({"configurable": {"thread_id": "conv-1"}})
        contents = [str(m.content) for m in st.values["messages"]]
        # "turn one" appears exactly once — the re-fed copy was dropped
        assert contents.count("turn one") == 1
        assert "turn two" in contents

    asyncio.run(go())


def test_non_threaded_agent_is_stateless(tmp_path, monkeypatch):
    """No thread env → no checkpointer → classic stateless agent (unchanged)."""
    af, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("AGENTFLOW_THREAD_ID", raising=False)

    async def go():
        agent = af.get_agent(system_prompt="SYS", tools=[])
        assert af._agent_checkpointer(agent) is None

    asyncio.run(go())


def test_opt_out_checkpointer_false(tmp_path, monkeypatch):
    af, _ = _setup(tmp_path, monkeypatch)

    async def go():
        agent = af.get_agent(tools=[], checkpointer=False)
        assert af._agent_checkpointer(agent) is None

    asyncio.run(go())


def test_read_head_and_reset(tmp_path, monkeypatch):
    """The backend can read the thread's head checkpoint and wipe the thread —
    the two operations that drive rollback from confirm_reply / chat_start."""
    from services.venv_manager import get_script_dir
    from services import conversation_threads as ct

    script_id = "script-thread-test"
    ws = get_script_dir(script_id) / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    import agentflow as af
    _RecordingModel.seen = []
    af._THREAD_CHECKPOINTERS.clear()
    monkeypatch.setenv("AGENTFLOW_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("AGENTFLOW_THREAD_ID", "conv-xyz")
    monkeypatch.delenv("AGENTFLOW_THREAD_CHECKPOINT", raising=False)
    monkeypatch.setenv("AGENTFLOW_EXECUTION_ID", "test")
    monkeypatch.setattr(af, "get_llm", lambda *a, **k: _RecordingModel())
    af._injected_tools = []

    async def go():
        agent = af.get_agent(tools=[])
        await af.stream_agent(agent, [("human", "hi")])

    asyncio.run(go())

    # no threads.db for an unknown script → None (never raises)
    assert ct.read_head_checkpoint("no-such-script", "conv-xyz") is None
    head = ct.read_head_checkpoint(script_id, "conv-xyz")
    assert head, "expected a head checkpoint after a threaded turn"

    ct.reset_thread(script_id, "conv-xyz")
    assert ct.read_head_checkpoint(script_id, "conv-xyz") is None


def test_delete_conversation_reclaims_thread(db, monkeypatch):
    """Deleting a conversation must wipe its thread from threads.db so its
    checkpoints don't linger (a deleted conversation is never resumed)."""
    from app.models import Script, Conversation
    from app.routers import conversations as conv_router

    s = Script(id="s-del", name="chatbot")
    db.add(s)
    db.commit()
    c = Conversation(script_id="s-del", title="t")
    db.add(c)
    db.commit()
    conv_id = c.id

    calls = []
    monkeypatch.setattr(
        conv_router.conversation_threads, "reset_thread",
        lambda sid, tid: calls.append((sid, tid)),
    )
    conv_router.delete_conversation(conv_id, db=db)

    assert calls == [("s-del", conv_id)]
    assert db.query(Conversation).filter_by(id=conv_id).first() is None


def test_rollback_forks_from_anchor(tmp_path, monkeypatch):
    """Passing an older checkpoint as the anchor forks the thread there (the
    rollback chat_start performs when a later turn was deleted)."""
    af, _ = _setup(tmp_path, monkeypatch)

    async def go():
        agent = af.get_agent(tools=[])
        cfg = {"configurable": {"thread_id": "conv-1"}}

        await af.stream_agent(agent, [("human", "q1")])
        head_after_t1 = (await agent.aget_state(cfg)).config["configurable"]["checkpoint_id"]
        await af.stream_agent(agent, [("human", "q2")])

        # roll back: a new turn anchored at the post-turn-1 checkpoint
        await af.stream_agent(agent, [("human", "q2-redo")], checkpoint_id=head_after_t1)

        contents = [str(m.content) for m in (await agent.aget_state(cfg)).values["messages"]]
        assert "q2-redo" in contents
        assert "q2" not in contents  # the forked-away turn is gone from the head

    asyncio.run(go())
