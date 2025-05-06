from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def home():
    return {"mensagem": "API da Tabela FIPE funcionando corretamente"}



