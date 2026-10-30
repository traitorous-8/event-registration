from fastapi import FastAPI

from backend.app.api.events import router as events_router
from backend.app.api.tickets import router as tickets_router

app = FastAPI(title="Event Registration API")

app.include_router(events_router)
app.include_router(tickets_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
