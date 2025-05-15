from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from cachetools import TTLCache
import httpx
import logging
import re
import os
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

# Logging Config
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calculadora_fipe")

# CORS Restrito
origins = [
    "https://slategrey-camel-778778.hostingersite.com",
    "http://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

BASE_URL = "https://api.invertexto.com/v1/fipe"
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")  # Token seguro via variável de ambiente

# Cache para dados da FIPE (1 hora de validade)
cache = TTLCache(maxsize=100, ttl=3600)

# Validação de Parâmetros com Pydantic
class FipeQuery(BaseModel):
    marca: str
    modelo: str
    ano: str
    pecas: str

    @validator('marca', 'modelo', 'ano')
    def check_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Campo obrigatório não pode ser vazio.')
        return v

@app.get("/marcas")
async def listar_marcas():
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/brands/1?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter marcas: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter marcas: {str(e)}")

@app.get("/modelos/{marca_id}")
async def listar_modelos(marca_id: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/models/{marca_id}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter modelos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")

@app.get("/anos/{fipe_code}")
async def listar_anos(fipe_code: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter anos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")

@app.get("/fipe")
async def consultar_fipe(fipe_code: str):
    try:
        cache_key = f"{fipe_code}"
        if cache_key in cache:
            logger.info(f"Valor FIPE recuperado do cache para {cache_key}")
            return {"valor_fipe": cache[cache_key]}

        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            fipe_data = response.json()

        valores = fipe_data.get("years", [])
        if not valores:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        valor_mais_recente = valores[-1]["price"]

        cache[cache_key] = valor_mais_recente
        return {"valor_fipe": valor_mais_recente}

    except Exception as e:
        logger.error(f"Erro ao consultar FIPE: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")

@app.get("/calcular")
async def calcular_preco_final(marca: str, modelo: str, ano: str, pecas: str = Query("")):
    try:
        params = FipeQuery(marca=marca, modelo=modelo, ano=ano, pecas=pecas)

        async with httpx.AsyncClient() as client:
            url_fipe = f"{BASE_URL}/years/{params.modelo}?token={TOKEN}"
            response = await client.get(url_fipe)
            response.raise_for_status()
            fipe_data = response.json()

        valores = fipe_data.get("years", [])
        if not valores:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        valor_fipe = valores[-1]["price"]

        lista_pecas = [p.strip() for p in params.pecas.split(",") if p.strip()]
        relatorio, total_abatido = await buscar_precos_e_gerar_relatorio(
            params.marca, params.modelo, params.ano, lista_pecas
        )

        valor_final = round(valor_fipe - total_abatido, 2)

        return {
            "valor_fipe": f"R$ {valor_fipe:.2f}",
            "total_abatido": f"R$ {total_abatido:.2f}",
            "valor_final": f"R$ {valor_final:.2f}",
            "relatorio_detalhado": relatorio
        }

    except Exception as e:
        logger.error(f"Erro no cálculo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro no cálculo: {str(e)}")

async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    relatorio = []
    total_abatimento = 0
    apify_token = os.getenv("APIFY_API_TOKEN")

    for peca in pecas_selecionadas:
        if not peca or peca.lower() == "não":
            continue

        try:
            # Monta a consulta para a API da Apify
            search_query = f"{peca} {marca_nome} {modelo_nome} {ano_nome}"
            url = "https://api.apify.com/v2/acts/karamelo~mercadolivre-scraper-brasil-portugues/run-sync-get-dataset-items"

            params = {
                "token": apify_token,
                "search": search_query,
                "language": "portuguese",
                "maxItems": 3,  # Limita a 3 resultados
                "format": "json"
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                resultados = response.json()

            # Calcula o preço médio dos 3 primeiros resultados
            precos = []
            links = []

            for item in resultados[:3]:
                preco = item.get("novoPreco") or item.get("precoAnterior")
                try:
                    preco_float = float(str(preco).replace(",", "."))
                    precos.append(preco_float)
                except (ValueError, TypeError):
                    continue

                links.append(item.get("zProdutoLink"))

            if not precos:
                relatorio.append({"item": peca, "erro": "Nenhum preço válido encontrado na pesquisa."})
                continue

            preco_medio = round(sum(precos) / len(precos), 2)
            total_abatimento += preco_medio

            relatorio.append({
                "item": peca,
                "preco_medio": preco_medio,
                "abatido": preco_medio,
                "links": links
            })

        except Exception as e:
            relatorio.append({"item": peca, "erro": f"Erro ao buscar na API da Apify: {str(e)}"})

    return relatorio, total_abatimento
