"""Recommendation Agent — selects optimal sites and determines capacity."""
import math
from .base import BaseAgent
from models.schemas import RecommendedSite, GridCell
from config import PHOENIX_BBOX


# Known Phoenix area names by approximate location
AREA_NAMES = [
    (33.448, -112.074, "Downtown Core"),
    (33.509, -112.074, "Midtown Central Ave"),
    (33.431, -111.943, "Tempe Town Lake"),
    (33.494, -111.926, "Scottsdale Old Town"),
    (33.678, -111.998, "Desert Ridge"),
    (33.465, -112.153, "West Phoenix"),
    (33.415, -111.832, "Mesa Downtown"),
    (33.306, -111.841, "Chandler Innovation"),
    (33.535, -112.074, "Uptown/North Central"),
    (33.393, -112.074, "South Mountain"),
    (33.580, -111.926, "North Scottsdale"),
    (33.350, -111.940, "Chandler/Gilbert"),
    (33.440, -112.020, "Airport Area"),
    (33.490, -112.005, "Arcadia"),
    (33.520, -111.960, "Paradise Valley"),
]

# Approximate flood zone areas in Phoenix
FLOOD_ZONES = [
    (33.43, -111.94, 0.02),  # Tempe Town Lake area
    (33.35, -112.08, 0.02),  # South Mountain / Salt River
    (33.39, -112.15, 0.02),  # Laveen
]

COST_PER_SPACE = {
    "surface": 15000,
    "garage": 25000,
    "mixed": 20000,
}


class RecommendationAgent(BaseAgent):
    name = "RecommendAgent"
    description = "Generates final parking lot recommendations with capacity and ROI"

    async def execute(self, **kwargs):
        analysis = kwargs.get("analysis", {})
        config = kwargs.get("config", {})
        parking_data = kwargs.get("parking", {})
        poi_data = kwargs.get("pois", {})
        transit_data = kwargs.get("transit", {})

        top_cells = analysis.get("top_cells", [])
        max_budget = config.get("max_budget", 150.0)
        min_capacity = config.get("min_capacity", 100)
        exclude_flood = config.get("exclude_flood_zones", False)
        top_k = config.get("top_k", 10)

        await self.log("SELECT", f"Selecting top sites from {len(top_cells)} candidate cells...")

        # Cluster nearby top cells to avoid redundant recommendations
        selected = []
        min_dist = 0.015  # ~1.7km minimum between sites

        for cell in top_cells:
            # Check distance from already selected
            too_close = False
            for s in selected:
                if abs(cell.lat - s.lat) < min_dist and abs(cell.lng - s.lng) < min_dist:
                    too_close = True
                    break
            if too_close:
                continue

            # Check flood zone
            in_flood = False
            for fz_lat, fz_lon, fz_r in FLOOD_ZONES:
                if abs(cell.lat - fz_lat) < fz_r and abs(cell.lng - fz_lon) < fz_r:
                    in_flood = True
                    break
            if exclude_flood and in_flood:
                continue

            selected.append(cell)
            if len(selected) >= top_k * 2:
                break

        await self.log("CLUSTER", f"Filtered to {len(selected)} distinct locations (min {min_dist*111:.1f}km apart)")

        # Determine capacity and type for each site
        sites = []
        cumulative_cost = 0
        facilities = parking_data.get("facilities", [])
        pois = poi_data.get("pois", [])
        stops = transit_data.get("stops", [])

        for i, cell in enumerate(selected):
            if len(sites) >= top_k:
                break

            # Capacity: based on POI density and population
            base_cap = max(min_capacity, int(cell.poi_count * 8 + cell.population * 0.02))
            capacity = min(1200, max(min_capacity, round(base_cap / 50) * 50))

            # Type based on score and density
            if cell.composite_score > 60 and cell.poi_count > 10:
                ptype = "Multi-Story Garage"
                cost_key = "garage"
            elif cell.composite_score > 40:
                ptype = "Mixed-Use Structure"
                cost_key = "mixed"
            else:
                ptype = "Smart Surface Lot"
                cost_key = "surface"

            cost_num = round(capacity * COST_PER_SPACE[cost_key] / 1_000_000, 1)

            # Check budget
            if cumulative_cost + cost_num > max_budget:
                continue
            cumulative_cost += cost_num

            # ROI estimate based on demand-supply gap
            base_roi = 12 + cell.gap_score * 0.1 + cell.poi_score * 0.03
            roi_num = round(min(25, base_roi), 1)

            # Priority
            if cell.composite_score >= 60:
                priority = "high"
            elif cell.composite_score >= 35:
                priority = "medium"
            else:
                priority = "low"

            # Name from nearest known area
            name = self._get_area_name(cell.lat, cell.lng)

            # Count nearby features
            search_r = 0.015
            nearby_pois = sum(1 for p in pois if abs(p.lat - cell.lat) < search_r and abs(p.lng - cell.lng) < search_r)
            nearby_transit = sum(1 for s in stops if abs(s.lat - cell.lat) < search_r and abs(s.lng - cell.lng) < search_r)
            nearby_parking = sum(1 for f in facilities if abs(f.lat - cell.lat) < search_r and abs(f.lng - cell.lng) < search_r)

            # Reason
            factors = []
            if cell.traffic_score > 50: factors.append(f"high traffic density ({cell.traffic_score:.0f}/100)")
            if cell.gap_score > 50: factors.append(f"parking deficit ({cell.gap_score:.0f}/100)")
            if cell.poi_score > 50: factors.append(f"dense POI cluster ({nearby_pois} nearby)")
            if cell.transit_score > 30: factors.append(f"transit access ({nearby_transit} stops nearby)")
            if cell.growth_score > 50: factors.append(f"high population density ({cell.population:,})")
            reason = "; ".join(factors[:3]) if factors else "Composite scoring above threshold"

            site = RecommendedSite(
                id=len(sites) + 1,
                name=name,
                lat=round(cell.lat, 4),
                lng=round(cell.lng, 4),
                capacity=capacity,
                parking_type=ptype,
                priority=priority,
                score=round(cell.composite_score, 1),
                sub_scores={
                    "traffic": round(cell.traffic_score, 1),
                    "gap": round(cell.gap_score, 1),
                    "growth": round(cell.growth_score, 1),
                    "poi": round(cell.poi_score, 1),
                    "transit": round(cell.transit_score, 1),
                },
                cost=f"${cost_num}M",
                cost_num=cost_num,
                roi=f"{roi_num}%",
                roi_num=roi_num,
                reason=reason,
                nearby_pois=nearby_pois,
                nearby_transit=nearby_transit,
                nearby_parking=nearby_parking,
                population_served=cell.population,
            )
            sites.append(site)

        total_cap = sum(s.capacity for s in sites)
        await self.log("CAPACITY", f"Optimized capacities: {[s.capacity for s in sites]} = {total_cap:,} total spaces")
        await self.log("COST", f"Total investment: ${cumulative_cost:.1f}M within ${max_budget}M budget")
        await self.log("ROI", f"Projected ROI range: {min(s.roi_num for s in sites):.1f}% - {max(s.roi_num for s in sites):.1f}%")
        await self.log("REPORT", f"Final: {len(sites)} recommended sites ready")

        self.results = {"recommended_sites": sites}
        return self.results

    def _get_area_name(self, lat, lng):
        """Find the nearest known Phoenix area name."""
        best = None
        best_dist = float("inf")
        for alat, alng, aname in AREA_NAMES:
            dist = math.sqrt((lat - alat) ** 2 + (lng - alng) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = aname
        return best or f"Phoenix ({lat:.3f}, {lng:.3f})"
