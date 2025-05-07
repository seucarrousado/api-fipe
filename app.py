from fastapi import FastAPI, HTTPException, Query
import requests
import unicodedata

app = FastAPI()

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

def normalize(text):
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()

# 1. Lista todas as marcas
@app.get("/marcas")
def listar_marcas():
    return requests.get(BASE_URL).json()

# 2. Lista todos os modelos de uma marca
@app.get("/modelos")
def listar_modelos(marca: str = Query(..., example="chevrolet")):
    marcas = requests.get(BASE_URL).json()
    marca_id = next(
        (m["codigo"] for m in marcas if normalize(marca) in normalize(m["nome"])),
        None
    )
    if not marca_id:
        raise HTTPException(status_code=404, detail="Marca não encontrada.")
    resposta = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()
    return resposta["modelos"]

# 3. Lista todos os anos disponíveis de um modelo
@app.get("/anos")
def listar_anos(marca: str = Query(...), modelo: str = Query(...)):
    marcas = requests.get(BASE_URL).json()
    marca_id = next(
        (m["codigo"] for m in marcas if normalize(marca) in normalize(m["nome"])),
        None
    )
    if not marca_id:
        raise HTTPException(status_code=404, detail="Marca não encontrada.")

    modelos = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()["modelos"]
    modelo_id = next(
        (m["codigo"] for m in modelos if normalize(modelo) in normalize(m["nome"])),
        None
    )
    if not modelo_id:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")

    return requests.get(f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos").json()

# 4. Consulta final com marca, modelo e ano
@app.get("/fipe")
def consultar_fipe(
    marca: str = Query(...),
    modelo: str = Query(...),
    ano: str = Query(...)
):
    try:
        marcas = requests.get(BASE_URL).json()
        marca_id = next(
            (m["codigo"] for m in marcas if normalize(marca) in normalize(m["nome"])),
            None
        )
        if not marca_id:
            raise HTTPException(status_code=404, detail="Marca não encontrada.")

        modelos = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()["modelos"]
        modelo_id = next(
            (m["codigo"] for m in modelos if normalize(modelo) in normalize(m["nome"])),
            None
        )
        if not modelo_id:
            raise HTTPException(status_code=404, detail="Modelo não encontrado.")

        anos = requests.get(f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos").json()
        ano_id = next(
            (a["codigo"] for a in anos if normalize(ano) in normalize(a["nome"]) or a["nome"].startswith(ano)),
            None
        )
        if not ano_id:
            raise HTTPException(status_code=404, detail="Ano não encontrado.")

        resultado = requests.get(f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos/{ano_id}").json()
        return {
            "modelo_completo": resultado.get("Modelo"),
            "marca": resultado.get("Marca"),
            "ano_modelo": resultado.get("AnoModelo"),
            "valor_fipe": resultado.get("Valor"),
            "combustivel": resultado.get("Combustivel"),
            "codigo_fipe": resultado.get("CodigoFipe")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")
