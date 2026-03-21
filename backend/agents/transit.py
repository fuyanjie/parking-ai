"""Transit & Mobility Agent — fetches real transit data from OpenStreetMap."""
import httpx
from .base import BaseAgent
from models.schemas import TransitStop
from config import OSM_OVERPASS_URL, PHOENIX_BBOX


class TransitAgent(BaseAgent):
    name = "TransitAgent"
    description = "Fetches public transit stops, light rail stations, and park-and-ride from OSM"

    async def execute(self, **kwargs):
        bbox = kwargs.get("bbox", PHOENIX_BBOX)

        # Query bus stops, light rail stations, park & ride
        query = f"""[out:json][timeout:60];
(
  node["highway"="bus_stop"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["railway"="station"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["railway"="tram_stop"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  node["railway"="halt"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  nwr["amenity"="parking"]["park_ride"="yes"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  nwr["park_ride"="yes"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out center 3000;"""

        await self.log("FETCH", "Querying OSM for transit stops (bus, light rail, park-and-ride)...")

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(OSM_OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()

        elements = data.get("elements", [])
        await self.log("PARSE", f"Received {len(elements)} transit-related elements")

        stops = []
        type_counts = {}
        for el in elements:
            lat = el.get("lat") or (el.get("center", {}).get("lat"))
            lon = el.get("lon") or (el.get("center", {}).get("lon"))
            if not lat or not lon:
                continue

            tags = el.get("tags", {})

            # Classify type
            if tags.get("park_ride") == "yes":
                route_type = "park_ride"
            elif tags.get("railway") in ("station", "tram_stop", "halt"):
                route_type = "light_rail"
            else:
                route_type = "bus"

            stops.append(TransitStop(
                lat=lat, lng=lon,
                name=tags.get("name"),
                route_type=route_type,
                osm_id=el.get("id"),
            ))
            type_counts[route_type] = type_counts.get(route_type, 0) + 1

        await self.log("CLASSIFY", f"Found {len(stops)} stops: {type_counts}")

        # Compute transit desert metric
        # Grid the area and find cells with no transit within 0.5mi (~800m)
        grid_coverage = self._compute_coverage(stops, bbox)
        await self.log("ANALYZE", f"Transit coverage: {grid_coverage['covered_pct']:.0f}% of metro area within 800m of a stop")
        await self.log("STATS", f"Transit deserts: {grid_coverage['desert_cells']} zones with no service", {
            "types": type_counts,
            "coverage_pct": grid_coverage["covered_pct"],
            "desert_cells": grid_coverage["desert_cells"],
        })

        self.results = {
            "stops": stops,
            "total": len(stops),
            "types": type_counts,
            "coverage": grid_coverage,
        }
        return self.results

    def _compute_coverage(self, stops, bbox):
        """Simple grid-based transit coverage analysis."""
        step = 0.008  # ~900m grid
        covered = 0
        total = 0
        radius = 0.008  # ~800m

        lat = bbox["south"]
        while lat < bbox["north"]:
            lon = bbox["west"]
            while lon < bbox["east"]:
                total += 1
                for s in stops:
                    if abs(s.lat - lat) < radius and abs(s.lng - lon) < radius:
                        covered += 1
                        break
                lon += step
            lat += step

        return {
            "covered_pct": (covered / total * 100) if total else 0,
            "covered_cells": covered,
            "desert_cells": total - covered,
            "total_cells": total,
        }
