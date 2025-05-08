# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests

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

@app.get("/preco-pastilha")
async def preco_pastilha(marca: str, modelo: str, ano: str):
    termo = f"pastilha de freio {marca} {modelo} {ano}".replace(" ", "+")
    url = f"https://lista.mercadolivre.com.br/{termo}"

    try:
        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = await client.get(url, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")

        precos = []
        for tag in soup.find_all("span"):
            texto = tag.get_text(strip=True).replace(".", "").replace(",", ".")
            if texto.replace(".", "").isdigit():
                valor = float(texto)
                if 20 <= valor <= 2000:
                    precos.append(valor)
            if len(precos) >= 10:
                break

        if len(precos) >= 3:
            media = sum(precos[:3]) / 3
            return {"media": round(media, 2), "resultados": precos[:3]}
        elif precos:
            media = sum(precos) / len(precos)
            return {"media": round(media, 2), "resultados": precos}
        else:
            return {"media": None, "error": "Nenhum preço encontrado."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar preço: {str(e)}")
