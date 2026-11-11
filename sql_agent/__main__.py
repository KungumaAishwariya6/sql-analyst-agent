"""Command-line chat: `python -m sql_agent`.

Type a question, read the answer, and enter a blank line (or `exit`) to quit.
"""

from sql_agent.agent import ask, build_graph


def main() -> None:
    print("SQL analyst agent. Ask a question about the database (blank line to quit).")
    graph = build_graph()  # build once, reuse for every question
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question in ("", "exit", "quit"):
            break
        print(ask(question, graph))


if __name__ == "__main__":
    main()
