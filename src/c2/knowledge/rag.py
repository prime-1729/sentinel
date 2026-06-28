import os
import glob
from typing import List, Dict, Any
import chromadb
from chromadb.utils import embedding_functions

# Use the nomic-embed-text model via Ollama for embeddings
ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="nomic-embed-text"
)

class SentinelRAG:
    def __init__(self, persist_dir: str = "data/chroma", docs_dir: str = "src/knowledge"):
        self.docs_dir = docs_dir
        
        # Ensure persistence directory exists
        os.makedirs(persist_dir, exist_ok=True)
        
        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # Get or create the collection with our Ollama embedding function
        self.collection = self.client.get_or_create_collection(
            name="sentinel_knowledge",
            embedding_function=ollama_ef
        )
        
        # Automatically ingest any new documents on startup
        self._ingest_documents()
        
    def _ingest_documents(self):
        """Read markdown files from the knowledge directory and add them to ChromaDB"""
        if not os.path.exists(self.docs_dir):
            print(f"RAG: Knowledge directory {self.docs_dir} not found.")
            return
            
        md_files = glob.glob(os.path.join(self.docs_dir, "*.md"))
        
        for file_path in md_files:
            file_id = os.path.basename(file_path)
            
            # Check if we already have this document
            try:
                existing = self.collection.get(ids=[file_id])
                if existing and existing['ids'] and len(existing['ids']) > 0:
                    continue # Skip if already ingested
            except Exception:
                pass
                
            print(f"RAG: Ingesting {file_id}")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # For this simple implementation, we chunk by sections (split by H2 '## ')
            # In a production system, you'd use a proper text splitter (like LangChain's RecursiveCharacterTextSplitter)
            chunks = content.split("## ")
            
            ids = []
            documents = []
            metadatas = []
            
            # First chunk might be just the H1 title and intro, let's keep it
            if chunks[0].strip():
                ids.append(f"{file_id}_intro")
                documents.append(chunks[0].strip())
                metadatas.append({"source": file_id, "section": "intro"})
                
            # Process remaining sections
            for i, chunk in enumerate(chunks[1:]):
                if not chunk.strip():
                    continue
                # Add the '## ' back so context is preserved
                chunk_text = f"## {chunk}".strip()
                ids.append(f"{file_id}_section_{i}")
                documents.append(chunk_text)
                
                # Extract section title for metadata
                section_title = chunk.split("\n")[0].strip()
                metadatas.append({"source": file_id, "section": section_title})
                
            if ids:
                self.collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                
    def retrieve_context(self, query: str, n_results: int = 3) -> str:
        """Query the vector database for relevant documentation"""
        if self.collection.count() == 0:
            return "No background knowledge available."
            
        results = self.collection.query(
            query_texts=[query],
            n_results=min(n_results, self.collection.count())
        )
        
        if not results['documents'] or not results['documents'][0]:
            return "No relevant background knowledge found."
            
        # Format the retrieved chunks into a single string for the LLM
        context_parts = []
        for i, doc in enumerate(results['documents'][0]):
            source = results['metadatas'][0][i]['source']
            context_parts.append(f"--- Document: {source} ---\n{doc}")
            
        return "\n\n".join(context_parts)

# Singleton instance for easy import
rag = SentinelRAG()

if __name__ == "__main__":
    # Test the RAG system
    print("Testing RAG retrieval...")
    context = rag.retrieve_context("What does IdleDrift mean and how do I query for it?")
    print(f"\nRetrieved Context:\n{context}")
