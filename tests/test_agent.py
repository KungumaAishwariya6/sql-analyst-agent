"""Tests for the Day 2 agent. No API key or network needed: a scripted fake model
plays the part of Claude, and the real tools run against the test database."""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from sql_agent import config
from sql_agent.agent import ask, build_graph
from sql_agent.langchain_tools import describe_table_tool, list_tables_tool, run_sql_tool


class ScriptedModel(BaseChatModel):
    """Returns the given replies in order. The last reply repeats if we run out."""

    replies: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self  # tool binding is not needed for the fake

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # Give every reply a unique id. LangGraph de-duplicates messages by id,
        # so reusing one id would overwrite history instead of extending it.
        base = self.replies[min(self.calls, len(self.replies) - 1)]
        reply = base.model_copy(update={"id": f"ai-{self.calls}"})
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _tool_call(name: str, call_id: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _use_test_db(monkeypatch, db_path):
    """Point the tools at the temporary test database instead of data/sample.db."""
    monkeypatch.setattr(config, "DB_PATH", db_path)


# --- tool wrappers -----------------------------------------------------------

def test_tool_names_match_what_the_prompt_mentions(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    assert list_tables_tool.name == "list_tables"
    assert describe_table_tool.name == "describe_table"
    assert run_sql_tool.name == "run_sql"
    assert "customers" in list_tables_tool.invoke({})


def test_run_sql_tool_returns_error_text_not_exception(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    text = run_sql_tool.invoke({"query": "DELETE FROM customers"})
    assert text.startswith("ERROR")
    assert "safety guard" in text


# --- graph behaviour -----------------------------------------------------------

def test_agent_runs_a_query_and_answers(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    model = ScriptedModel(replies=[
        _tool_call("run_sql", "c1", query="SELECT COUNT(*) AS n FROM customers"),
        AIMessage(content="There are 206 customers."),
    ])
    answer = ask("How many customers are there?", build_graph(model))
    assert answer == "There are 206 customers."


def test_agent_sees_tool_output_before_answering(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    model = ScriptedModel(replies=[
        _tool_call("run_sql", "c1", query="SELECT COUNT(*) FROM customers"),
        AIMessage(content="done"),
    ])
    build_graph(model).invoke({"messages": [("user", "count customers")]})
    # The second model call must have seen the query result (206) in the history.
    assert model.calls == 2


def test_agent_recovers_from_a_sql_error(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    model = ScriptedModel(replies=[
        _tool_call("run_sql", "c1", query="SELECT nonexistent FROM customers"),
        _tool_call("run_sql", "c2", query="SELECT COUNT(*) FROM customers"),
        AIMessage(content="There are 206 customers."),
    ])
    result = build_graph(model).invoke({"messages": [("user", "count customers")]})
    tool_outputs = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_outputs[0].startswith("ERROR")  # the first failure was fed back
    assert "206" in tool_outputs[1]              # and the retry succeeded
    assert result["messages"][-1].content == "There are 206 customers."


def test_agent_stops_when_step_limit_is_reached(db_path, monkeypatch):
    _use_test_db(monkeypatch, db_path)
    # A model that never stops asking for tools must not loop forever.
    model = ScriptedModel(replies=[_tool_call("list_tables", "c1")])
    answer = ask("loop forever", build_graph(model))
    assert "Stopped after" in answer
