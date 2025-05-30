from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from cachetools import TTLCache
import httpx
import logging
import os
import asyncio
from datetime import datetime
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_CIDADES = os.path.join(BASE_DIR, "cidades_por_estado.json")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
WHEEL_SIZE_URL = "https://api.wheel-size.com/v2/search/by_model/"
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")
APIFY_ACTOR = os.getenv("APIFY_ACTOR")
cache = TTLCache(maxsize=100, ttl=3600)  # Cache para FIPE
peca_cache = TTLCache(maxsize=500, ttl=86400)  # Cache para peças (24 horas)

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

def calcular_desconto_estado(interior, exterior, valor_fipe):
    desconto = 0
    
    if interior == "otimo":
        desconto += 0
    elif interior == "bom":
        desconto += valor_fipe * 0.01
    elif interior == "regular":
        desconto += valor_fipe * 0.03
    elif interior == "ruim":
        desconto += valor_fipe * 0.05
    
    if exterior == "otimo":
        desconto += 0
    elif exterior == "bom":
        desconto += valor_fipe * 0.01
    elif exterior == "regular":
        desconto += valor_fipe * 0.02
    elif exterior == "ruim":
        desconto += valor_fipe * 0.03
    
    return desconto

def calcular_desconto_km(km, valor_fipe, ano):
    try:
        ano_atual = datetime.now().year
        idade = ano_atual - int(ano)
        km_medio_esperado = idade * 15000
        
        if km > km_medio_esperado:
            excedente = km - km_medio_esperado
            return valor_fipe * (excedente / 1000) * 0.005
        return 0
    except:
        return 0

