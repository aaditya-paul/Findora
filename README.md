# Personal-Use AI Outfit Agent

A highly capable AI agent built via a ReAct loop combining LLMs and visual modeling with web scraping and styling RAG. It handles routing between free-tier / local LLM providers depending on rate limits and user configurations.

## Stack

- **Router Layer**: NVIDIA / Gemini / Groq / Ollama selector
- **Vision VLM**: Visual clothing parsing via model
- **UI**: Streamlit
- **Web scraping**: playwright (headless)

## Running Locally

1. Setup virtual environment or utilize UV: `uv pip install -e .`
2. Configure `.env` if desired (from `.env.example`).
3. Run Streamlit:
   ```bash
   streamlit run app/ui/streamlit_app.py
   ```

```
uv pip install -e .
playwright install chromium
streamlit run app/ui/streamlit_app.py
```
