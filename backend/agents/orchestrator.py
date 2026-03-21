"""Orchestrator Agent — coordinates the full agent pipeline."""
import asyncio
import time
from typing import Callable, Optional

from .base import BaseAgent
from .traffic import TrafficAgent
from .poi import POIAgent
from .parking import ParkingAgent
from .transit import TransitAgent
from .demographics import DemographicsAgent
from .analyzer import SpatialAnalyzer
from .recommender import RecommendationAgent
from models.schemas import PipelineResult
from config import PipelineConfig, DEFAULT_WEIGHTS


class OrchestratorAgent(BaseAgent):
    name = "Orchestrator"
    description = "Coordinates the full multi-agent pipeline for parking lot analysis"

    def __init__(self, log_callback: Optional[Callable] = None):
        super().__init__(log_callback)
        self.traffic_agent = TrafficAgent(log_callback)
        self.poi_agent = POIAgent(log_callback)
        self.parking_agent = ParkingAgent(log_callback)
        self.transit_agent = TransitAgent(log_callback)
        self.demographics_agent = DemographicsAgent(log_callback)
        self.analyzer = SpatialAnalyzer(log_callback)
        self.recommender = RecommendationAgent(log_callback)

    async def execute(self, **kwargs):
        config = kwargs.get("config", PipelineConfig())
        pipeline_start = time.time()

        await self.log("INIT", f"Starting pipeline with weights: {config.weights}")
        await self.log("INIT", f"Budget: ${config.max_budget}M | Min capacity: {config.min_capacity}")

        # ========== PHASE 1: Parallel Data Collection ==========
        await self.log("PHASE", "Phase 1: Parallel data collection from 5 agents...")

        # Run data collection agents in parallel
        results = await asyncio.gather(
            self.traffic_agent.run(),
            self.poi_agent.run(),
            self.parking_agent.run(),
            self.transit_agent.run(),
            self.demographics_agent.run(),
            return_exceptions=True,
        )

        # Unpack results (handle any failures gracefully)
        traffic_data = results[0] if not isinstance(results[0], Exception) else {"traffic_zones": [], "grid": {}}
        poi_data = results[1] if not isinstance(results[1], Exception) else {"pois": []}
        parking_data = results[2] if not isinstance(results[2], Exception) else {"facilities": []}
        transit_data = results[3] if not isinstance(results[3], Exception) else {"stops": []}
        demographics_data = results[4] if not isinstance(results[4], Exception) else {"tracts": []}

        # Log any failures
        for i, name in enumerate(["Traffic", "POI", "Parking", "Transit", "Demographics"]):
            if isinstance(results[i], Exception):
                await self.log("WARN", f"{name} agent failed: {str(results[i])}")

        await self.log("PHASE", f"Phase 1 complete — collected {parking_data.get('total', 0)} parking, "
                       f"{poi_data.get('total', 0)} POIs, {transit_data.get('total', 0)} transit, "
                       f"{demographics_data.get('total_tracts', 0)} tracts")

        # ========== PHASE 2: Spatial Analysis ==========
        await self.log("PHASE", "Phase 2: Spatial analysis and multi-criteria scoring...")

        analysis = await self.analyzer.run(
            parking=parking_data,
            pois=poi_data,
            transit=transit_data,
            demographics=demographics_data,
            traffic=traffic_data,
            weights=config.weights,
        )

        # ========== PHASE 3: Recommendation Generation ==========
        await self.log("PHASE", "Phase 3: Generating optimal site recommendations...")

        recommendation = await self.recommender.run(
            analysis=analysis,
            config=config.model_dump(),
            parking=parking_data,
            pois=poi_data,
            transit=transit_data,
        )

        pipeline_end = time.time()
        duration = round(pipeline_end - pipeline_start, 2)

        sites = recommendation.get("recommended_sites", [])
        total_cap = sum(s.capacity for s in sites)
        total_cost = sum(s.cost_num for s in sites)

        await self.log("DONE", f"Pipeline complete in {duration}s — {len(sites)} sites, "
                       f"{total_cap:,} spaces, ${total_cost:.1f}M total investment")

        result = PipelineResult(
            recommended_sites=sites,
            total_parking_fetched=parking_data.get("total", 0),
            total_pois_fetched=poi_data.get("total", 0),
            total_transit_stops=transit_data.get("total", 0),
            total_census_tracts=demographics_data.get("total_tracts", 0),
            total_population=demographics_data.get("total_population", 0),
            grid_cells_analyzed=analysis.get("active_cells", 0),
            pipeline_duration_sec=duration,
        )

        self.results = result
        return result
