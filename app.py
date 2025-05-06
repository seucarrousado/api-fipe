from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import requests
from bs4 import BeautifulSoup

app = FastAPI()

@app.get("/")
def home():
    return {"mensagem": "API de consulta FIPE ativa."}

@app.get("/fipe")
def consulta_fipe(
    modelo: str = Query(...),
    versao: str = Query(...),
    ano: int = Query(...)
):
    termo_busca = f"valor fipe {modelo} {versao} {ano}"
    url = f"https://www.google.com/search?q={termo_busca.replace(' ', '+')}"
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/90.0.4430.93 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Pega o primeiro valor em R$
        valor = None
        for tag in soup.find_all(string=True):
            if "R$" in tag:
                valor = tag.strip()
                break

        if valor:
            return JSONResponse(content={
                "modelo": modelo,
                "versao": versao,
                "ano": ano,
                "valor_fipe_encontrado": valor
            })
        else:
            return JSONResponse(
                status_code=404,
                content={"erro": "Valor não encontrado. Tente ser mais específico."}
            )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"erro": f"Erro ao buscar valor: {str(e)}"}
        )






