You said:
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from cachetools import TTLCache
import httpx
import logging
import os
import asyncio

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calculadora_fipe")

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
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR = "seucarrousado/buscarprecomercadolivre"

cache = TTLCache(maxsize=100, ttl=3600)

class FipeQuery(BaseModel):
    marca: str
    modelo: str
    ano: str
    pecas: str

    @validator('marca', 'modelo', 'ano')
    def not_empty(cls, v):
        if not v.strip():
            raise ValueError('Campo obrigatório não pode ser vazio.')
        return v

# Rotas para alimentar o frontend com marcas, modelos e anos
@app.get("/marcas")
async def listar_marcas():
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/brands/1?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
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
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")

async def obter_nome_marca(codigo_marca):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/brands?token={TOKEN}")
        response.raise_for_status()
        marcas = response.json()
        for marca in marcas:
            if str(marca.get('id')) == str(codigo_marca):
                return marca.get('brand')
    return "Marca Desconhecida"
    
async def obter_nome_modelo(codigo_modelo):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/models/{codigo_modelo}?token={TOKEN}")
        response.raise_for_status()
        modelos = response.json()
        return modelos.get('model', "Modelo Desconhecido")

async def obter_nome_ano(codigo_ano):
    return codigo_ano.split('-')[0]  # Exemplo: '2022' de '2022-01'

@app.get("/anos/{fipe_code}")
async def listar_anos(fipe_code: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")

# Consulta de valor FIPE
@app.get("/fipe")
async def consultar_fipe(fipe_code: str):
    try:
        cache_key = f"{fipe_code}"
        if cache_key in cache:
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
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")

# Consulta de preços de peças via Apify
@app.get("/pecas")
async def buscar_precos_pecas(marca: str, modelo: str, ano: str, pecas: str = Query("")):
    try:
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        marca_nome = await obter_nome_marca(marca)
        modelo_nome = await obter_nome_modelo(modelo)

        ano_nome = ano if ano else "Ano não informado"

        relatorio, total_abatido = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_nome, lista_pecas
        )

        return {
            "total_abatido": f"R$ {total_abatido:.2f}",
            "relatorio_detalhado": relatorio
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na consulta de peças: {str(e)}")

# Lógica para buscar preços na Apify e calcular o preço médio das peças
async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    relatorio = []
    total_abatimento = 0

    api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/runs?token={APIFY_TOKEN}"

    async with httpx.AsyncClient() as client:
        for peca in pecas_selecionadas:
            if not peca or peca.lower() == "não":
                continue

            termo_busca = f"{peca.strip()} {marca_nome} {modelo_nome} {ano_nome}"
            payload = {"keyword": termo_busca, "pages": 1, "promoted": False}

            try:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                data = response.json()

                run_id = data.get("data", {}).get("id")
                if not run_id:
                    relatorio.append({"item": peca, "erro": "Erro ao iniciar busca no Apify."})
                    continue

                # Aguardar a execução do Actor finalizar
                status = ""
                while status != "SUCCEEDED":
                    await asyncio.sleep(2)
                    status_resp = await client.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}")
                    status = status_resp.json().get("data", {}).get("status", "")
                    if status in ["FAILED", "ABORTED"]:
                        relatorio.append({"item": peca, "erro": "Task no Apify falhou."})
                        continue

                # Obter resultados do Dataset
                dataset_id = status_resp.json().get("data", {}).get("defaultDatasetId")
                dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?format=json&clean=true&token={APIFY_TOKEN}"
                dataset_resp = await client.get(dataset_url)
                dataset_resp.raise_for_status()
                produtos = dataset_resp.json()

                if not produtos:
                    relatorio.append({"item": peca, "erro": "Nenhum resultado encontrado."})
                    continue

                precos = []
                links = []
                for item in produtos[:5]:
                    try:
                        preco = float(str(item.get("novoPreco", "0")).replace(".", "").replace(",", "."))
                        precos.append(preco)
                        links.append(item.get("zProdutoLink", ""))
                    except:
                        continue

                if not precos:
                    relatorio.append({"item": peca, "erro": "Preços não encontrados."})
                    continue

                preco_medio = round(sum(precos) / len(precos), 2)
                total_abatimento += preco_medio

                relatorio.append({
                    "item": peca,
                    "preco_medio": preco_medio,
                    "abatido": preco_medio,
                    "links": links[:3]
                })

            except Exception as e:
                relatorio.append({"item": peca, "erro": f"Erro ao buscar preços via Apify: {str(e)}"})

    return relatorio, total_abatimento
