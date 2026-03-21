"""
Phoenix Parking AI — FastAPI Backend with WebSocket Agent Pipeline

Usage:
    cd backend
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Then open the frontend and switch to "Live Backend" mode.
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from agents.orchestrator import OrchestratorAgent
from config import PipelineConfig, DEFAULT_WEIGHTS
from models.schemas import AgentLogEntry

app = FastAPI(
    title="Phoenix Parking AI Agent API",
    description="Multi-agent system for data-driven parking lot site selection",
    version="1.0.0",
)

# CORS — allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== REST Endpoints ==========

@app.get("/")
async def root():
    return {
        "service": "Phoenix Parking AI Agent API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Health check",
            "POST /run": "Run pipeline (REST, returns when complete)",
            "WS /ws": "Run pipeline via WebSocket (real-time logs)",
        }
    }


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


class RunRequest(BaseModel):
    weights: dict = DEFAULT_WEIGHTS
    max_budget: float = 150.0
    min_capacity: int = 100
    exclude_flood_zones: bool = False
    transit_priority: bool = False
    include_future: bool = False
    top_k: int = 10


@app.post("/run")
async def run_pipeline(req: RunRequest):
    """Run the full agent pipeline and return results (blocking)."""
    logs = []

    async def collect_log(entry: AgentLogEntry):
        logs.append(entry.model_dump())

    config = PipelineConfig(
        weights=req.weights,
        max_budget=req.max_budget,
        min_capacity=req.min_capacity,
        exclude_flood_zones=req.exclude_flood_zones,
        transit_priority=req.transit_priority,
        include_future=req.include_future,
        top_k=req.top_k,
    )

    orchestrator = OrchestratorAgent(log_callback=collect_log)
    result = await orchestrator.run(config=config)

    return {
        "result": result.model_dump(),
        "logs": logs,
    }


# ========== WebSocket Endpoint ==========

@app.websocket("/ws")
async def websocket_pipeline(websocket: WebSocket):
    """Run agent pipeline with real-time log streaming via WebSocket.

    Client sends: { "action": "run", "config": { ... } }
    Server sends: { "type": "log", "data": { agent, action, message, timestamp } }
                  { "type": "result", "data": { recommended_sites, ... } }
                  { "type": "error", "data": { message } }
    """
    await websocket.accept()

    try:
        while True:
            # Wait for client command
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "run":
                config_data = msg.get("config", {})
                config = PipelineConfig(**config_data)

                # Log callback sends each entry via WebSocket
                async def ws_log(entry: AgentLogEntry):
                    await websocket.send_json({
                        "type": "log",
                        "data": entry.model_dump(),
                    })

                await websocket.send_json({
                    "type": "status",
                    "data": {"status": "running", "message": "Pipeline started..."}
                })

                try:
                    orchestrator = OrchestratorAgent(log_callback=ws_log)
                    result = await orchestrator.run(config=config)

                    # Send final result
                    await websocket.send_json({
                        "type": "result",
                        "data": result.model_dump(),
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": str(e)},
                    })

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Unknown action: {action}"}
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        except:
            pass


# ========== Main ==========

if __name__ == "__main__":
    import uvicorn
    print("\n  Phoenix Parking AI Agent API")
    print("  ============================")
    print("  REST:      http://localhost:8000")
    print("  WebSocket: ws://localhost:8000/ws")
    print("  Docs:      http://localhost:8000/docs")
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000)
