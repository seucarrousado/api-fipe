# app.py
from fastapi import FastAPI, HTTPException, Query
import requests
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Permitir CORS para seu site na Hostinger
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
def consultar_fipe(marca_id: str = Query(...), modelo_id: str = Query(...), ano_codigo: str = Query(...)):
    try:
        url = f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos/{ano_codigo}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return {"valor_fipe": data["Valor"]}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Erro ao consultar FIPE: {str(e)}")
