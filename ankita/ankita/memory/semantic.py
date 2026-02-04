"""
Semantic Memory - Meaning-based recall using embeddings.

This is Layer 3 of the memory system:
1. Conversation (short-term)
2. Episodes (actions with tags)
3. Semantic (THIS - meaning-based) 
4. Preferences (habits)

Uses Ollama embeddings for similarity search (no heavy ML deps).
Stores: notes content, episode summaries, important info.
"""

import json
import os
import requests
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional

SEMANTIC_PATH = os.path.join(os.path.dirname(__file__), "semantic.json")
EMBEDDINGS_PATH = os.path.join(os.path.dirname(__file__), "embeddings.npy")
OLLAMA_URL = "http://localhost:11434/api/embeddings"


def _get_embedding(text: str) -> Optional[np.ndarray]:
    """Get embedding from Ollama."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=10
        )
        if response.status_code == 200:
            embedding = response.json().get("embedding")
            if embedding:
                return np.array(embedding)
    except Exception:
        pass
    return None


def _load_store() -> Dict:
    """Load semantic memory store."""
    if not os.path.exists(SEMANTIC_PATH):
        return {"items": []}
    with open(SEMANTIC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(data: Dict):
    """Save semantic memory store."""
    with open(SEMANTIC_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_embeddings() -> Optional[np.ndarray]:
    """Load embeddings array."""
    if not os.path.exists(EMBEDDINGS_PATH):
        return None
    return np.load(EMBEDDINGS_PATH)


def _save_embeddings(embeddings: np.ndarray):
    """Save embeddings array."""
    np.save(EMBEDDINGS_PATH, embeddings)


def add_semantic(text: str, source: str, ref: str = "", tags: List[str] = None) -> bool:
    """
    Add an item to semantic memory.
    
    Args:
        text: The content to remember
        source: Where it came from (note, episode, user, etc.)
        ref: Reference (filename, episode id, etc.)
        tags: Optional tags for filtering
    
    Returns:
        True if successful
    """
    embedding = _get_embedding(text)
    if embedding is None:
        # Fallback: store without embedding (keyword search only)
        print("[Memory] Ollama not available, storing without embedding")
    
    # Load existing data
    store = _load_store()
    embeddings = _load_embeddings()
    
    # Create new item
    item = {
        "id": f"sem_{len(store['items'])}",
        "text": text[:500],  # Limit text length
        "source": source,
        "ref": ref,
        "tags": tags or [],
        "time": datetime.now().isoformat()
    }
    
    # Append to store
    store["items"].append(item)
    _save_store(store)
    
    # Append embedding if available
    if embedding is not None:
        if embeddings is None:
            embeddings = embedding.reshape(1, -1)
        else:
            embeddings = np.vstack([embeddings, embedding])
        _save_embeddings(embeddings)
    
    return True


def search_semantic(query: str, limit: int = 5, source: str = None, tags: List[str] = None) -> List[Dict]:
    """
    Search semantic memory by meaning.
    
    Args:
        query: What to search for
        limit: Max results to return
        source: Filter by source (optional)
        tags: Filter by tags (optional)
    
    Returns:
        List of matching items with scores
    """
    store = _load_store()
    embeddings = _load_embeddings()
    
    if not store["items"]:
        return []
    
    # Try embedding search first
    if embeddings is not None and len(embeddings) == len(store["items"]):
        query_embedding = _get_embedding(query)
        if query_embedding is not None:
            # Calculate cosine similarities
            similarities = np.dot(embeddings, query_embedding) / (
                np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_embedding) + 1e-8
            )
            
            # Get results with scores
            results = []
            for i, (item, score) in enumerate(zip(store["items"], similarities)):
                # Apply filters
                if source and item.get("source") != source:
                    continue
                if tags and not any(t in item.get("tags", []) for t in tags):
                    continue
                
                results.append({
                    **item,
                    "score": float(score)
                })
            
            # Sort by score and limit
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
    
    # Fallback: keyword search
    query_words = set(query.lower().split())
    results = []
    
    for item in store["items"]:
        # Apply filters
        if source and item.get("source") != source:
            continue
        if tags and not any(t in item.get("tags", []) for t in tags):
            continue
        
        # Simple keyword matching
        text_words = set(item.get("text", "").lower().split())
        overlap = len(query_words & text_words)
        if overlap > 0:
            results.append({
                **item,
                "score": overlap / len(query_words)
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def find_by_meaning(query: str, threshold: float = 0.5) -> Optional[Dict]:
    """
    Find the best matching item if score is above threshold.
    """
    results = search_semantic(query, limit=1)
    if results and results[0]["score"] >= threshold:
        return results[0]
    return None


def get_all_semantic(source: str = None) -> List[Dict]:
    """Get all semantic memories, optionally filtered by source."""
    store = _load_store()
    if source:
        return [item for item in store["items"] if item.get("source") == source]
    return store["items"]


def clear_semantic():
    """Clear all semantic memory (for testing)."""
    _save_store({"items": []})
    if os.path.exists(EMBEDDINGS_PATH):
        os.remove(EMBEDDINGS_PATH)
