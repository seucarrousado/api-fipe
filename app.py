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

@app.get("/preco-google")
async def preco_google(marca: str, modelo: str, ano: str, termo: str):
    query = f"site:mercadolivre.com.br {termo} {marca} {modelo} {ano}".replace(" ", "+")
    url = f"https://www.google.com/search?q={query}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            response = await client.get(url, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")

        resultados = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/url?q=https://www.mercadolivre.com.br"):
                link = href.split("/url?q=")[-1].split("&")[0]
                texto = a.get_text(" ", strip=True)
                preco_match = re.search(r"R\$ ?(\d{2,4}(?:[.,]\d{2})?)", texto)
                if preco_match:
                    preco = float(preco_match.group(1).replace(".", "").replace(",", "."))
                    resultados.append({"preco": preco, "link": link})
            if len(resultados) >= 3:
                break

        if not resultados:
            return {"media": None, "resultados": [], "error": "Nenhum resultado com preço encontrado"}

        media = round(sum(r["preco"] for r in resultados) / len(resultados), 2)
        return {"media": media, "resultados": resultados}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
