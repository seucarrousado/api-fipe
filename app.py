from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def home():
    return {"mensagem": "API de consulta FIPE ativa."}

@app.get("/fipe")
def consulta_fipe(modelo: str = Query(...), ano: int = Query(...)):
    # Simulação de retorno fixo
    resposta = {
        "modelo": modelo,
        "ano": ano,
        "preco_fipe": 50000  # valor fixo de exemplo
    }
    return JSONResponse(content=resposta)





