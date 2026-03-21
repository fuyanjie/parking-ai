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

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import OrchestratorAgent
from config import PipelineConfig, DEFAULT_WEIGHTS
from models.schemas import AgentLogEntry

# Groq LLM client (OpenAI-compatible)
from openai import AsyncOpenAI

groq_client = None
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if GROQ_API_KEY:
    groq_client = AsyncOpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

# Chat conversation history per session (in-memory)
chat_histories: dict[str, list] = {}

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
            "POST /chat": "Chat with AI agent about analysis",
            "GET /chat/status": "Check if LLM is configured",
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


# ========== Chat Endpoint (Groq LLM) ==========

SYSTEM_PROMPT = """You are the AI assistant for the Phoenix Parking Lot Planning system. You help users understand the parking analysis results and recommendations.

You have access to the current analysis context provided below. Answer questions based on this data. Be concise but insightful. When discussing specific sites, reference their ID numbers, scores, and key metrics. If asked about methodology, explain the multi-criteria spatial analysis approach.

You can also:
- Suggest which parameter adjustments would change rankings
- Explain why certain sites scored higher/lower
- Compare sites when asked
- Discuss trade-offs between cost, capacity, and location
- Explain data sources (OpenStreetMap, US Census ACS)

Keep responses under 150 words unless the user asks for detail. Use specific numbers from the context data."""


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    context: Optional[dict] = None  # Current analysis state from frontend


@app.post("/chat")
async def chat(req: ChatRequest):
    """Chat with the AI agent about parking analysis."""
    if not groq_client:
        return JSONResponse(status_code=503, content={
            "error": "Chat unavailable — set GROQ_API_KEY in backend/.env (free at console.groq.com)"
        })

    # Build context string from frontend state
    ctx_parts = []
    if req.context:
        sites = req.context.get("activeSites", [])
        if sites:
            ctx_parts.append("CURRENT RECOMMENDED SITES:")
            for s in sites:
                ctx_parts.append(
                    f"  #{s.get('id')} {s.get('name')} — Score: {s.get('score')}, "
                    f"Capacity: {s.get('capacity')}, Type: {s.get('type')}, "
                    f"Cost: {s.get('cost')}, ROI: {s.get('roi')}, "
                    f"Priority: {s.get('priority')}, "
                    f"Sub-scores: traffic={s.get('subScores',{}).get('traffic')}, "
                    f"gap={s.get('subScores',{}).get('gap')}, "
                    f"growth={s.get('subScores',{}).get('growth')}, "
                    f"poi={s.get('subScores',{}).get('poi')}, "
                    f"transit={s.get('subScores',{}).get('transit')}"
                )

        weights = req.context.get("weights", {})
        if weights:
            ctx_parts.append(f"\nCURRENT SCORING WEIGHTS: {weights}")

        constraints = req.context.get("constraints", {})
        if constraints:
            ctx_parts.append(f"CONSTRAINTS: Budget=${constraints.get('maxBudget',150)}M, Min capacity={constraints.get('minCapacity',100)}")

        whatif = req.context.get("whatIf", {})
        if whatif:
            ctx_parts.append(f"WHAT-IF TOGGLES: Exclude flood={whatif.get('excludeFlood',False)}, Transit priority={whatif.get('transitPriority',False)}, Future areas={whatif.get('includeFuture',False)}")

        live = req.context.get("liveData", {})
        if live:
            ctx_parts.append(f"\nLIVE DATA: OSM parking={live.get('osmParking',0)}, Census tracts={live.get('censusTracts',0)}, Population={live.get('population',0)}")

    context_str = "\n".join(ctx_parts) if ctx_parts else "No analysis has been run yet. The user should click 'Run Agent Pipeline' first."

    # Get or create conversation history
    if req.session_id not in chat_histories:
        chat_histories[req.session_id] = []
    history = chat_histories[req.session_id]

    # Keep history manageable (last 10 exchanges)
    if len(history) > 20:
        history = history[-20:]
        chat_histories[req.session_id] = history

    # Build messages
    messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n--- CURRENT ANALYSIS CONTEXT ---\n{context_str}"},
        *history,
        {"role": "user", "content": req.message},
    ]

    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=500,
        )
        reply = response.choices[0].message.content

        # Save to history
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": reply})

        return {"reply": reply, "model": "llama-3.3-70b-versatile"}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/chat/status")
async def chat_status():
    """Check if chat LLM is configured."""
    return {
        "available": groq_client is not None,
        "provider": "Groq" if groq_client else None,
        "model": "llama-3.3-70b-versatile" if groq_client else None,
        "hint": "Set GROQ_API_KEY in backend/.env (free at console.groq.com)" if not groq_client else None,
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
