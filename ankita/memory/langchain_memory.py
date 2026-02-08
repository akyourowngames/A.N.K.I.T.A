"""
LangChain Memory Layer - Unlimited long-term context using Vector Storage.
This integrates with the existing A.N.K.I.T.A memory system to provide
meaning-based retrieval over months of data.
"""

import os
import logging
from datetime import datetime
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from pathlib import Path

# Suppress transformers warnings
logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)

# Paths
_MEMORY_DIR = Path(__file__).parent
VECTOR_DB_PATH = _MEMORY_DIR / "vector_db"

class LangChainMemory:
    """Unlimited memory powered by LangChain and FAISS."""
    
    def __init__(self):
        # Use local HuggingFace embeddings (no server needed)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2"
        )
        self.vector_store = self._load_or_create_db()

    def _load_or_create_db(self):
        """Load existing FAISS index or create a new one."""
        if VECTOR_DB_PATH.exists():
            try:
                return FAISS.load_local(
                    str(VECTOR_DB_PATH), 
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
            except Exception as e:
                print(f"[LangChainMemory] Load error: {e}")
        
        # Create empty index with a dummy document
        dummy_doc = Document(page_content="Initial memory", metadata={"time": datetime.now().isoformat()})
        db = FAISS.from_documents([dummy_doc], self.embeddings)
        return db

    def add_memory(self, text, metadata=None):
        """Add a new document/interaction to long-term memory."""
        if not text or not text.strip():
            return
            
        doc = Document(
            page_content=text,
            metadata=metadata or {"time": datetime.now().isoformat()}
        )
        self.vector_store.add_documents([doc])
        self._save_db()
        print(f"[LangChainMemory] Archived: {text[:50]}...")

    def bulk_add(self, texts: list, metadatas: list = None):
        """Add multiple memories at once."""
        docs = []
        for i, t in enumerate(texts):
            if t and t.strip():
                m = metadatas[i] if metadatas else {"time": datetime.now().isoformat()}
                docs.append(Document(page_content=t, metadata=m))
        
        if docs:
            self.vector_store.add_documents(docs)
            self._save_db()
            print(f"[LangChainMemory] Bulk added {len(docs)} items.")

    def retrieve_context(self, query, k=5):
        """Retrieve the most relevant past memories for a query."""
        try:
            docs = self.vector_store.similarity_search(query, k=k)
            return "\n".join([d.page_content for d in docs if d.page_content != "Initial memory"])
        except Exception as e:
            print(f"[LangChainMemory] Retrieval error: {e}")
            return ""

    def _save_db(self):
        """Persist the vector store to disk."""
        self.vector_store.save_local(str(VECTOR_DB_PATH))


# Singleton
_lc_memory = None

def get_langchain_memory():
    global _lc_memory
    if _lc_memory is None:
        _lc_memory = LangChainMemory()
    return _lc_memory
