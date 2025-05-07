from fastapi import FastAPI, HTTPException, Query
import requests

app = FastAPI()

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

@app.get("/fipe")
def consultar_fipe(
    marca: str = Query(..., example="chevrolet"),
    modelo: str = Query(..., example="onix"),
    ano: str = Query(..., example="2020")):

    # 1. Obter a marca
    marcas = requests.get(BASE_URL).json()
    marca_id = next((m["codigo"] for m in marcas if m["nome"].lower() == marca.lower()), None)
    if not marca_id:
        raise HTTPException(status_code=404, detail="Marca não encontrada.")

    # 2. Obter o modelo
    modelos = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()["modelos"]
    modelo_id = next((m["codigo"] for m in modelos if modelo.lower() in m["nome"].lower()), None)
    if not modelo_id:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    # 3. Obter o ano
    anos = requests.get(f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos").json()
    ano_id = next((a["codigo"] for a in anos if ano in a["nome"]), None)
    if not