async def get_tire_specs(marca_nome, modelo_nome, ano_nome):
    try:
        async with httpx.AsyncClient() as client:
            params = {
                "make": marca_nome.lower(),
                "model": modelo_nome.lower(),
                "year": ano_nome,
                "key": WHEEL_SIZE_TOKEN
            }
            response = await client.get(WHEEL_SIZE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if not data or not data.get("data", []):
                return None
            
            vehicle = data["data"][0]
            tire_size = vehicle.get("tire", {}).get("size", None)
            if not tire_size:
                return None
                
            return tire_size
    except Exception as e:
        logger.error(f"Erro ao consultar Wheel Size API: {str(e)}")
        return None

@app.get("/pecas")
async def buscar_precos_pecas(
    marca: str, 
    modelo: str, 
    ano: str,
    pecas: str = Query(""), 
    fipe_code: str = Query(None), 
    km: float = Query(0.0),
    estado_interior: str = Query(""), 
    estado_exterior: str = Query(""),
    ipva_valor: float = Query(0.0),
    peca_extra: str = Query("")
):
    try:
        from urllib.parse import unquote

        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        
        if peca_extra and peca_extra.strip():
            lista_pecas.extend([p.strip() for p in peca_extra.split(",") if p.strip()])
            
        marca_nome = marca
        modelo_nome = modelo.replace("  ", " ").strip()
        ano_codigo = ano

        valor_fipe = 0
        if fipe_code:
            cache_key = f"{fipe_code}-{ano_codigo}"
            
            if cache_key in cache:
                valor_fipe = float(cache[cache_key])
            else:
                async with httpx.AsyncClient() as client:
                    url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
                    response = await client.get(url)
                    response.raise_for_status()
                    fipe_data = response.json()

                valores = fipe_data.get("years", [])
                if not valores:
                    raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

                valor_encontrado = None
                for item in valores:
                    if item.get("year_id") == ano_codigo:
                        valor_encontrado = item.get("price")
                        break
                
                if not valor_encontrado and valores:
                    valor_encontrado = valores[0]["price"]
                    
                if not valor_encontrado:
                    raise HTTPException(status_code=404, detail="Valor FIPE não encontrado para o ano especificado")
                    
                valor_fipe = float(valor_encontrado)
                cache[cache_key] = valor_fipe

        relatorio, total_pecas = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_codigo.split('-')[0], lista_pecas
        )
        
        desconto_estado = calcular_desconto_estado(estado_interior, estado_exterior, valor_fipe)
        desconto_km = calcular_desconto_km(km, valor_fipe, ano_codigo.split('-')[0])
        ipva_desconto = ipva_valor
        
        total_descontos = desconto_estado + desconto_km + ipva_desconto + total_pecas
        
        valor_final = valor_fipe - total_descontos

        return {
            "valor_fipe": valor_fipe,
            "total_abatido": total_descontos,
            "valor_final": valor_final,
            "desconto_estado": desconto_estado,
            "ipva_desconto": ipva_desconto,
            "km_desconto": {
                "valor": desconto_km,
                "percentual": f"{(desconto_km / valor_fipe * 100):.2f}%" if valor_fipe > 0 else "0%"
            },
            "relatorio_detalhado": relatorio,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na consulta de peças: {str(e)}")

@app.get("/cidades/{uf}")
async def get_cidades_por_estado(uf: str):
    try:
        with open(ARQUIVO_CIDADES, "r", encoding="utf-8") as f:
            dados = json.load(f)
        for estado in dados["estados"]:
            if estado["sigla"].upper() == uf.upper():
                return estado["cidades"]
        return []
    except Exception as e:
        return {"erro": f"Erro ao carregar cidades: {str(e)}"}

async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    relatorio = []
    total_abatimento = 0

    async def processar_peca(peca):
        cache_key = f"{marca_nome}-{modelo_nome}-{ano_nome}-{peca}"
        if cache_key in peca_cache:
            return {"sucesso": True, "peca": peca, "dados": peca_cache[cache_key], "tireSize": peca_cache[cache_key].get("tireSize", None)}
        
        tire_size = None
        if peca.lower().startswith("pneu") or peca.lower().startswith("pneus"):
            tire_size = await get_tire_specs(marca_nome, modelo_nome, ano_nome)
            if not tire_size:
                return {"sucesso": False, "peca": peca, "erro": "Não foi possível obter as dimensões do pneu."}
            termo_busca = f"{peca} {tire_size}".strip()
        else:
            termo_busca = f"{peca.strip()} {marca_nome} {modelo_nome} {ano_nome}".replace("  ", " ").strip()
        
        payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
        
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                dados_completos = response.json()
                
                if tire_size:
                    dados_completos["tireSize"] = tire_size
                peca_cache[cache_key] = dados_completos
                return {"sucesso": True, "peca": peca, "dados": dados_completos, "tireSize": tire_size}
                
        except Exception as e:
            return {"sucesso": False, "peca": peca, "erro": str(e)}
    
    tasks = [processar_peca(peca) for peca in pecas_selecionadas]
    resultados = await asyncio.gather(*tasks)
    
    for resultado in resultados:
        if not resultado["sucesso"]:
            relatorio.append({"item": resultado["peca"], "erro": resultado["erro"]})
            continue
            
        dados = resultado["dados"]
        if not dados:
            relatorio.append({"item": resultado["peca"], "erro": "Nenhum resultado encontrado."})
            continue

        precos = []
        links = []
        imagens = []
        nomes = []
        precos_texto = []

        modelo_keywords = modelo_nome.lower().split()[:2] if not resultado["peca"].lower().startswith("pneu") else []

        for item in dados[:5]:
            titulo = item.get("eTituloProduto", "").lower()
            
            if modelo_keywords and not any(kw in titulo for kw in modelo_keywords):
                continue

            preco_str = item.get("novoPreco")
            if not preco_str:
                continue

            try:
                preco = float(str(preco_str).replace(".", "").replace(",", "."))
                precos.append(preco)
                links.append(item.get("zProdutoLink", ""))
                imagens.append(item.get("imagemLink", ""))
                nomes.append(item.get("eTituloProduto", ""))
                precos_texto.append(preco_str)
            except Exception:
                continue

        if not precos:
            relatorio.append({"item": resultado["peca"], "erro": "Nenhum preço válido encontrado."})
            continue

        preco_medio = round(sum(precos) / len(precos), 2)
        total_abatimento += preco_medio

        relatorio_item = {
            "item": resultado["peca"],
            "preco_medio": preco_medio,
            "abatido": preco_medio,
            "links": links[:3],
            "imagens": imagens[:3],
            "nomes": nomes[:3],
            "precos": precos_texto[:3]
        }
        if resultado["tireSize"]:
            relatorio_item["tireSize"] = resultado["tireSize"]

        relatorio.append(relatorio_item)

    return relatorio, total_abatimento
