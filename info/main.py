from fastapi import FastAPI
from backend.api.chat import router as chat_router
from backend.api.memory import router as memory_router
from backend.api.admin import router as admin_router
from backend.api.upload import router as upload_router

app = FastAPI(title="Athena")

app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(admin_router)
app.include_router(upload_router)

@app.get("/")
def home():
    return {
        "message": "Athena is running"
    }