import json
import logging
from app.llm.router import LLMRouter, Provider
from app.tools.image_scraper import ImageScraper
from app.tools.vision_analyser import VisionAnalyser
from app.tools.price_searcher import PriceSearcher
from app.tools.style_advisor import StyleAdvisor
from app.schemas import OutfitRecommendationResponse, OutfitCard

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a personal outfit recommendation agent operating in a ReAct loop.
You have access to the following tools. Call them in order — do NOT fabricate
any URLs, prices, or image data. All external data MUST come from tool results.

Tools available:
  search_outfit_images(query: str) -> list[{url, alt, source}]
  analyze_outfit_image(image_url: str) -> ClothingComponents JSON
  search_prices(component: str, max_price_inr: int) -> list[PurchaseOption]
  get_style_tips(context: str) -> list[str]

Reasoning mode: Use structured thinking to plan which tools to call and in what order.
JSON output: Your FINAL response must be a valid OutfitRecommendationResponse JSON
object. Never include markdown fences. Never output partial JSON.

For NVIDIA Nemotron models: the system prompt controls reasoning mode.
For efficiency on tool-calling turns, reasoning is OFF by default here.
/no_think
"""

class OutfitAgent:
    def __init__(self, router: LLMRouter):
        self.router = router
        self.scraper = ImageScraper(headless=False)
        self.vision = VisionAnalyser(router)
        self.pricings = PriceSearcher()
        self.advisor = StyleAdvisor(router)

    async def run(self, query: str) -> OutfitRecommendationResponse:
        log.info(f"Agent starting run for query: {query}")
        
        # 1. Scrape Images
        images = await self.scraper.scrape_pinterest(query, n=6)
        if not images:
            log.warning("No images found for query.")
            return self._empty_response(query)

        outfits = []
        # 2. Analyze & Price Search
        for img in images:
            img_url = img["src"]
            components = self.vision.analyse(img_url)
            
            purchase_options = {}
            total_price = 0.0
            
            # Simple pricing aggregation
            if components.top:
                opts = self.pricings.search_prices(components.top, 3000)
                purchase_options["top"] = opts
                if opts: total_price += opts[0].price_inr
                
            if components.bottom:
                opts = self.pricings.search_prices(components.bottom, 4000)
                purchase_options["bottom"] = opts
                if opts: total_price += opts[0].price_inr
                
            if components.footwear:
                opts = self.pricings.search_prices(components.footwear, 5000)
                purchase_options["footwear"] = opts
                if opts: total_price += opts[0].price_inr
                
            outfits.append(OutfitCard(
                image_url=img_url,
                source="Pinterest",
                components=components,
                purchase_options=purchase_options,
                total_min_price_inr=total_price
            ))

        # 3. Get Style tips
        style_tips_raw = self.advisor.get_tips(query, k=2)
        
        # 4. Final LLM Aggregation
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Query: {query}\n\nProcessed Data:\nOutfits: {len(outfits)}\nTips context: {style_tips_raw}\n\nGenerate the final OutfitRecommendationResponse JSON. Focus on styling_tips, grooming_tips and confidence_tips based on context."}
        ]
        
        raw_json, provider, model = self.router.complete(messages, task="standard", json_mode=True)
        
        try:
            resp = OutfitRecommendationResponse.model_validate_json(raw_json)
            # Inject our strictly retrieved data to prevent hallucinations
            resp.outfits = outfits
            resp.provider_used = provider
            resp.model_used = model
            resp.query = query
            return resp
        except Exception as e:
            log.error(f"Failed to parse agent final response: {e}. Raw: {raw_json}")
            fallback_tips = style_tips_raw if isinstance(style_tips_raw, list) else [style_tips_raw]
            # Fallback response
            return OutfitRecommendationResponse(
                query=query,
                intent_summary="Fallback Generation due to parsing error",
                occasion="Unknown",
                outfits=outfits,
                styling_tips=fallback_tips,
                grooming_tips=fallback_tips[:2],
                confidence_tips=fallback_tips[2:4] if len(fallback_tips) > 2 else fallback_tips[:2],
                provider_used=provider,
                model_used=model
            )

    def _empty_response(self, query: str) -> OutfitRecommendationResponse:
        return OutfitRecommendationResponse(
            query=query,
            intent_summary="No images found for this query.",
            occasion="",
            outfits=[],
            provider_used="none",
            model_used="none"
        )
