import time
from typing import Any


class TrendsCollector:
    def __init__(
        self, client: Any | None = None, *, sleep: Any = time.sleep, request_delay: float = 1.0
    ) -> None:
        self.client = client
        self.sleep = sleep
        self.request_delay = request_delay

    def collect(self, keyword: str, timeframe: str = "today 12-m", geo: str = "US") -> dict[str, Any]:
        return self.collect_many([keyword], timeframe=timeframe, geo=geo).get(
            keyword, {"keyword": keyword, "available": False}
        )

    def collect_many(
        self, keywords: list[str], timeframe: str = "today 12-m", geo: str = "US"
    ) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        unique = list(dict.fromkeys(keyword for keyword in keywords if keyword))
        if not unique:
            return results
        if self.client is None:
            from pytrends.request import TrendReq

            self.client = TrendReq(hl="en-US", tz=360)
        for start in range(0, len(unique), 5):
            batch = unique[start : start + 5]
            if start:
                self.sleep(self.request_delay)
            try:
                self.client.build_payload(batch, timeframe=timeframe, geo=geo)
                interest = self.client.interest_over_time()
                regions_frame = self.client.interest_by_region(resolution="REGION")
            except Exception as error:
                if "429" in str(error) or "too many requests" in str(error).lower():
                    self.sleep(30)
                    try:
                        self.client.build_payload(batch, timeframe=timeframe, geo=geo)
                        interest = self.client.interest_over_time()
                        regions_frame = self.client.interest_by_region(resolution="REGION")
                    except Exception:
                        for keyword in batch:
                            results[keyword] = {"keyword": keyword, "available": False}
                        continue
                else:
                    for keyword in batch:
                        results[keyword] = {"keyword": keyword, "available": False}
                    continue
            for keyword in batch:
                if interest.empty or keyword not in interest:
                    results[keyword] = {
                        "keyword": keyword, "available": False, "slope": 0.0,
                        "seasonality": 0.0, "regions": {},
                    }
                    continue
                values = [float(value) for value in interest[keyword].tolist()]
                results[keyword] = self._summarize(keyword, values, interest, regions_frame)
        return results

    @staticmethod
    def _summarize(
        keyword: str, values: list[float], interest: Any, regions_frame: Any
    ) -> dict[str, Any]:
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
        regions = (
            {str(index): float(row[keyword]) for index, row in regions_frame.iterrows()}
            if not regions_frame.empty and keyword in regions_frame
            else {}
        )
        return {
            "keyword": keyword, "available": True, "slope": slope,
            "seasonality": seasonality, "regions": regions,
        }
