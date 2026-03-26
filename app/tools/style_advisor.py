import chromadb
from app.llm.router import LLMRouter, Provider
import logging

log = logging.getLogger(__name__)

class StyleAdvisor:
    """ChromaDB-backed RAG over a local corpus of style/grooming tips."""

    def __init__(self, router: LLMRouter, db_path: str = "data/chroma"):
        self.router = router
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            "style_tips",
            metadata={"hnsw:space": "cosine"}
        )
        self._seed_if_empty()

    def _embed(self, text: str) -> list[float]:
        """Use Ollama nomic-embed-text for local embeddings."""
        import httpx
        try:
            resp = httpx.post(
                "http://localhost:11434/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text},
                timeout=10,
            )
            return resp.json()["embedding"]
        except Exception as e:
            log.warning(f"Embedding failed (Ollama running?). Returning zero vector. {e}")
            return [0.0] * 768

    def get_tips(self, context: str, k: int = 5) -> list[str]:
        if self.collection.count() == 0:
            return ["No tips available - index empty."]
            
        embedding = self._embed(context)
        # Handle zero vector safely if embedding failed
        if sum(embedding) == 0.0:
            return self.collection.get(limit=k)["documents"]
            
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=k,
            include=["documents"],
        )
        
        if not results["documents"] or not results["documents"][0]:
            return ["No specific tips found."]
        return results["documents"][0]

    def _seed_if_empty(self):
        if self.collection.count() > 0:
            return
        # Load from bundled corpus on first run
        import json
        from pathlib import Path
        corpus_path = Path("data/tip_corpus.jsonl")
        if not corpus_path.exists():
            log.warning("Tip corpus missing. Skipping seed.")
            return
            
        tips = [json.loads(l) for l in corpus_path.read_text().splitlines()]
        if not tips:
            return
            
        try:
            self.collection.add(
                ids=[str(t["id"]) for t in tips],
                documents=[t["text"] for t in tips],
                metadatas=[{"tags": t.get("tags", "")} for t in tips],
                embeddings=[self._embed(t["text"]) for t in tips],
            )
            log.info(f"Seeded {len(tips)} tips into ChromaDB.")
        except Exception as e:
            log.error(f"Failed to seed tips: {e}")
