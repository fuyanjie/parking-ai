"""Traffic Data Agent — derives traffic density from OSM road network data."""
import httpx
from .base import BaseAgent
from config import OSM_OVERPASS_URL, PHOENIX_BBOX


class TrafficAgent(BaseAgent):
    name = "TrafficAgent"
    description = "Analyzes road network density as a proxy for traffic volume from OSM"

    async def execute(self, **kwargs):
        bbox = kwargs.get("bbox", PHOENIX_BBOX)

        # Query major roads (motorway, trunk, primary, secondary) for traffic proxy
        query = f"""[out:json][timeout:60];
(
  way["highway"~"motorway|trunk|primary|secondary"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out body 3000;"""

        await self.log("FETCH", "Querying OSM for major road network (motorway, trunk, primary, secondary)...")

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(OSM_OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()

        elements = data.get("elements", [])
        await self.log("PARSE", f"Received {len(elements)} road segments")

        # Build a road density grid
        road_density = {}
        road_types = {}
        step = 0.01  # ~1.1km grid

        for el in elements:
            tags = el.get("tags", {})
            hwy = tags.get("highway", "secondary")
            road_types[hwy] = road_types.get(hwy, 0) + 1

            # Use node references to estimate road location
            # For ways, use center of node list if available
            nodes = el.get("nodes", [])
            if not nodes:
                continue
            # We don't have node coords in body output, so use tags/bounds heuristic
            # For now, use a grid-based count as proxy

        # Since we can't get node coords from 'out body', use a simpler approach:
        # Query intersection density instead
        query2 = f"""[out:json][timeout:60];
(
  node["highway"="traffic_signals"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["highway"="motorway_junction"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out 3000;"""

        await self.log("FETCH", "Querying traffic signals and junctions as density proxy...")

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(OSM_OVERPASS_URL, data={"data": query2})
            resp.raise_for_status()
            data2 = resp.json()

        signals = data2.get("elements", [])
        await self.log("PARSE", f"Found {len(signals)} traffic signals/junctions")

        # Grid-based density computation
        grid = {}
        for el in signals:
            lat, lon = el.get("lat", 0), el.get("lon", 0)
            if not lat or not lon:
                continue
            gkey = (round(lat / step) * step, round(lon / step) * step)
            grid[gkey] = grid.get(gkey, 0) + 1

        max_density = max(grid.values()) if grid else 1

        # Convert to traffic_zones format
        traffic_zones = []
        for (lat, lon), count in grid.items():
            intensity = count / max_density
            traffic_zones.append({
                "lat": round(lat, 4),
                "lng": round(lon, 4),
                "density": count,
                "intensity": round(intensity, 3),
            })

        traffic_zones.sort(key=lambda x: -x["density"])
        top_zones = traffic_zones[:15]

        await self.log("ANALYZE", f"Computed traffic density for {len(grid)} grid cells")
        await self.log("STATS", f"Road segments: {len(elements)}, Signals: {len(signals)}, Peak zones: {len(top_zones)}", {
            "road_segments": len(elements),
            "traffic_signals": len(signals),
            "grid_cells": len(grid),
            "road_types": road_types,
        })

        self.results = {
            "traffic_zones": traffic_zones,
            "top_zones": top_zones,
            "total_signals": len(signals),
            "total_roads": len(elements),
            "road_types": road_types,
            "grid": grid,
        }
        return self.results
