"""The LangGraph agent: turns a plain-English question into SQL and an answer.

Graph shape (a loop):

    START -> agent -> (model asked for a tool?) -yes-> tools -> agent
                              |
                              no
                              v
                             END

The model decides what to do next. Tool results (including SQL errors) go back
into the conversation, so the model can fix a bad query and try again.
"""

from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from sql_agent import config
from sql_agent.langchain_tools import AGENT_TOOLS

# Instructions for the model. The schema is not included here: the model
# discovers it with list_tables and describe_table, as the README describes.
SYSTEM_PROMPT = """You answer questions about a SQLite e-commerce database by writing SQL.

Workflow:
1. Call list_tables to see what exists.
2. Call describe_table for each table you need. Check column names and the
   meaning of status values before you write SQL.
3. Call run_sql with one SELECT (or WITH ... SELECT) query.
4. If run_sql returns an ERROR, read it, fix the query and retry.
5. Answer the question in plain English using the query results. Give the
   key numbers and say briefly how you got them.

Rules:
- Only read-only SELECT queries are allowed. Never try to change data.
- Results are capped at 100 rows. Use aggregates or LIMIT when you can.
- If the data cannot answer the question, say so instead of guessing.
- Note that orders.total is net of discount while order_items.amount is not."""


def build_graph(model: BaseChatModel | None = None):
    """Compile the agent graph.

    `model` can be passed in for tests (a scripted fake). By default it is
    Claude, using the model name and token limit from config.py.
    """
    base = model or ChatAnthropic(
        model=config.MODEL_NAME,
        # No temperature setting: this model rejects it ("Extra inputs are not permitted").
        max_tokens=config.MAX_OUTPUT_TOKENS,
    )
    llm = base.bind_tools(AGENT_TOOLS)

    def call_model(state: MessagesState) -> dict:
        # The system prompt is added on every call but never stored in the history.
        reply = llm.invoke([SystemMessage(SYSTEM_PROMPT)] + state["messages"])
        return {"messages": [reply]}

    def route_after_model(state: MessagesState) -> Literal["tools", "__end__"]:
        # If the model requested tools, run them. Otherwise it has answered.
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(AGENT_TOOLS))  # runs each requested tool
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_model, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


def _text(message: BaseMessage) -> str:
    """Return the plain text of a model message.

    Claude can return a list of content blocks; keep only the text blocks.
    """
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "") for block in message.content if isinstance(block, dict)
    ).strip()


def ask(question: str, graph=None) -> str:
    """Answer one plain-English question. Returns text; never raises for step limits."""
    graph = graph or build_graph()
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(question)]},
            {"recursion_limit": config.MAX_AGENT_STEPS},
        )
    except GraphRecursionError:
        return (
            f"Stopped after {config.MAX_AGENT_STEPS} steps without a final answer. "
            "Try a more specific question."
        )
    final = result["messages"][-1]
    return _text(final) if isinstance(final, AIMessage) else str(final.content)
