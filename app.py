from fastapi import FastAPI, HTTPException, Query
import requests
import unicodedata

app = FastAPI()

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

# Função para remover acentos e normalizar texto
def normalize(text):
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()

@app.get("/fipe")
def consultar_fipe(
    marca: str = Query(..., example="chevrolet"),
    modelo: str = Query(..., example="onix"),
    ano: str = Query(..., example="2020")
):
    try:
        # 1. Obter a marca (busca parcial e normalizada)
        marcas = requests.get(BASE_URL).json()
        marca_id = next(
            (m["codigo"] for m in marcas if normalize(marca) in normalize(m["nome"])),
            None
        )
        if not marca_id:
            raise HTTPException(status_code=404, detail="Erro na consulta: 404: Marca não encontrada.")

        # 2. Obter o modelo (busca parcial e normalizada)
        modelos = requests.get(f"{BASE_URL}/{marca_id}/modelos").json()["modelos"]
        modelo_id = next(
            (m["codigo"] for m in modelos if normalize(modelo) in normalize(m["nome"])),
            None
        )
        if not modelo_id:
            raise HTTPException(status_code=404, detail="Erro na consulta: 404: Modelo não encontrado.")

        # 3. Obter o ano (busca parcial, aceita '2020 Flex', etc.)
        anos = requests.get(f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos").json()
        ano_id = next(
            (a["codigo"] for a in anos if normalize(ano) in normalize(a["nome"]) or a["nome"].startswith(ano)),
            None
        )
        if not ano_id:
            raise HTTPException(status_code=404, detail="Erro na consulta: 404: Ano não encontrado.")

        # 4. Obter valor final da FIPE
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
        raise HTTPException(status_code=500, detail=f"Erro interno na consulta: {str(e)}")
