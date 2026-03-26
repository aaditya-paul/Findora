import time
from collections import defaultdict

class GeminiRateGuard:
    def __init__(self):
        self.requests = defaultdict(list)
    
    def can_request(self, model_level: str) -> bool:
        now = time.time()
        minute_ago = now - 60
        self.requests[model_level] = [t for t in self.requests[model_level] if t > minute_ago]
        
        limits = {
            "default": 15,
            "standard": 10,
            "reasoning": 5
        }
        
        return len(self.requests[model_level]) < limits.get(model_level, 5)
        
    def record_request(self, model_level: str):
        self.requests[model_level].append(time.time())

rate_guard = GeminiRateGuard()
