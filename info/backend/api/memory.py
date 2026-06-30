from fastapi import APIRouter
from backend.core.memory import conversation_history

router = APIRouter()


@router.get("/memory")
def memory():

    return {
        "messages": conversation_history
    }