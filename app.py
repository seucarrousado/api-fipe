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
import re
import unicodedata

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
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR = os.getenv("APIFY_ACTOR")
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")  # Token da Wheel-Size API
WHEEL_SIZE_BASE = "https://api.wheel-size.com/v2"  # Base URL da Wheel-Size

cache = TTLCache(maxsize=100, ttl=3600)  # Cache para FIPE
peca_cache = TTLCache(maxsize=500, ttl=86400)  # Cache para peças (24 horas)
slug_cache = TTLCache(maxsize=100, ttl=86400)  # Cache para slugs (24 horas)
wheel_cache = TTLCache(maxsize=50, ttl=86400)  # Cache para medidas de pneus (24 horas)

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

def normalizar_slug(texto: str) -> str:
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    texto = texto.lower().strip()
    texto = re.sub(r'[\s_]+', '-', texto)
    texto = re.sub(r'[^a-z0-9\-]', '', texto)
    return texto

async def get_make_slug(make_name: str) -> str:
    cache_key = f"make_slug:{make_name}"
    if cache_key in slug_cache:
        return slug_cache[cache_key]
    
    try:
        url = f"{WHEEL_SIZE_BASE}/makes/?user_key={WHEEL_SIZE_TOKEN}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            makes = response.json()
            
            for make in makes.get("data", []):
                if normalizar_slug(make['name']) == normalizar_slug(make_name):
                    slug_encontrado = make['slug']
                    logger.info(f"[WHEEL] Marca: {make_name} → Slug retornado: {slug_encontrado}")
                    slug_cache[cache_key] = slug_encontrado
                    return slug_encontrado
        
        # Fallback: normalização direta
        slug_normalizado = normalizar_slug(make_name)
        slug_cache[cache_key] = slug_normalizado
        return slug_normalizado
    except Exception as e:
        logger.error(f"Erro ao buscar slug da marca {make_name}: {str(e)}")
        return normalizar_slug(make_name)

async def get_model_slug(make_slug: str, model_name: str) -> str:
    cache_key = f"model_slug:{make_slug}:{model_name}"
    if cache_key in slug_cache:
        return slug_cache[cache_key]
    
    try:
        url = f"{WHEEL_SIZE_BASE}/models/?make={make_slug}&user_key={WHEEL_SIZE_TOKEN}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
            models = body.get("data", [])  # Corrigido aqui

        for model in models:
            if normalizar_slug(model['name']) == normalizar_slug(model_name):
                slug_cache[cache_key] = model['slug']
                return model['slug']
        
        slug_normalizado = normalizar_slug(model_name)
        slug_cache[cache_key] = slug_normalizado
        return slug_normalizado
    except Exception as e:
        logger.error(f"Erro ao buscar slug do modelo {model_name}: {str(e)}")
        return normalizar_slug(model_name)

