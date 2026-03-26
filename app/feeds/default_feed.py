import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from app.agent.orchestrator import OutfitAgent
from app.cache import SqliteCache
from app.llm.router import LLMRouter
import logging

log = logging.getLogger(__name__)

DEFAULT_QUERIES = [
    "men summer street style",
    "women casual college India",
    "minimalist everyday look",
    "indo-western fusion outfit men"
]

cache = SqliteCache("data/cache.db")

def _run_agent_sync(query: str):
    import sys
    router = LLMRouter(preferred="auto")
    agent = OutfitAgent(router)
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(agent.run(query))
        finally:
            loop.close()
    else:
        return asyncio.run(agent.run(query))

def refresh_feed():
    for q in DEFAULT_QUERIES:
        if not cache.is_fresh(q, ttl_hours=6):
            log.info(f"[FEED] Refreshing cache for: {q}")
            try:
                result = _run_agent_sync(q)
                result.cached = True
                cache.set(q, result, ttl_hours=6)
            except Exception as e:
                log.error(f"[FEED] Failed for '{q}': {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(refresh_feed, "interval", hours=6, id="feed_refresh")

def start_feed():
    if not scheduler.running:
        scheduler.start()
        # Trigger initial run in background
        scheduler.add_job(refresh_feed, id="initial_feed_refresh", replace_existing=True)
