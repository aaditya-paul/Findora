import sys
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st

# Add the project root to sys.path so 'app' can be imported easily
sys.path.append(str(Path(__file__).parent.parent.parent))

# Load .env from project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from app.llm.router import LLMRouter, Provider
from app.agent.orchestrator import OutfitAgent
from app.feeds.default_feed import start_feed, cache, DEFAULT_QUERIES
from app.schemas import OutfitRecommendationResponse

st.set_page_config(page_title="Personal AI Outfit Agent", layout="wide", page_icon="👔")

# Initialize the background feed
start_feed()

st.title("👔 Personal AI Outfit Agent")
st.markdown("Your local-first, free-tier intelligent stylist.")

with st.sidebar:
    st.header("⚙️ Advanced LLM Settings")
    st.markdown("Force a specific provider instead of automatic routing.")
    preferred = st.selectbox(
        "Provider",
        options=["auto", "nvidia", "gemini", "groq", "ollama"],
        index=0
    )
    model_override = st.text_input("Custom Model Override", value="", help="e.g. qwen2.5:7b or gemini-2.5-flash")
    
    st.divider()
    st.markdown("**API Keys Found:**")
    nvidia_ok  = bool(os.getenv("NVIDIA_API_KEY"))
    gemini_ok  = bool(os.getenv("GEMINI_API_KEY"))
    groq_ok    = bool(os.getenv("GROQ_API_KEY"))
    ollama_ok  = False
    try:
        import httpx
        ollama_ok = httpx.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        pass
    st.markdown(f"- NVIDIA_API_KEY: {'✅' if nvidia_ok else '❌'}")
    st.markdown(f"- GEMINI_API_KEY: {'✅' if gemini_ok else '❌'}")
    st.markdown(f"- GROQ_API_KEY: {'✅' if groq_ok else '❌'}")
    st.markdown(f"- Ollama (local): {'✅ Running' if ollama_ok else '⚠️ Not detected'}")

    st.divider()
    st.markdown("**Pinterest Auth:**")
    from app.tools.pinterest_auth import session_exists, run_login_flow
    if session_exists():
        st.markdown("🟢 Session active — scraping with cookies")
        if st.button("🔄 Re-login to Pinterest"):
            with st.spinner("Opening browser for Pinterest login..."):
                run_login_flow()
            st.success("Session refreshed!")
    else:
        st.warning("No Pinterest session. Scraping may hit CAPTCHAs.")
        if st.button("🔑 Sign in to Pinterest"):
            with st.spinner("Opening browser — log in, then press Enter in the terminal..."):
                run_login_flow()
            st.success("✅ Session saved! Scraping will now use your login.")

    st.divider()
    # Force feed refresh button
    if st.button("Refresh Default Feed Cache"):
        from app.feeds.default_feed import refresh_feed
        refresh_feed()
        st.success("Default Feed Cache refreshed.")


def render_outfit_card(outfit):
    col1, col2 = st.columns([1, 2])
    with col1:
        st.image(outfit.image_url, width=420, caption=f"Source: {outfit.source}")
    with col2:
        st.subheader("Outfit Components")
        st.json(outfit.components.model_dump(exclude_none=True))
        st.markdown(f"**Estimated Cost:** ₹{outfit.total_min_price_inr:,.2f}")
        for part, options in outfit.purchase_options.items():
            if options:
                opt = options[0]
                st.markdown(f"- **{part.title()}**: [{opt.store}]({opt.url}) @ ₹{opt.price_inr:,.2f}")

def render_advice(tips, title, icon="💡"):
    st.subheader(f"{icon} {title}")
    if not tips:
        st.write("No specific advice.")
    # Standardize list formatting just in case string was dumped instead of list 
    tiplist = tips if isinstance(tips, list) else [tips]
    for tip in tiplist:
        st.markdown(f"- {tip}")

def display_response(resp: OutfitRecommendationResponse):
    if getattr(resp, "cached", False):
        st.info("⚡ Served from Local Cache")
        
    st.success(f"Generated via **{resp.provider_used}** ({resp.model_used}) in reasoning mode.")
    st.markdown(f"**Intent Summary:** {resp.intent_summary} (Occasion: {resp.occasion})")
    
    if not resp.outfits:
        st.warning("No outfits could be sourced.")
    else:
        for i, outfit in enumerate(resp.outfits):
            st.markdown(f"### Outfit #{i+1}")
            render_outfit_card(outfit)
            st.divider()
        
    c1, c2, c3 = st.columns(3)
    with c1: render_advice(resp.styling_tips, "Styling Tips", "👔")
    with c2: render_advice(resp.grooming_tips, "Grooming Tips", "💈")
    with c3: render_advice(resp.confidence_tips, "Confidence Tips", "💯")

query = st.chat_input("Describe the outfit you're looking for... (e.g. 'summer beach party men')")

if query:
    with st.spinner("Analyzing request, fetching references, and styling..."):
        cached_raw = cache.get(query)
        if cached_raw:
            resp = OutfitRecommendationResponse.model_validate(cached_raw)
            resp.cached = True
            display_response(resp)
        else:
            override = model_override if model_override.strip() else None
            router = LLMRouter(preferred=preferred, model_override=override)
            agent = OutfitAgent(router)
            
            try:
                import sys as _sys
                if _sys.platform == "win32":
                    _loop = asyncio.ProactorEventLoop()
                    asyncio.set_event_loop(_loop)
                    try:
                        resp = _loop.run_until_complete(agent.run(query))
                    finally:
                        _loop.close()
                else:
                    resp = asyncio.run(agent.run(query))
                resp.cached = False
                cache.set(query, resp, ttl_hours=1)
                display_response(resp)
            except Exception as e:
                st.error(f"Execution Error: {str(e)}")
else:
    # Default Feed
    st.header("🔥 Trending Looks")
    for def_query in DEFAULT_QUERIES:
        cached_raw = cache.get(def_query)
        if cached_raw:
            resp = OutfitRecommendationResponse.model_validate(cached_raw)
            with st.expander(f"Look: {def_query.title()}"):
                display_response(resp)
        else:
            with st.expander(f"Look: {def_query.title()} (Generating in background...)"):
                st.write("This feed item is currently being built by the background agent.")
