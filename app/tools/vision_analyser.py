import base64
import httpx
from app.schemas import ClothingComponents

VISION_PROMPT = """
Analyse this outfit image. Return ONLY a JSON object with these exact fields:
top, bottom, footwear, outerwear,
accessories (array of strings),
color_palette (array of hex or color name strings),
style_tags (array of style keywords),
confidence (float 0.0 to 1.0).

Be specific about fabric, fit, and cut when visible.
Set any field to null if not visible. Return NO other text.
"""

class VisionAnalyser:
    def __init__(self, router):
        self.router = router

    def analyse(self, image_url: str) -> ClothingComponents:
        try:
            img_bytes = httpx.get(image_url, timeout=15, follow_redirects=True).content
            b64 = base64.b64encode(img_bytes).decode('utf-8')

            messages = [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": VISION_PROMPT}
                ]
            }]
            raw, provider, model = self.router.complete_vision(messages)
            return ClothingComponents.model_validate_json(raw)
        except Exception as e:
            # Fallback bare minimum components on full failure
            return ClothingComponents(
                confidence=0.0
            )
