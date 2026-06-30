from fastapi import APIRouter
from backend.core.memory_service import clear_memory

router = APIRouter()


@router.get("/clear-memory")
def reset_memory():

    clear_memory()

    return {
        "message": "Memory cleared"
    }