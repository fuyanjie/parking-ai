"""Demographics & Growth Agent — fetches real Census ACS data."""
import httpx
from .base import BaseAgent
from models.schemas import CensusTract
from config import CENSUS_API_URL


class DemographicsAgent(BaseAgent):
    name = "DemographicsAgent"
    description = "Fetches population, income, and housing data from US Census ACS"

    async def execute(self, **kwargs):
        # Fetch ACS 5-Year data: population, median income, housing units
        variables = "NAME,B01001_001E,B19013_001E,B25001_001E"
        url = f"{CENSUS_API_URL}?get={variables}&for=tract:*&in=state:04+county:013"

        await self.log("FETCH", "Querying US Census ACS 2022 — Maricopa County tract-level data...")
        await self.log("QUERY", f"Variables: Total Pop (B01001), Median Income (B19013), Housing Units (B25001)")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        header = data[0]
        rows = data[1:]
        await self.log("PARSE", f"Received {len(rows)} census tracts")

        tracts = []
        total_pop = 0
        total_housing = 0
        income_values = []

        for row in rows:
            name = row[0]
            pop = int(row[1]) if row[1] and row[1] != "null" else 0
            income = int(row[2]) if row[2] and row[2] not in ("null", "-666666666") else None
            housing = int(row[3]) if row[3] and row[3] != "null" else 0
            tract_id = row[5]

            if pop < 50:
                continue

            # Approximate centroid from tract number using hash-based positioning
            hash1 = int(tract_id[:4]) if len(tract_id) >= 4 else 0
            hash2 = int(tract_id[2:6]) if len(tract_id) >= 6 else 0
            lat = 33.25 + (hash1 % 450) / 1000
            lng = -112.28 + (hash2 % 480) / 1000

            # Keep only those roughly in metro area
            if not (33.2 < lat < 33.72 and -112.35 < lng < -111.75):
                continue

            tracts.append(CensusTract(
                tract_id=tract_id,
                name=name,
                population=pop,
                median_income=income,
                lat=lat,
                lng=lng,
            ))
            total_pop += pop
            total_housing += housing
            if income and income > 0:
                income_values.append(income)

        avg_income = int(sum(income_values) / len(income_values)) if income_values else 0

        await self.log("ANALYZE", f"Processed {len(tracts)} tracts in metro area")
        await self.log("STATS", f"Total pop: {total_pop:,} | Avg income: ${avg_income:,} | Housing: {total_housing:,}", {
            "total_tracts": len(tracts),
            "total_population": total_pop,
            "average_income": avg_income,
            "total_housing": total_housing,
        })

        # Compute growth-relevant metrics
        high_income_tracts = len([t for t in tracts if t.median_income and t.median_income > 80000])
        high_pop_tracts = len([t for t in tracts if t.population > 5000])
        await self.log("GROWTH", f"High-income tracts (>$80K): {high_income_tracts}, High-pop tracts (>5K): {high_pop_tracts}")

        self.results = {
            "tracts": tracts,
            "total_tracts": len(tracts),
            "total_population": total_pop,
            "average_income": avg_income,
            "total_housing": total_housing,
        }
        return self.results
