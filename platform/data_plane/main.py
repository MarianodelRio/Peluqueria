# No domain logic — F0 scaffolding only
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
