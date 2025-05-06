from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
async def root():
    return JSONResponse(content={"mensagem": "API da Tabela FIPE funcionando corretamente"})
