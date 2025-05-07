from fastapi import FastAPI, HTTPException, Query
import requests

app = FastAPI()

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

@app.get("/fipe")
def consultar_fipe(
    marca: str = Query(..., example="chevrolet"),
    modelo: str = Query(..., example="onix"),
    ano: str = Query(..., example="2020")):
    
    try:
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
        if not ano_id:
            raise HTTPException(status_code=404, detail="Ano não encontrado.")

        # 4. Obter valor final
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
        raise HTTPException(status_code=500, detail=f"Erro na consulta: {str(e)}")
