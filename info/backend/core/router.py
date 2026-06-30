import json


def parse_tool_response(response):

    try:

        data = json.loads(
            response
        )

        return (
            data.get("tool"),
            data.get("input")
        )

    except Exception:

        return (
            None,
            None
        )