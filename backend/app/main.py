from fastapi import FastAPI

app = FastAPI(title="Платформа охраны труда", version="0.1.0")


@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}
