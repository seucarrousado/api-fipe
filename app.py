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

def buscar_via_ia(peca, marca, modelo, ano):
    prompt = (
        f"Buscar no site Mercado Livre a peça '{peca}' para o veículo "
        f"{marca} {modelo} {ano}. Retorne apenas os 3 melhores preços e links diretos "
        f"dos anúncios. Calcule o preço médio e forneça no formato:\n"
        "- Preço Médio: R$ [Valor]\n- Links:\n1. [Link1]\n2. [Link2]\n3. [Link3]"
    )

    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Você é um especialista em avaliação de peças automotivas."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content.strip()

async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    relatorio = []
    total_abatimento = 0

    for peca in pecas_selecionadas:
        if not peca or peca.lower() == "não":
            continue

        try:
            ia_response = buscar_via_ia(peca, marca_nome, modelo_nome, ano_nome)

            preco_match = re.search(r"Preço Médio: R\\$ ([\\d\\.,]+)", ia_response)
            preco_medio = float(preco_match.group(1).replace(".", "").replace(",", ".")) if preco_match else 0.0

            links = re.findall(r"https?://\S+", ia_response)

            if preco_medio == 0.0:
                relatorio.append({"item": peca, "erro": "Preço médio não encontrado pela IA."})
                continue

            total_abatimento += preco_medio

            relatorio.append({
                "item": peca,
                "preco_medio": preco_medio,
                "abatido": preco_medio,
                "links": links
            })

        except Exception as e:
            relatorio.append({"item": peca, "erro": f"Erro na resposta da IA: {str(e)}"})

    return relatorio, total_abatimento
