def success_response(data):

    return {
        "success": True,
        "data": data,
        "error": None
    }


def error_response(message):

    return {
        "success": False,
        "data": None,
        "error": message
    }