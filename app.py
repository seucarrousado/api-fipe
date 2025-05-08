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
def preco_ml(termo: str):
    url = "https://api.mercadolibre.com/sites/MLB/search"
    params = {"q": termo, "limit": 5}
    
    token = os.getenv("MELI_ACCESS_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Token de acesso do Mercado Livre não configurado")

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()

        resultados = []
        for item in data.get("results", []):
            resultados.append({
                "titulo": item.get("title"),
                "preco": item.get("price"),
                "link": item.get("permalink")
            })

        if not resultados:
            return {"media": None, "resultados": [], "error": "Nenhum preço encontrado no Mercado Livre"}

        media = sum(item["preco"] for item in resultados) / len(resultados)
        return {"media": media, "resultados": resultados}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar Mercado Livre: {str(e)}")
