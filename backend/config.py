"""Configuration for the Phoenix Parking Agent System."""
from pydantic import BaseModel

# Phoenix metro bounding box
PHOENIX_BBOX = {
    "south": 33.25, "north": 33.70,
    "west": -112.30, "east": -111.80
}

# API endpoints
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CENSUS_API_URL = "https://api.census.gov/data/2022/acs/acs5"

# Scoring defaults
DEFAULT_WEIGHTS = {
    "traffic": 0.25,
    "gap": 0.25,
    "growth": 0.20,
    "poi": 0.15,
    "transit": 0.15,
}

# Grid resolution for spatial analysis (degrees)
GRID_RESOLUTION = 0.01  # ~1.1km

class PipelineConfig(BaseModel):
    weights: dict = DEFAULT_WEIGHTS
    max_budget: float = 150.0  # millions
    min_capacity: int = 100
    exclude_flood_zones: bool = False
    transit_priority: bool = False
    include_future: bool = False
    top_k: int = 10
