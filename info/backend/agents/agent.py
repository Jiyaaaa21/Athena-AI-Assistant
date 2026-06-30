from backend.tools.registry import TOOLS

from backend.core.llm import (
    ask_llm_raw,
    ask_llm_with_memory
)

from backend.core.memory_service import (
    add_message
)

from backend.core.logger import (
    agent_logger,
    tool_logger,
    error_logger
)

from backend.prompts.tool_router_prompt import (
    TOOL_ROUTER_PROMPT
)

from backend.tools.direct_return import (
    DIRECT_RETURN_TOOLS,
    DIRECT_RETURN_RESULTS
)


def run_tool(tool_name, tool_input):

    try:

        tool = TOOLS.get(tool_name)

        if not tool:

            error_logger.error(
                f"Unknown tool requested: {tool_name}"
            )

            return "Tool not found"

        return tool.run(tool_input)

    except Exception as e:

        error_logger.error(
            f"{tool_name}: {str(e)}"
        )

        return (
            "An error occurred while using the tool."
        )


def should_return_directly(
    tool_name,
    tool_input,
    tool_result
):

    if tool_name in DIRECT_RETURN_TOOLS:
        return True

    if (
        tool_name == "notes"
        and tool_input == "list"
    ):
        return True

    if (
        tool_name == "reminder"
        and tool_input == "list"
    ):
        return True

    if tool_result in DIRECT_RETURN_RESULTS:
        return True

    return False


def process_query(user_query: str):

    agent_logger.info(
        f"USER: {user_query}"
    )

    tool_selection_prompt = (
        TOOL_ROUTER_PROMPT
        + f"\n\nUser Query: {user_query}"
    )

    response = ask_llm_raw(
        tool_selection_prompt
    )

    print(
        "LLM Decision:",
        response
    )

    if response.startswith("TOOL:"):

        tool_part = (
            response.replace(
                "TOOL:",
                ""
            ).strip()
        )

        tool_name, tool_input = (
            tool_part.split(
                "|",
                1
            )
        )

        tool_name = (
            tool_name.strip()
        )

        tool_input = (
            tool_input.strip()
        )

        tool_result = run_tool(
            tool_name,
            tool_input
        )

        tool_logger.info(
            f"{tool_name} | {tool_input}"
        )

        if should_return_directly(
            tool_name,
            tool_input,
            tool_result
        ):

            add_message(
                "user",
                user_query
            )

            add_message(
                "assistant",
                tool_result
            )

            return tool_result

        final_prompt = f"""
You are Athena.

User Question:
{user_query}

Tool Used:
{tool_name}

Tool Result:
{tool_result}

Generate a natural, clear and helpful response.
"""

        answer = ask_llm_raw(
            final_prompt
        )

        add_message(
            "user",
            user_query
        )

        add_message(
            "assistant",
            answer
        )

        return answer

    return ask_llm_with_memory(
        user_query
    )