async def obter_medida_pneu_por_slug(marca: str, modelo: str, ano: int) -> str:
    cache_key = f"pneu_measure:{marca}:{modelo}:{ano}"
    if cache_key in wheel_cache:
        return wheel_cache[cache_key]

    try:
        make_slug = await get_make_slug(marca)

        # Separar nome do modelo (ex: "argo") para slug
        modelo_slug = modelo.split()[0].strip().lower()
        model_slug = await get_model_slug(make_slug, modelo_slug)

        if not make_slug or not model_slug:
            logger.error(f"[WHEEL] Slugs não encontrados: marca={marca}->{make_slug}, modelo={modelo}->{model_slug}")
            return ""

        # Buscar modificações disponíveis para este modelo e ano
        mod_url = f"{WHEEL_SIZE_BASE}/modifications/?make={make_slug}&model={model_slug}&year={ano}&region=ladm&user_key={WHEEL_SIZE_TOKEN}"
        async with httpx.AsyncClient() as client:
            mod_response = await client.get(mod_url)
            mod_response.raise_for_status()
            modifications = mod_response.json()

            if not isinstance(modifications, list) or not modifications:
                logger.error(f"[WHEEL] Nenhuma modificação para {make_slug}/{model_slug}/{ano}")
                return ""

            logger.info(f"[WHEEL] {len(modifications)} modificações encontradas para {make_slug}/{model_slug}/{ano}")
            for i, mod in enumerate(modifications):
                nome = mod.get("name", "")
                motor = mod.get("engine", {}).get("capacity", "")
                combustivel = mod.get("engine", {}).get("fuel", "")
                slug = mod.get("slug", "")
                logger.info(f"[MOD-{i+1}] Nome: {nome} | Motor: {motor} | Combustível: {combustivel} | Slug: {slug}")


            modelo_normalizado = normalizar_slug(modelo)
            mod_slug = ""

            # Buscar modificação mais compatível com o nome completo
            for mod in modifications:
                nome_mod = mod.get("name", "").lower()
                motor = mod.get("engine", {}).get("capacity", "")
                combustivel = mod.get("engine", {}).get("fuel", "")
                slug_temp = mod.get("slug", "")

                termos = [nome_mod, motor.replace('.', ''), combustivel]
                if any(term in modelo_normalizado for term in termos if term):
                    mod_slug = slug_temp
                    break

            if not mod_slug:
                mod_slug = modifications[0].get("slug", "")
                logger.warning(f"[WHEEL] Nenhuma modificação 100% compatível encontrada, usando slug: {mod_slug}")

            # Buscar medida de pneu com base na modificação
            detail_url = f"{WHEEL_SIZE_BASE}/search/by_model/?make={make_slug}&model={model_slug}&year={ano}&modification={mod_slug}&region=ladm&user_key={WHEEL_SIZE_TOKEN}"
            detail_response = await client.get(detail_url)
            detail_response.raise_for_status()
            vehicle_data = detail_response.json()

            data_list = vehicle_data.get("data")
            if not isinstance(data_list, list):
                return ""

            for mod_data in data_list:
                for wheel in mod_data.get("wheels", []):
                    if wheel.get("is_stock") and "tire" in wheel:
                        tire = wheel["tire"]
                        width = tire.get("section_width")
                        aspect = tire.get("aspect_ratio")
                        rim = tire.get("rim_diameter")

                        if all([width, aspect, rim]):
                            medida = f"{width}/{aspect} R{rim}"
                            wheel_cache[cache_key] = medida
                            return medida

        logger.warning(f"[WHEEL] Nenhuma medida encontrada para {marca}/{modelo}/{ano}")
        return ""

    except Exception as e:
        logger.error(f"[WHEEL] Erro: {str(e)}")
        return ""



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
    
    # Desconto baseado no estado do interior
    if interior == "otimo":
        desconto += 0
    elif interior == "bom":
        desconto += valor_fipe * 0.01
    elif interior == "regular":
        desconto += valor_fipe * 0.03
    elif interior == "ruim":
        desconto += valor_fipe * 0.05
    
    # Desconto baseado no estado do exterior
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

