"""Spatial Analysis Agent — multi-criteria scoring on a unified grid."""
import math
from .base import BaseAgent
from models.schemas import GridCell
from config import PHOENIX_BBOX, GRID_RESOLUTION


class SpatialAnalyzer(BaseAgent):
    name = "SpatialAnalyzer"
    description = "Performs multi-criteria spatial analysis on collected data"

    async def execute(self, **kwargs):
        parking_data = kwargs.get("parking", {})
        poi_data = kwargs.get("pois", {})
        transit_data = kwargs.get("transit", {})
        demographics_data = kwargs.get("demographics", {})
        traffic_data = kwargs.get("traffic", {})
        weights = kwargs.get("weights", {})

        bbox = PHOENIX_BBOX
        step = GRID_RESOLUTION

        await self.log("MERGE", "Building unified spatial grid from 5 data layers...")

        # Build grid
        grid_cells = {}
        lat = bbox["south"]
        while lat < bbox["north"]:
            lon = bbox["west"]
            while lon < bbox["east"]:
                key = (round(lat, 3), round(lon, 3))
                grid_cells[key] = GridCell(lat=lat, lng=lon)
                lon += step
            lat += step

        await self.log("GRID", f"Created {len(grid_cells)} grid cells at {step}° resolution (~{step*111:.1f}km)")

        # 1. Populate parking counts (inverse = gap)
        facilities = parking_data.get("facilities", [])
        for f in facilities:
            key = (round(f.lat / step) * step, round(f.lng / step) * step)
            key = (round(key[0], 3), round(key[1], 3))
            if key in grid_cells:
                grid_cells[key].parking_count += 1

        # 2. Populate POI counts
        pois = poi_data.get("pois", [])
        for p in pois:
            key = (round(p.lat / step) * step, round(p.lng / step) * step)
            key = (round(key[0], 3), round(key[1], 3))
            if key in grid_cells:
                grid_cells[key].poi_count += 1

        # 3. Populate transit counts
        stops = transit_data.get("stops", [])
        for s in stops:
            key = (round(s.lat / step) * step, round(s.lng / step) * step)
            key = (round(key[0], 3), round(key[1], 3))
            if key in grid_cells:
                grid_cells[key].transit_count += 1

        # 4. Populate population
        tracts = demographics_data.get("tracts", [])
        for t in tracts:
            key = (round(t.lat / step) * step, round(t.lng / step) * step)
            key = (round(key[0], 3), round(key[1], 3))
            if key in grid_cells:
                grid_cells[key].population += t.population

        await self.log("POPULATE", f"Data distributed: {len(facilities)} parking, {len(pois)} POIs, {len(stops)} transit, {len(tracts)} tracts")

        # 5. Compute sub-scores (0-100)
        cells = list(grid_cells.values())
        active = [c for c in cells if c.poi_count > 0 or c.parking_count > 0 or c.transit_count > 0 or c.population > 0]

        if not active:
            await self.log("WARN", "No active cells found — returning empty grid")
            self.results = {"grid_cells": [], "active_cells": 0}
            return self.results

        max_parking = max(c.parking_count for c in active) or 1
        max_poi = max(c.poi_count for c in active) or 1
        max_transit = max(c.transit_count for c in active) or 1
        max_pop = max(c.population for c in active) or 1

        # Traffic density from traffic agent
        traffic_grid = traffic_data.get("grid", {})
        max_traffic = max(traffic_grid.values()) if traffic_grid else 1

        for cell in active:
            # Traffic score: based on signal/junction density
            t_key = (round(cell.lat / 0.01) * 0.01, round(cell.lng / 0.01) * 0.01)
            traffic_density = traffic_grid.get(t_key, 0)
            cell.traffic_score = min(100, (traffic_density / max_traffic) * 100)

            # Gap score: HIGH demand (POI+pop) but LOW existing parking = HIGH gap
            demand = (cell.poi_count / max_poi + cell.population / max_pop) / 2
            supply = cell.parking_count / max_parking
            cell.gap_score = min(100, max(0, (demand - supply * 0.5) * 100))

            # Growth score: population-weighted
            cell.growth_score = min(100, (cell.population / max_pop) * 100)

            # POI score
            cell.poi_score = min(100, (cell.poi_count / max_poi) * 100)

            # Transit score
            cell.transit_score = min(100, (cell.transit_count / max_transit) * 100)

            # Composite
            w = weights
            cell.composite_score = (
                cell.traffic_score * w.get("traffic", 0.25) +
                cell.gap_score * w.get("gap", 0.25) +
                cell.growth_score * w.get("growth", 0.20) +
                cell.poi_score * w.get("poi", 0.15) +
                cell.transit_score * w.get("transit", 0.15)
            )

        # Sort by composite score
        active.sort(key=lambda c: -c.composite_score)
        top_cells = active[:50]

        await self.log("SCORE", f"Scored {len(active)} active cells using weighted model")
        await self.log("RANK", f"Top cell: ({top_cells[0].lat:.3f}, {top_cells[0].lng:.3f}) score={top_cells[0].composite_score:.1f}")
        await self.log("STATS", f"Top 10 composite scores: {[round(c.composite_score, 1) for c in top_cells[:10]]}")

        self.results = {
            "grid_cells": active,
            "top_cells": top_cells,
            "active_cells": len(active),
            "total_cells": len(grid_cells),
        }
        return self.results
