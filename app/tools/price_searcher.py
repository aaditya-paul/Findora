import urllib.parse
from app.schemas import PurchaseOption

class PriceSearcher:
    def search_prices(self, component: str, max_price_inr: int = 5000) -> list[PurchaseOption]:
        query = urllib.parse.quote(f"{component} under {max_price_inr} INR")
        return [
            PurchaseOption(
                name=f"Search for {component}",
                store="Google Shopping",
                price_inr=min(max_price_inr, 2999),
                url=f"https://www.google.com/search?tbm=shop&q={query}",
                in_stock=True
            )
        ]
