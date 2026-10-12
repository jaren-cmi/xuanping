from typing import Any


class TrendsCollector:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from pytrends.request import TrendReq

            client = TrendReq(hl="en-US", tz=360)
        self.client = client

    def collect(self, keyword: str, timeframe: str = "today 12-m", geo: str = "US") -> dict[str, Any]:
        self.client.build_payload([keyword], timeframe=timeframe, geo=geo)
        interest = self.client.interest_over_time()
        if interest.empty or keyword not in interest:
            return {"keyword": keyword, "slope": 0.0, "seasonality": 0.0, "regions": {}}
        values = [float(value) for value in interest[keyword].tolist()]
        n = len(values)
        mean_x = (n - 1) / 2
        mean_y = sum(values) / n
        denominator = sum((index - mean_x) ** 2 for index in range(n))
        slope = (
            sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
            / denominator
            if denominator
            else 0.0
        )
        seasonality = (max(values) - min(values)) / mean_y if mean_y else 0.0
        regions_frame = self.client.interest_by_region(resolution="REGION")
        regions = (
            {str(index): float(row[keyword]) for index, row in regions_frame.iterrows()}
            if not regions_frame.empty and keyword in regions_frame
            else {}
        )
        return {"keyword": keyword, "slope": slope, "seasonality": seasonality, "regions": regions}
