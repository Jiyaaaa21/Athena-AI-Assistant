from fastapi import APIRouter

from backend.agents.agent import (
    process_query
)

from backend.api.response import (
    success_response,
    error_response
)

router = APIRouter()


@router.get("/chat")
def chat(question: str):

    try:

        answer = process_query(
            question
        )

        return success_response(
            {
                "question": question,
                "answer": answer
            }
        )

    except Exception as e:

        return error_response(
            str(e)
        )