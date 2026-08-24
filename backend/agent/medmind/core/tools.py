from __future__ import annotations


READ_TOOL_NAMES = {
    "get_provider_info",
    "list_specialties",
    "list_doctors",
    "list_services",
    "list_available_slots",
}


def select_read_tools(
    tools,
):

    selected = [
        tool
        for tool in tools
        if tool.name
        in READ_TOOL_NAMES
    ]

    loaded_names = {
        tool.name
        for tool in selected
    }

    missing = (
        READ_TOOL_NAMES
        - loaded_names
    )

    if missing:

        raise RuntimeError(
            "Missing MCP tools: "
            + ", ".join(
                sorted(
                    missing
                )
            )
        )

    return selected