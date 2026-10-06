from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routes import api

app = FastAPI(title="Expense Copilot", version="0.1.0")
app.include_router(api.router, prefix="/api")

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}

@app.get("/sample-transactions.csv", include_in_schema=False)
def sample_transactions():
    return FileResponse("examples/transactions.csv", media_type="text/csv", filename="transactions.csv")

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
