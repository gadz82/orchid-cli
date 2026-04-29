"""Send-a-message pipeline: graph invocation, HITL, streaming.

Extracted from :mod:`chat` so the Typer-facing module stays focused on
command shapes. Three async functions live here:

  - :func:`send_message` — the full path: load history, refresh MCP
    auth, invoke the graph (or stream), persist, auto-title.
  - :func:`invoke_with_approval` — wraps ``graph.ainvoke`` and prompts
    the user when LangGraph emits a tool-approval interrupt.
  - :func:`stream_graph` — drives ``graph.astream`` and renders Markdown
    tokens via :class:`rich.live.Live` for the interactive REPL.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console

from orchid_ai.core.state import OrchidAuthContext

console = Console()


async def send_message(
    ctx,
    chat_id: str,
    message: str,
    auth: OrchidAuthContext,
    *,
    streaming: bool = False,
) -> tuple[str, list[str]]:
    """Send a message through the graph, persist to storage, return ``(response, agents_used)``."""
    history_rows = await ctx.chat_repo.get_messages(chat_id, limit=50)
    history_messages = []
    for row in history_rows:
        if row.role == "user":
            history_messages.append(HumanMessage(content=row.content, id=row.id))
        elif row.role == "assistant":
            history_messages.append(AIMessage(content=row.content, id=row.id))

    mcp_auth_status = await _refresh_mcp_auth_status(ctx, auth)

    has_checkpointer = ctx.runtime.checkpointer is not None
    if has_checkpointer:
        initial_state: dict = {
            "messages": [HumanMessage(content=message)],
            "auth_context": auth,
            "chat_id": chat_id,
        }
    else:
        initial_state = {
            "messages": history_messages + [HumanMessage(content=message)],
            "auth_context": auth,
            "chat_id": chat_id,
        }
    if mcp_auth_status:
        initial_state["mcp_auth_status"] = mcp_auth_status

    graph_config: dict = {"configurable": {"thread_id": chat_id}}

    if streaming:
        response_text, agents_used = await stream_graph(ctx, initial_state, config=graph_config)
    else:
        result = await invoke_with_approval(ctx, initial_state, graph_config)
        response_text = result.get("final_response", "No response generated.")
        agents_used = result.get("active_agents", [])

    await ctx.chat_repo.add_message(chat_id, "user", message)
    await ctx.chat_repo.add_message(chat_id, "assistant", response_text, agents_used=agents_used)

    if not history_rows:
        title = message[:50].strip()
        if len(message) > 50:
            title += "…"
        await ctx.chat_repo.update_title(chat_id, title)

    return response_text, agents_used


async def _refresh_mcp_auth_status(ctx, auth: OrchidAuthContext) -> dict[str, bool]:
    """Look up the per-user OAuth status of every registered MCP server.

    Returns a mapping of server name → ``authorized`` bool. Empty when
    no MCP servers require OAuth.  Unauthorized servers are surfaced via
    the supervisor's ``mcp_auth_status`` so the LLM can prompt the user
    to run ``orchid mcp status`` and authorize through the gateway.
    """
    registry = ctx.runtime.mcp_auth_registry
    store = ctx.mcp_token_store
    if not registry or registry.empty or not store:
        return {}

    mcp_auth_status: dict[str, bool] = {}
    for name in registry.oauth_servers:
        token = await store.get_token(auth.tenant_key, auth.user_id, name)
        mcp_auth_status[name] = token is not None and not token.is_expired

    return mcp_auth_status


async def invoke_with_approval(ctx, initial_state: dict, graph_config: dict) -> dict:
    """Invoke the graph, handling HITL tool approval interrupts.

    When the graph pauses for tool approval (``GraphInterrupt``), the
    user is prompted in the terminal.  On approval the graph resumes;
    on denial the tool is skipped.
    """
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Command
    from rich.prompt import Confirm

    invocation_input: dict | Command = initial_state

    while True:
        try:
            return await ctx.graph.ainvoke(invocation_input, config=graph_config)
        except GraphInterrupt as exc:
            interrupts = exc.args[0] if exc.args else []
            if not interrupts:
                raise

            approved = True
            for interrupt_obj in interrupts:
                val = interrupt_obj.value
                if isinstance(val, dict):
                    tool_name = val.get("tool", "unknown")
                    tool_args = val.get("args", {})
                    agent_name = val.get("agent", "")
                    console.print(
                        f"\n[bold yellow]Tool approval needed[/bold yellow] "
                        f"({agent_name}): [bold]{tool_name}[/bold]({tool_args})"
                    )
                else:
                    console.print(f"\n[bold yellow]Approval needed:[/bold yellow] {val}")

                if not Confirm.ask("[bold]Approve execution?[/bold]", default=True):
                    approved = False

            invocation_input = Command(resume={"approved": approved})


async def stream_graph(
    ctx,
    initial_state: dict,
    *,
    config: dict | None = None,
) -> tuple[str, list[str]]:
    """Stream graph execution with live Markdown rendering.

    The supervisor node can be invoked **multiple times** in one graph
    run — once for the initial routing decision (structured-output JSON),
    once per inter-agent hop in a sequential skill, and finally once for
    the user-facing synthesis.  Each invocation is a distinct LLM call
    with its own ``message.id``.  The LAST coherent supervisor block
    carries the synthesis; earlier blocks are internal plumbing the user
    should never see.

    Strategy
    --------
    * ``stream_mode=["messages", "values"]`` — the ``messages`` leg
      gives token deltas; the ``values`` leg captures the supervisor's
      ``final_response`` when it answers without dispatching agents.
    * Group token deltas by ``message.id``.  When the id changes, the
      accumulated buffer is discarded and the Live block is reset —
      only the LATEST LLM call's output survives to the final render.
    * Classify each new message by its FIRST non-empty chunk: if it
      starts with ``{`` it's routing JSON and the whole message is
      suppressed; if it starts with ``[Supervisor`` it's an internal
      handoff marker and is likewise suppressed.
    * Agent-node tokens are never rendered to the answer area; the
      agent's activation IS shown as a dim status line above the Live
      region so the user still sees which agent(s) handled the turn.
    * The final text feeds a :class:`rich.live.Live` block wrapping a
      :class:`rich.markdown.Markdown` so ``**bold**``, lists, and
      fenced code render correctly as tokens arrive.
    """
    from rich.live import Live
    from rich.markdown import Markdown

    seen_agents: set[str] = set()
    current_msg_id: str | None = None
    current_msg_suppressed: bool = False
    response_parts: list[str] = []
    direct_final: str | None = None

    with Live(
        Markdown(""),
        console=console,
        refresh_per_second=15,
        vertical_overflow="visible",
        transient=False,
    ) as live:
        async for mode, payload in ctx.graph.astream(
            initial_state,
            config=config,
            stream_mode=["messages", "values"],
        ):
            if mode == "values":
                if isinstance(payload, dict):
                    fr = payload.get("final_response")
                    if fr:
                        direct_final = fr
                continue

            msg, metadata = payload
            node = metadata.get("langgraph_node", "")
            content = getattr(msg, "content", "")

            if not content or not isinstance(content, str):
                continue
            if getattr(msg, "tool_calls", None):
                continue

            if node.endswith("_agent"):
                agent_name = node.removesuffix("_agent")
                if agent_name not in seen_agents:
                    seen_agents.add(agent_name)
                    console.print(f"[dim italic]↳ {agent_name} agent working…[/dim italic]")
                continue

            if node != "supervisor":
                continue

            msg_id = getattr(msg, "id", None)
            if msg_id != current_msg_id:
                current_msg_id = msg_id
                response_parts = []
                live.update(Markdown(""))

                first = content.lstrip()
                current_msg_suppressed = (
                    # Routing JSON (structured-output Pydantic).
                    first.startswith("{")
                    # Internal handoff marker like ``[Supervisor → menu]``.
                    or content.startswith("[Supervisor")
                )

            if current_msg_suppressed:
                continue

            response_parts.append(content)
            live.update(Markdown("".join(response_parts)))

        if not response_parts and direct_final:
            response_parts.append(direct_final)
            live.update(Markdown(direct_final))

    full_response = "".join(response_parts).strip() or "No response generated."
    return full_response, sorted(seen_agents)
