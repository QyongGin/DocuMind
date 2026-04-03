from fastapi import FastAPI
from langchain_ollama import ChatOllama
import chromadb

app = FastAPI()

llm = ChatOllama(
    model="exaone3.5:7.8b",
    base_url="http://localhost:11434"
)

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection("documents")

@app.get("/health")
def health():
    return {"status": "ok"}