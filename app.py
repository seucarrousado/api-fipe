from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"mensagem": "API da Tabela FIPE funcionando corretamente"}


