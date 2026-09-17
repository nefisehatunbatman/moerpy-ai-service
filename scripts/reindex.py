"""Rebuild all KB embeddings atomically with the explicitly configured provider."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db.base import SessionLocal,init_db
from app.rag.embeddings import get_embedding_provider
from app.rag.knowledge_base import KnowledgeBaseRepository
init_db()
with SessionLocal() as session:
    kb=KnowledgeBaseRepository(session,get_embedding_provider())
    kb.seed_if_empty();kb.reindex()
print('Embedding index rebuilt. Restart API workers after the provider cutover.')
