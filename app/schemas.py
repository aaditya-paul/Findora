from pydantic import BaseModel, Field
from typing import Optional

class PurchaseOption(BaseModel):
    name: str
    store: str
    price_inr: float
    original_price_inr: Optional[float] = None
    url: str
    image_url: Optional[str] = None
    in_stock: bool = True

class ClothingComponents(BaseModel):
    top: Optional[str] = None
    bottom: Optional[str] = None
    footwear: Optional[str] = None
    outerwear: Optional[str] = None
    accessories: list[str] = Field(default_factory=list)
    color_palette: list[str] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    confidence: float = 0.0

class OutfitCard(BaseModel):
    image_url: str
    source: str
    components: ClothingComponents
    purchase_options: dict[str, list[PurchaseOption]] = Field(default_factory=dict)
    total_min_price_inr: float = 0.0

class OutfitRecommendationResponse(BaseModel):
    query: str
    intent_summary: str
    occasion: str
    outfits: list[OutfitCard] = Field(default_factory=list)
    styling_tips: list[str] = Field(default_factory=list)
    grooming_tips: list[str] = Field(default_factory=list)
    confidence_tips: list[str] = Field(default_factory=list)
    provider_used: str = "ollama"
    model_used: str = "qwen2.5:7b"
    cached: bool = False
