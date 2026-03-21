"""Pydantic models for the parking agent system."""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentLogEntry(BaseModel):
    agent: str
    action: str
    message: str
    data: Optional[dict] = None
    timestamp: Optional[str] = None


class ParkingFacility(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    capacity: Optional[int] = None
    parking_type: Optional[str] = None  # surface, garage, underground
    osm_id: Optional[int] = None


class CensusTract(BaseModel):
    tract_id: str
    name: str
    population: int
    median_income: Optional[int] = None
    lat: float
    lng: float


class POI(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    category: str  # retail, dining, office, medical, entertainment, etc.
    osm_id: Optional[int] = None


class TransitStop(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None
    route_type: str  # bus, light_rail, park_ride
    osm_id: Optional[int] = None


class GridCell(BaseModel):
    lat: float
    lng: float
    traffic_score: float = 0.0
    gap_score: float = 0.0
    growth_score: float = 0.0
    poi_score: float = 0.0
    transit_score: float = 0.0
    composite_score: float = 0.0
    parking_count: int = 0
    poi_count: int = 0
    transit_count: int = 0
    population: int = 0
    is_flood_zone: bool = False


class RecommendedSite(BaseModel):
    id: int
    name: str
    lat: float
    lng: float
    capacity: int
    parking_type: str
    priority: str  # high, medium, low
    score: float
    sub_scores: dict
    cost: str
    cost_num: float
    roi: str
    roi_num: float
    reason: str
    nearby_pois: int = 0
    nearby_transit: int = 0
    nearby_parking: int = 0
    population_served: int = 0


class PipelineResult(BaseModel):
    recommended_sites: list[RecommendedSite]
    total_parking_fetched: int
    total_pois_fetched: int
    total_transit_stops: int
    total_census_tracts: int
    total_population: int
    grid_cells_analyzed: int
    pipeline_duration_sec: float
