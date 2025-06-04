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

# Configuração avançada de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("api.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger("calculadora_fipe")
logger.setLevel(logging.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("🚀 API Inicializada com sucesso!")

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
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")
WHEEL_SIZE_BASE = "https://api.wheel-size.com/v2"

cache = TTLCache(maxsize=100, ttl=3600)
peca_cache = TTLCache(maxsize=500, ttl=86400)
slug_cache = TTLCache(maxsize=100, ttl=86400)
wheel_cache = TTLCache(maxsize=50, ttl=86400)

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

@app.get("/marcas")
async def listar_marcas():
    try:
        logger.info("Chamando /marcas")
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/brands/1?token={TOKEN}"
            logger.debug(f"URL Invertexto: {url}")
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter marcas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter marcas: {str(e)}")

@app.get("/modelos/{marca_id}")
async def listar_modelos(marca_id: str):
    try:
        logger.info(f"Chamando /modelos para marca ID: {marca_id}")
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/models/{marca_id}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter modelos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")

@app.get("/anos/{fipe_code}")
async def listar_anos(fipe_code: str):
    try:
        logger.info(f"Chamando /anos para fipe_code: {fipe_code}")
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter anos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")

@app.get("/fipe")
async def consultar_fipe(fipe_code: str):
    try:
        logger.info(f"Consultando FIPE para código: {fipe_code}")
        cache_key = f"{fipe_code}"
        if cache_key in cache:
            logger.debug(f"Retornando FIPE do cache: {cache[cache_key]}")
            return {"valor_fipe": cache[cache_key]}

        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
            response = await client.get(url)
            response.raise_for_status()
            fipe_data = response.json()

        valores = fipe_data.get("years", [])
        if not valores:
            logger.warning(f"Valor FIPE não encontrado para {fipe_code}")
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        valor_mais_recente = valores[-1]["price"]
        cache[cache_key] = valor_mais_recente
        logger.info(f"Valor FIPE encontrado: {valor_mais_recente}")
        return {"valor_fipe": valor_mais_recente}
    except Exception as e:
        logger.error(f"Erro ao consultar FIPE: {str(e)}")
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

async def obter_medida_pneu_por_slug(marca: str, modelo: str, ano: int) -> str:
    cache_key = f"pneu_measure:{marca}:{modelo}:{ano}"
    logger.debug(f"Verificando cache de pneus para: {cache_key}")
    
    if cache_key in wheel_cache:
        logger.info(f"Retornando medida de pneu do cache: {wheel_cache[cache_key]}")
        return wheel_cache[cache_key]
    
    try:
        logger.info(f"Iniciando busca de pneu para {marca} {modelo} {ano}")
        
        modelo_base = modelo.split()[0]
        versao = " ".join(modelo.split()[1:]).lower()
        logger.debug(f"Modelo base: '{modelo_base}', Versão: '{versao}'")
        
        url = (
            f"{WHEEL_SIZE_BASE}/search/by_model/"
            f"?make={marca.strip().lower()}"
            f"&model={modelo_base.strip().lower()}"
            f"&year={ano}"
            f"&region=ladm"
            f"&user_key={WHEEL_SIZE_TOKEN}"
        )
        
        logger.info(f"Chamando Wheel-Size API: {url}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            logger.debug(f"Resposta Wheel-Size: status={response.status_code}")
            response.raise_for_status()
            
            data = response.json()
            logger.debug(f"Dados Wheel-Size recebidos: {json.dumps(data, indent=2)[:500]}...")
            
            if "data" not in data or not data["data"]:
                logger.warning(f"Wheel-Size: Nenhum dado encontrado para {marca} {modelo} {ano}")
                return ""
            
            logger.info(f"Wheel-Size: {len(data['data'])} veículos encontrados")
            
            target_vehicle = None
            
            for vehicle in data["data"]:
                modification = vehicle.get("modification", {})
                mod_name = modification.get("name", "").lower()
                logger.debug(f"Veículo: {vehicle.get('model',{}).get('name')} - Modificação: {mod_name}")
                
                if versao and versao in mod_name:
                    target_vehicle = vehicle
                    logger.info(f"Encontrada versão específica: {mod_name}")
                    break
                elif not target_vehicle:
                    target_vehicle = vehicle
            
            if not target_vehicle:
                logger.error("Nenhum veículo selecionado!")
                return ""
                
            logger.info(f"Veículo selecionado: {target_vehicle.get('model',{}).get('name')}")
            
            medidas_validas = []
            wheels = target_vehicle.get("wheels", [])
            logger.debug(f"Rodas encontradas: {len(wheels)}")
            
            for wheel in wheels:
                if wheel.get("is_stock") and "tire" in wheel:
                    tire = wheel["tire"]
                    logger.debug(f"Pneu encontrado: {tire}")
                    if all(key in tire for key in ["section_width", "aspect_ratio", "rim_diameter"]):
                        medida = (
                            f"{tire['section_width']}/"
                            f"{tire['aspect_ratio']} "
                            f"R{tire['rim_diameter']}"
                        )
                        logger.debug(f"Medida formatada: {medida}")
                        if medida not in medidas_validas:
                            medidas_validas.append(medida)
            
            logger.debug(f"Medidas válidas encontradas: {medidas_validas}")
            
            if not medidas_validas:
                logger.warning("Nenhuma medida de pneu válida encontrada")
                return ""
            
            medida_final = max(set(medidas_validas), key=medidas_validas.count) if medidas_validas else medidas_validas[0]
            wheel_cache[cache_key] = medida_final
            
            logger.info(f"Medida de pneu definida: {medida_final}")
            return medida_final
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP {e.response.status_code} na Wheel-Size: {e.request.url}")
    except Exception as e:
        logger.exception(f"Erro inesperado na Wheel-Size: {str(e)}")
    return ""

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
    logger.info("\n" + "="*80)
    logger.info("🏁 INICIANDO CONSULTA DE PEÇAS")
    logger.info(f"🔧 Parâmetros recebidos:")
    logger.info(f"  marca: {marca}")
    logger.info(f"  modelo: {modelo}")
    logger.info(f"  ano: {ano}")
    logger.info(f"  pecas: {pecas}")
    logger.info(f"  fipe_code: {fipe_code}")
    logger.info(f"  km: {km}")
    logger.info(f"  estado_interior: {estado_interior}")
    logger.info(f"  estado_exterior: {estado_exterior}")
    logger.info(f"  ipva_valor: {ipva_valor}")
    logger.info(f"  peca_extra: {peca_extra}")
    logger.info("="*80)
    
    try:
        from urllib.parse import unquote

        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        logger.debug(f"Parâmetros decodificados:")
        logger.debug(f"  marca: {marca}")
        logger.debug(f"  modelo: {modelo}")
        logger.debug(f"  pecas: {pecas}")
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        
        if peca_extra and peca_extra.strip():
            lista_pecas.extend([p.strip() for p in peca_extra.split(",") if p.strip()])
        
        logger.info(f"📋 Lista de peças processada: {lista_pecas}")
        logger.info(f"🔢 Número de peças: {len(lista_pecas)}")
        
        marca_nome = marca
        modelo_nome = modelo.replace("  ", " ").strip()
        ano_codigo = ano

        valor_fipe = 0
        if fipe_code:
            cache_key = f"{fipe_code}-{ano_codigo}"
            logger.debug(f"Chave de cache FIPE: {cache_key}")
            
            if cache_key in cache:
                valor_fipe = float(cache[cache_key])
                logger.info(f"💰 Valor FIPE do cache: R${valor_fipe:,.2f}")
            else:
                logger.info("🔄 Buscando valor FIPE na API")
                async with httpx.AsyncClient() as client:
                    url = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
                    logger.debug(f"URL FIPE: {url}")
                    response = await client.get(url)
                    response.raise_for_status()
                    fipe_data = response.json()

                valores = fipe_data.get("years", [])
                if not valores:
                    logger.warning("🚫 Valor FIPE não encontrado na resposta")
                    raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

                valor_encontrado = None
                for item in valores:
                    if item.get("year_id") == ano_codigo:
                        valor_encontrado = item.get("price")
                        break
                
                if not valor_encontrado and valores:
                    valor_encontrado = valores[0]["price"]
                    logger.warning("⚠️ Usando primeiro valor FIPE disponível")
                    
                if not valor_encontrado:
                    logger.error("❌ Valor FIPE não encontrado para o ano especificado")
                    raise HTTPException(status_code=404, detail="Valor FIPE não encontrado para o ano especificado")
                    
                valor_fipe = float(valor_encontrado)
                cache[cache_key] = valor_fipe
                logger.info(f"✅ Valor FIPE encontrado: R${valor_fipe:,.2f}")

        termos_pneu = ["pneu", "pneus", "pneuss", "pneuz", "roda", "rodas"]
        tem_pneu = any(
            any(termo in peca.lower() for termo in termos_pneu)
            for peca in lista_pecas
        )
        
        if tem_pneu:
            logger.info("🛞 Detectado termo de pneu na lista de peças")
            try:
                ano_int = int(ano_codigo.split('-')[0])
                logger.info(f"🔍 Buscando medida de pneu para {marca_nome} {modelo_nome} {ano_int}")
                
                medida_pneu = await obter_medida_pneu_por_slug(
                    marca=marca_nome, 
                    modelo=modelo_nome, 
                    ano=ano_int)
                
                if medida_pneu:
                    logger.info(f"✅ Medida de pneu obtida: {medida_pneu}")
                    nova_lista = []
                    for peca in lista_pecas:
                        if any(termo in peca.lower() for termo in termos_pneu):
                            qtd_match = re.search(r'\d+', peca)
                            qtd = qtd_match.group() if qtd_match else "4"
                            
                            if int(qtd) < 2:
                                qtd = "4"
                                logger.warning("⚠️ Quantidade de pneus ajustada para 4 (mínimo não atendido)")
                            
                            nova_peca = f"{qtd} pneus {medida_pneu}"
                            nova_lista.append(nova_peca)
                            logger.debug(f"🔀 Substituído: '{peca}' → '{nova_peca}'")
                        else:
                            nova_lista.append(peca)
                    lista_pecas = nova_lista
                    logger.info(f"📝 Nova lista de peças: {lista_pecas}")
                else:
                    logger.warning("⚠️ Medida de pneu não encontrada. Mantendo termos originais.")
            except Exception as e:
                logger.error(f"❌ Erro crítico na substituição de pneus: {str(e)}")
        else:
            logger.info("⏭️ Nenhum termo de pneu detectado. Pulando substituição.")

        logger.info("🔍 Iniciando busca de preços para peças...")
        relatorio, total_pecas = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_codigo.split('-')[0], lista_pecas
        )
        logger.info(f"✅ Busca de peças concluída. Total em peças: R${total_pecas:,.2f}")
        
        desconto_estado = calcular_desconto_estado(estado_interior, estado_exterior, valor_fipe)
        desconto_km = calcular_desconto_km(km, valor_fipe, ano_codigo.split('-')[0])
        ipva_desconto = ipva_valor
        
        logger.debug(f"🔢 Descontos calculados:")
        logger.debug(f"  Estado: R${desconto_estado:,.2f}")
        logger.debug(f"  KM: R${desconto_km:,.2f}")
        logger.debug(f"  IPVA: R${ipva_desconto:,.2f}")
        logger.debug(f"  Peças: R${total_pecas:,.2f}")
        
        total_descontos = desconto_estado + desconto_km + ipva_desconto + total_pecas
        valor_final = valor_fipe - total_descontos

        logger.info("📊 Resultado final:")
        logger.info(f"  Valor FIPE: R${valor_fipe:,.2f}")
        logger.info(f"  Total descontado: R${total_descontos:,.2f}")
        logger.info(f"  Valor final: R${valor_final:,.2f}")
        
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
        logger.exception(f"❌ ERRO FATAL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro na consulta de peças: {str(e)}")

@app.get("/cidades/{uf}")
async def get_cidades_por_estado(uf: str):
    try:
        logger.info(f"Buscando cidades para UF: {uf}")
        with open(ARQUIVO_CIDADES, "r", encoding="utf-8") as f:
            dados = json.load(f)
        for estado in dados["estados"]:
            if estado["sigla"].upper() == uf.upper():
                return estado["cidades"]
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar cidades: {str(e)}")
        return {"erro": f"Erro ao carregar cidades: {str(e)}"}

async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    logger.info(f"🔍 Buscando preços para {len(pecas_selecionadas)} peças")
    relatorio = []
    total_abatimento = 0

    async def processar_peca(peca):
        cache_key = f"{marca_nome}-{modelo_nome}-{ano_nome}-{peca}"
        logger.debug(f"Processando peça: {peca}")
        
        if cache_key in peca_cache:
            logger.debug(f"Retornando peça do cache: {peca}")
            return {"sucesso": True, "peca": peca, "dados": peca_cache[cache_key]}
        
        termo_busca = f"{peca.strip()} {marca_nome} {modelo_nome} {ano_nome}".replace("  ", " ").strip()
        payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
        logger.debug(f"Payload para Apify: {payload}")
        
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
                logger.debug(f"Chamando Apify: {api_url}")
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                dados_completos = response.json()
                logger.debug(f"Resposta Apify recebida: {len(dados_completos)} itens")
                
                peca_cache[cache_key] = dados_completos
                return {"sucesso": True, "peca": peca, "dados": dados_completos}
        except Exception as e:
            logger.error(f"Erro ao buscar peça: {str(e)}")
            return {"sucesso": False, "peca": peca, "erro": str(e)}

    tasks = [processar_peca(peca) for peca in pecas_selecionadas]
    logger.info(f"🔄 Iniciando busca assíncrona para {len(tasks)} peças")
    resultados = await asyncio.gather(*tasks)
    logger.info("✅ Busca assíncrona concluída")
    
    for resultado in resultados:
        if not resultado["sucesso"]:
            logger.warning(f"❌ Falha na peça: {resultado['peca']} - {resultado['erro']}")
            relatorio.append({"item": resultado["peca"], "erro": resultado["erro"]})
            continue

        dados = resultado["dados"]
        if not dados:
            logger.warning(f"⚠️ Nenhum dado para: {resultado['peca']}")
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
            logger.warning(f"⚠️ Nenhum preço válido para: {resultado['peca']}")
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
        logger.info(f"🔍 Buscando pneu original para {marca}/{modelo}/{ano}")
        medida_pneu = await obter_medida_pneu_por_slug(marca, modelo, ano)
        
        if medida_pneu:
            logger.info(f"✅ Pneu encontrado: {medida_pneu}")
            return {"pneu_original": medida_pneu}
        else:
            logger.error(f"❌ Pneu não encontrado: {marca}/{modelo}/{ano}")
            raise HTTPException(
                status_code=404,
                detail="Medida do pneu não encontrada para o modelo especificado"
            )
            
    except Exception as e:
        logger.exception(f"❌ Erro fatal em /pneu-original: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Erro interno ao processar solicitação"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
