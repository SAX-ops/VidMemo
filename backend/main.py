# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import download, summary

app = FastAPI(title="VidSumAI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(download.router, prefix="/api")
app.include_router(summary.router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
