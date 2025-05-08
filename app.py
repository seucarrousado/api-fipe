# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import httpx
from bs4 import BeautifulSoup

app = FastAPI()

# Permitir CORS para o domínio da Hostinger
origins = [
    "https://slategrey-camel-778778.hostingersite.com",
    "http://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

@app.get("/marcas")
def listar_marcas():
    try:
        response = requests.get(BASE_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter marcas: {str(e)}")

@app.get("/modelos/{marca_id}")
def listar_modelos(marca_id: str):
    try:
        url = f"{BASE_URL}/{marca_id}/modelos"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")

@app.get("/anos/{marca_id}/{modelo_id}")
def listar_anos(marca_id: str, modelo_id: str):
    try:
        url = f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")

@app.get("/fipe")
def consultar_fipe(marca: str, modelo: str, ano: str):
    try:
        # ✅ Agora os parâmetros já são códigos corretos
        url = f"{BASE_URL}/{marca}/modelos/{modelo}/anos/{ano}"
        fipe_data = requests.get(url).json()

        valor = fipe_data.get("Valor")
        if not valor:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        return {"valor_fipe": valor}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")
from bs4 import BeautifulSoup
import httpx

@app.get("/preco-ml")
async def preco_mercado_livre(marca: str, modelo: str, ano: str, termo: str):
    termo_busca = f"{termo} {marca} {modelo} {ano}".replace(" ", "-").lower()
    url = f"https://lista.mercadolivre.com.br/{termo_busca}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(url, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")

        resultados = []
        cards = soup.select("a.ui-search-result__content, a.ui-search-link")

        for card in cards:
            link = card.get("href", "")
            preco_span = card.select_one("span.andes-money-amount__fraction")

            if preco_span and "mercadolivre.com.br" in link:
                try:
                    preco = float(preco_span.text.replace(".", "").replace(",", "."))
                    if preco > 20:
                        resultados.append({"preco": preco, "link": link.split("?")[0]})
                except:
                    continue
            if len(resultados) >= 3:
                break

        if not resultados:
            return {"media": None, "resultados": [], "error": "Nenhum preço encontrado no Mercado Livre"}

        media = round(sum(r["preco"] for r in resultados) / len(resultados), 2)
        return {"media": media, "resultados": resultados}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
