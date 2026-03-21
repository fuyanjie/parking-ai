"""POI & Business Density Agent — fetches real POI data from OpenStreetMap."""
import httpx
from .base import BaseAgent
from models.schemas import POI
from config import OSM_OVERPASS_URL, PHOENIX_BBOX

# OSM tag → category mapping
TAG_CATEGORIES = {
    "restaurant": "dining", "fast_food": "dining", "cafe": "dining", "bar": "dining", "pub": "dining",
    "supermarket": "retail", "mall": "retail", "department_store": "retail", "clothes": "retail",
    "convenience": "retail", "marketplace": "retail",
    "hospital": "medical", "clinic": "medical", "doctors": "medical", "pharmacy": "medical", "dentist": "medical",
    "school": "education", "university": "education", "college": "education", "library": "education",
    "cinema": "entertainment", "theatre": "entertainment", "nightclub": "entertainment",
    "stadium": "entertainment", "sports_centre": "entertainment",
    "bank": "office", "office": "office", "coworking_space": "office",
    "hotel": "hospitality", "motel": "hospitality", "hostel": "hospitality",
    "place_of_worship": "community", "community_centre": "community",
}


class POIAgent(BaseAgent):
    name = "POIAgent"
    description = "Fetches points of interest and business density from OpenStreetMap"

    async def execute(self, **kwargs):
        bbox = kwargs.get("bbox", PHOENIX_BBOX)

        # Query major POI categories
        query = f"""[out:json][timeout:60];
(
  nwr["amenity"~"restaurant|fast_food|cafe|bar|hospital|clinic|pharmacy|cinema|theatre|nightclub|bank|school|university"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  nwr["shop"~"supermarket|mall|department_store|clothes|convenience"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  nwr["tourism"~"hotel|motel|hostel"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
  nwr["leisure"~"stadium|sports_centre"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
);
out center 5000;"""

        await self.log("FETCH", "Querying OSM for POIs (restaurants, retail, medical, entertainment, etc.)")

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(OSM_OVERPASS_URL, data={"data": query})
            resp.raise_for_status()
            data = resp.json()

        elements = data.get("elements", [])
        await self.log("PARSE", f"Received {len(elements)} raw POI elements")

        pois = []
        category_counts = {}
        for el in elements:
            lat = el.get("lat") or (el.get("center", {}).get("lat"))
            lon = el.get("lon") or (el.get("center", {}).get("lon"))
            if not lat or not lon:
                continue

            tags = el.get("tags", {})
            # Determine category
            category = "other"
            for tag_key in ("amenity", "shop", "tourism", "leisure"):
                val = tags.get(tag_key, "")
                if val in TAG_CATEGORIES:
                    category = TAG_CATEGORIES[val]
                    break

            pois.append(POI(
                lat=lat, lng=lon,
                name=tags.get("name"),
                category=category,
                osm_id=el.get("id"),
            ))
            category_counts[category] = category_counts.get(category, 0) + 1

        await self.log("CLASSIFY", f"Classified {len(pois)} POIs into {len(category_counts)} categories", {
            "categories": category_counts
        })
        await self.log("STATS", f"Top categories: {', '.join(f'{k}: {v}' for k, v in sorted(category_counts.items(), key=lambda x: -x[1])[:5])}")

        self.results = {
            "pois": pois,
            "total": len(pois),
            "categories": category_counts,
        }
        return self.results
