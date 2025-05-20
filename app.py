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

logger.info("[DEBUG] API Inicializada com sucesso!")

origins = [
    "https://slategrey-camel-778778.hostingersite.com",
    "http://localhost",
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
APIFY_ACTOR = os.getenv("APIFY_ACTOR")
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
    return codigo_ano.split('-')[0]

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

@app.get("/pecas")
async def buscar_precos_pecas(marca: str, modelo: str, ano: str, pecas: str = Query("")):
    try:
        from urllib.parse import unquote

        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        marca_nome = marca
        modelo_nome = modelo.replace("  ", " ").strip()
        ano_nome = ano if ano else "Ano não informado"

        relatorio, total_abatido = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_nome, lista_pecas
        )

        return {
            "total_abatido": f"R$ {total_abatido:.2f}",
            "relatorio_detalhado": relatorio,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na consulta de peças: {str(e)}")

async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    import logging
    import httpx

    logger = logging.getLogger("calculadora_fipe")
    relatorio = []
    total_abatimento = 0

    # ✅ URL RESTAURADA
    api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"

    logger.info("[DEBUG] Função buscar_precos_e_gerar_relatorio foi chamada.")
    logger.info(f"[DEBUG] URL Apify: {api_url}")
    logger.info(f"[DEBUG] Peças Selecionadas: {pecas_selecionadas}")
    logger.info(f"[DEBUG] Marca: {marca_nome}, Modelo: {modelo_nome}, Ano: {ano_nome}")

    async with httpx.AsyncClient(timeout=60) as client:
        for peca in pecas_selecionadas:
            if not peca or peca.lower() == "não":
                continue

            termo_busca = f"{peca.strip()} {marca_nome} {modelo_nome} {ano_nome}".replace("  ", " ").strip()
            payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
            logger.info(f"[DEBUG] Buscando peça: {termo_busca} | Payload: {payload}")

            try:
                response = await client.post(api_url, json=payload)
                logger.info(f"[DEBUG] Status Apify: {response.status_code}")

                try:
                    response.raise_for_status()
                except Exception as e:
                    logger.error(f"[ERROR] Falha no status da resposta: {e}")
                    logger.error(f"[ERROR] Corpo da resposta: {response.text}")
                    relatorio.append({"item": peca, "erro": "Erro HTTP ao acessar o Apify."})
                    continue

                try:
                    dados_completos = response.json()
                    logger.info(f"[DEBUG] Tipo da resposta: {type(dados_completos)}")
                    logger.info(f"[DEBUG] Conteúdo bruto da resposta Apify: {dados_completos}")
                except Exception as e:
                    logger.error(f"[ERROR] Falha ao ler JSON: {str(e)}")
                    relatorio.append({"item": peca, "erro": "Resposta do Apify inválida (JSON)."})
                    continue

                if not isinstance(dados_completos, list):
                    logger.error(f"[ERROR] Resposta do Apify não é uma lista: {type(dados_completos)}")
                    relatorio.append({"item": peca, "erro": "Formato de resposta inesperado."})
                    continue

                if not dados_completos:
                    relatorio.append({"item": peca, "erro": "Nenhum resultado encontrado."})
                    continue

                precos = []
                links = []
                imagens = []
                nomes = []
                precos_texto = []

                for item in dados_completos[:5]:
                    logger.info(f"[DEBUG] Produto bruto: {item}")

                    preco_str = item.get("novoPreco")
                    if not preco_str:
                        logger.warning(f"[WARN] Produto sem preço válido: {item}")
                        continue

                    try:
                        preco = float(str(preco_str).replace(".", "").replace(",", "."))
                        precos.append(preco)
                        links.append(item.get("zProdutoLink", ""))
                        imagens.append(item.get("imagemLink", ""))
                        nomes.append(item.get("eTituloProduto", ""))
                        precos_texto.append(preco_str)  
                    except Exception as e:
                        logger.warning(f"[WARN] Erro ao converter preço: {preco_str} | {e}")
                        continue

                if not precos:
                    relatorio.append({"item": peca, "erro": "Nenhum preço válido encontrado."})
                    continue

                preco_medio = round(sum(precos) / len(precos), 2)
                total_abatimento += preco_medio

                relatorio.append({
                    "item": peca,
                    "preco_medio": preco_medio,
                    "abatido": preco_medio,
                    "links": links[:3]
                    "imagens": imagens[:3],
                    "precos": precos_texto[:3]
                })

            except Exception as e:
                logger.error(f"[ERROR] Erro inesperado ao buscar preços via Apify: {str(e)}")
                relatorio.append({"item": peca, "erro": f"Erro inesperado ao buscar preços: {str(e)}"})

    logger.info(f"[DEBUG] Relatório final: {relatorio}")
    return relatorio, total_abatimento
