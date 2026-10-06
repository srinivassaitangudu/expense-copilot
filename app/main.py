from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes import api

app = FastAPI(title="Expense Copilot", version="0.1.0")
app.include_router(api.router, prefix="/api")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
