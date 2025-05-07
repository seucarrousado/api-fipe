# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

# Permitir CORS para Hostinger e local
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
        # 1. Buscar ID da marca
        marcas = requests.get(BASE_URL).json()
        marca_id = next((m["codigo"] for m in marcas if m["nome"].lower() == marca.lower()), None)
        if not marca_id:
            raise HTTPException(status_code=404, detail="Marca não encontrada")

        # 2. Buscar ID do modelo
        modelos = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()["modelos"]
        modelo_id = next((m["codigo"] for m in modelos if modelo.lower() in m["nome"].lower()), None)
        if not modelo_id:
            raise HTTPException(status_code=404, detail="Modelo não encontrado")

        # 3. Consultar FIPE com código do ano (ex: 2023-1)
        url = f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos/{ano}"
        fipe_data = requests.get(url).json()

        valor = fipe_data.get("Valor")
        if not valor:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        return {"valor_fipe": valor}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")
