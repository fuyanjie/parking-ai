"""Parking Inventory Agent — fetches real parking data from OpenStreetMap."""
import httpx
from .base import BaseAgent
from models.schemas import ParkingFacility
from config import OSM_OVERPASS_URL, PHOENIX_BBOX


class ParkingAgent(BaseAgent):
    name = "ParkingAgent"
    description = "Fetches existing parking facilities from OpenStreetMap Overpass API"

    async def execute(self, **kwargs):
        bbox = kwargs.get("bbox", PHOENIX_BBOX)
        query = f"""[out:json][timeout:60];
(
  nwr["amenity"="parking"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out center 2000;"""

        await self.log("FETCH", f"Querying OSM Overpass API for parking in Phoenix metro...")
        await self.log("QUERY", f"Bbox: {bbox['south']},{bbox['west']} to {bbox['north']},{bbox['east']}")

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                OSM_OVERPASS_URL,
                data={"data": query},
            )
            resp.raise_for_status()
            data = resp.json()

        elements = data.get("elements", [])
        await self.log("PARSE", f"Received {len(elements)} raw elements from OSM")

        facilities = []
        for el in elements:
            lat = el.get("lat") or (el.get("center", {}).get("lat"))
            lon = el.get("lon") or (el.get("center", {}).get("lon"))
            if not lat or not lon:
                continue

            tags = el.get("tags", {})
            capacity = None
            if "capacity" in tags:
                try:
                    capacity = int(tags["capacity"])
                except (ValueError, TypeError):
                    pass

            ptype = tags.get("parking", "surface")
            if ptype in ("multi-storey", "multi_storey"):
                ptype = "garage"
            elif ptype in ("underground",):
                ptype = "underground"
            else:
                ptype = "surface"

            facilities.append(ParkingFacility(
                lat=lat,
                lng=lon,
                name=tags.get("name"),
                capacity=capacity,
                parking_type=ptype,
                osm_id=el.get("id"),
            ))

        # Summary stats
        with_capacity = [f for f in facilities if f.capacity]
        total_known = sum(f.capacity for f in with_capacity)
        types = {}
        for f in facilities:
            types[f.parking_type] = types.get(f.parking_type, 0) + 1

        await self.log("ANALYZE", f"Parsed {len(facilities)} valid facilities")
        await self.log("STATS", f"Capacity known: {len(with_capacity)} lots, {total_known:,} spaces total", {
            "total": len(facilities),
            "with_capacity": len(with_capacity),
            "total_known_spaces": total_known,
            "types": types,
        })

        self.results = {
            "facilities": facilities,
            "total": len(facilities),
            "total_known_spaces": total_known,
            "types": types,
        }
        return self.results