@app.get("/pecas")
async def buscar_precos_pecas(
    marca: str, 
    modelo: str, 
    ano: str,  # Agora recebe o código completo do ano (ex: "1995-1")
    pecas: str = Query(""), 
    fipe_code: str = Query(None), 
    km: float = Query(0.0),
    estado_interior: str = Query(""), 
    estado_exterior: str = Query(""),
    ipva_valor: float = Query(0.0),
    peca_extra: str = Query("")  # Novo parâmetro para peças extras
):
    try:
        from urllib.parse import unquote

        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        
        # Adicionar peças extras se existirem
        if peca_extra and peca_extra.strip():
            lista_pecas.extend([p.strip() for p in peca_extra.split(",") if p.strip()])
            
        marca_nome = marca
        modelo_nome = modelo.replace("  ", " ").strip()
        ano_codigo = ano  # Usamos o código completo do ano

        valor_fipe = 0
        if fipe_code:
            # Criar chave de cache única com fipe_code + ano_codigo
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

                # Encontrar o valor específico para o ano_codigo
                valor_encontrado = None
                for item in valores:
                    if item.get("year_id") == ano_codigo:
                        valor_encontrado = item.get("price")
                        break
                
                # Se não encontrar, usar o primeiro valor disponível
                if not valor_encontrado and valores:
                    valor_encontrado = valores[0]["price"]
                    
                if not valor_encontrado:
                    raise HTTPException(status_code=404, detail="Valor FIPE não encontrado para o ano especificado")
                    
                valor_fipe = float(valor_encontrado)
                cache[cache_key] = valor_fipe

        # Substituir "pneu" por medida real consultada via Wheel-Size
        logger.info(f"[DEBUG] Lista de peças recebida: {lista_pecas}")
        if True:
            logger.info(f"[PNEU] Iniciando substituição de pneus para {marca_nome} {modelo_nome} {ano_codigo}")
            
            try:
                ano_int = int(ano_codigo.split('-')[0])
            except:
                ano_int = datetime.now().year
                logger.warning(f"[PNEU] Falha ao converter ano, usando {ano_int} como fallback")
            
            try:
                modelo_nome_limpo = modelo_nome.split()[0].strip().lower()  # ou use a função limpar_modelo() se quiser algo mais robusto
                medida_pneu = await obter_medida_pneu_por_slug(
                    marca=marca_nome, 
                    modelo=modelo_nome_limpo, 
                    ano=ano_int)
                
                if medida_pneu:
                    logger.info(f"[PNEU] Medida obtida: {medida_pneu}")
                    nova_lista = []
                    for peca in lista_pecas:
                        if "pneu" in peca.lower():
                            # Detecta quantidade (2 ou 4 pneus)
                            qtd = "4" if any(k in peca.lower() for k in ["4", "quatro", "jogo"]) else "2"
                            nova_lista.append(f"{qtd} pneus {medida_pneu}")
                        else:
                            nova_lista.append(peca)
                    lista_pecas = nova_lista
                else:
                    logger.warning("[PNEU] Medida não encontrada. Mantendo termo original.")
            except Exception as e:
                logger.error(f"[PNEU] Erro crítico: {str(e)}")

        relatorio, total_pecas = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_codigo.split('-')[0], lista_pecas
        )
        
        # Calcular todos os descontos
        desconto_estado = calcular_desconto_estado(estado_interior, estado_exterior, valor_fipe)
        desconto_km = calcular_desconto_km(km, valor_fipe, ano_codigo.split('-')[0])
        ipva_desconto = ipva_valor
        
        # SOMA de todos os descontos
        total_descontos = desconto_estado + desconto_km + ipva_desconto + total_pecas
        
        # Calcular valor final CORRETAMENTE
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
            return {"sucesso": True, "peca": peca, "dados": peca_cache[cache_key]}
        
        termo_busca = f"{peca.strip()} {marca_nome} {modelo_nome} {ano_nome}".replace("  ", " ").strip()
        payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
        
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                dados_completos = response.json()
                
                peca_cache[cache_key] = dados_completos
                return {"sucesso": True, "peca": peca, "dados": dados_completos}
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

        termo_minusculo = resultado["peca"].lower()
        is_pneu_com_medida = "pneu" in termo_minusculo and any(c.isdigit() for c in termo_minusculo)
        modelo_keywords = [] if is_pneu_com_medida else modelo_nome.lower().split()[:2]

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

        relatorio.append({
            "item": resultado["peca"],
            "preco_medio": preco_medio,
            "abatido": preco_medio,
            "links": links[:3],
            "imagens": imagens[:3],
            "nomes": nomes[:3],
            "precos": precos_texto[:3]
        })

    return relatorio, total_abatimento

@app.get("/pneu-original")
async def get_pneu_original(
    marca: str = Query(..., example="fiat"),
    modelo: str = Query(..., example="argo"),
    ano: int = Query(..., example=2022)
):
    try:
        logger.info(f"[PNEU-EP] Buscando pneu para {marca}/{modelo}/{ano}")
        medida_pneu = await obter_medida_pneu_por_slug(marca, modelo, ano)
        
        if medida_pneu:
            return {"pneu_original": medida_pneu}
        else:
            logger.error(f"[PNEU-EP] Não encontrado: {marca}/{modelo}/{ano}")
            raise HTTPException(
                status_code=404,
                detail="Medida do pneu não encontrada para o modelo especificado"
            )
            
    except Exception as e:
        logger.error(f"[PNEU-EP] Erro fatal: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao processar solicitação"
        )
