from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from cachetools import TTLCache
import httpx
import logging
import re

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

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

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
            response = await client.get(BASE_URL)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter marcas: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter marcas: {str(e)}")


@app.get("/modelos/{marca_id}")
async def listar_modelos(marca_id: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/{marca_id}/modelos"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter modelos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")


@app.get("/anos/{marca_id}/{modelo_id}")
async def listar_anos(marca_id: str, modelo_id: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter anos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")


@app.get("/fipe")
async def consultar_fipe(marca: str, modelo: str, ano: str):
    try:
        cache_key = f"{marca}_{modelo}_{ano}"
        if cache_key in cache:
            logger.info(f"Valor FIPE recuperado do cache para {cache_key}")
            return {"valor_fipe": cache[cache_key]}

        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/{marca}/modelos/{modelo}/anos/{ano}"
            response = await client.get(url)
            response.raise_for_status()
            fipe_data = response.json()

        valor = fipe_data.get("Valor")
        if not valor:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        cache[cache_key] = valor
        return {"valor_fipe": valor}

    except Exception as e:
        logger.error(f"Erro ao consultar FIPE: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")


@app.get("/calcular")
async def calcular_preco_final(marca: str, modelo: str, ano: str, pecas: str = Query("")):
    try:
        params = FipeQuery(marca=marca, modelo=modelo, ano=ano, pecas=pecas)

        # Consulta FIPE
        async with httpx.AsyncClient() as client:
            url_fipe = f"{BASE_URL}/{params.marca}/modelos/{params.modelo}/anos/{params.ano}"
            response = await client.get(url_fipe)
            response.raise_for_status()
            fipe_data = response.json()

        valor_fipe_str = fipe_data.get("Valor")
        if not valor_fipe_str:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        valor_fipe = float(re.sub(r'[^\d,]', '', valor_fipe_str).replace(',', '.'))

        # Processa as peças
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
    url_base = "https://api.mercadolibre.com/sites/MLB/search"
    relatorio = []
    total_abatimento = 0

    async with httpx.AsyncClient() as client:
        for peca in pecas_selecionadas:
            termo_busca = f"{peca} {marca_nome} {modelo_nome} {ano_nome}"
            params = {"q": termo_busca, "limit": 5}

            try:
                response = await client.get(url_base, params=params)
                if response.status_code != 200:
                    relatorio.append({"item": peca, "erro": "Erro na consulta"})
                    continue

                data = response.json()
                resultados = []

                for item in data.get("results", []):
                    preco = item.get("price")
                    titulo = item.get("title")
                    link = item.get("permalink")

                    if preco and preco > 50:
                        resultados.append({"titulo": titulo, "preco": preco, "link": link})

                if not resultados:
                    relatorio.append({"item": peca, "erro": "Nenhum preço válido encontrado"})
                    continue

                top_resultados = resultados[:3]
                media = sum(item["preco"] for item in top_resultados) / len(top_resultados)
                total_abatimento += media

                relatorio.append({
                    "item": peca,
                    "preco_medio": round(media, 2),
                    "abatido": round(media, 2),
                    "links": [item["link"] for item in top_resultados]
                })

            except Exception as e:
                logger.error(f"Erro ao buscar preço de {peca}: {e}")
                relatorio.append({"item": peca, "erro": f"Erro: {str(e)}"})

    return relatorio, total_abatimento

