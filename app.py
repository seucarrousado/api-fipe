from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator
from cachetools import TTLCache
import httpx
import logging
import os
import asyncio
from datetime import datetime
import re
import unidecode  # Adicionado para normalização de textos

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Nova pasta para armazenar logs
PASTA_RELATORIOS = os.path.join(BASE_DIR, "relatorios")
os.makedirs(PASTA_RELATORIOS, exist_ok=True)

# Caminho completo para o log
LOG_CAMINHO = os.path.join(PASTA_RELATORIOS, "log_pecas.csv")

ARQUIVO_CIDADES = os.path.join(BASE_DIR, "cidades_por_estado.json")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todos para teste, ajuste em produção
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
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")  # Adicionado token da Wheel Size
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

# Função para criar slugs
def criar_slug(texto):
    """Cria um slug consistente para comparação de strings"""
    # Remove acentos
    texto = unidecode.unidecode(texto)
    # Converte para minúsculas
    texto = texto.lower()
    # Remove caracteres especiais e substitui por hífens
    texto = re.sub(r'[^a-z0-9]+', '-', texto)
    # Remove hífens extras no início/fim
    return texto.strip('-')

@app.get("/wheel-size")
async def buscar_medida_pneu(marca: str, modelo: str, ano_id: str):
    """
    Busca a medida do pneu na API da Wheel Size.

    Parâmetros:
        marca: texto (ex: "Fiat")
        modelo: texto completo com versão (ex: "Argo 1.0 6V Flex")
        ano_id: string no formato "AAAA-X" (ex: "2022-1")
    """
    logger.info(f"[WS] Requisição recebida: marca={marca}, modelo={modelo}, ano_id={ano_id}")

    try:
        ano_base = ano_id.split('-')[0]
    except Exception as e:
        logger.error(f"[WS] Erro ao extrair ano base de {ano_id}: {e}")
        return {"erro": "Formato de ano inválido"}

    # Versão (trim) extraída diretamente do modelo completo recebido
    trim_nome = modelo.lower().strip()
    logger.info(f"[WS] Versão (trim) recebida do frontend: {trim_nome}")

    marca_slug = criar_slug(marca)
    modelo_slug = criar_slug(modelo.split()[0])  # modelo base

    url_wheel = (
        f"https://api.wheel-size.com/v2/search/by_model/"
        f"?make={marca_slug}"
        f"&model={modelo_slug}"
        f"&year={ano_base}"
        f"®ion=ladm"
        f"&ordering=trim"
        f"&user_key={WHEEL_SIZE_TOKEN}"
    )
    logger.info(f"[WS] URL da Wheel-Size: {url_wheel}")

    try:
        async with httpx.AsyncClient() as client:
            response_wheel = await client.get(url_wheel)
            response_wheel.raise_for_status()
            data = response_wheel.json()

        logger.info(f"[WS] Total de resultados da Wheel-Size: {len(data.get('data', []))}")    

        veiculo_correto = None
        melhor_match = None
        melhor_pontuacao = 0

        if data.get('data'):
            for veiculo in data['data']:
                trim_atual = veiculo.get('trim', '').lower()
                logger.info(f"[WS] Comparando trim: {trim_atual} vs {trim_nome}")

                if trim_nome and trim_atual == trim_nome:
                    veiculo_correto = veiculo
                    logger.info(f"[WS] Trim exato encontrado.")
                    break

                if trim_nome:
                    tokens_nome = set(trim_nome.split())
                    tokens_atual = set(trim_atual.split())
                    pontos = len(tokens_nome & tokens_atual)

                    if pontos > melhor_pontuacao:
                        melhor_pontuacao = pontos
                        melhor_match = veiculo

        if not veiculo_correto:
            veiculo_correto = melhor_match if melhor_match else (data['data'][0] if data['data'] else None)
            logger.info(f"[WS] Usando melhor match ou fallback.")

        if veiculo_correto and veiculo_correto.get('wheels'):
            roda = veiculo_correto['wheels'][0]['front']
            medida = roda.get('tire_full') or f"{roda['section_width']}/{roda['aspect_ratio']} R{roda['rim_diameter']}"

            return {
                "medida": medida.replace('R', ' R'),
                "debug": {
                    "trim_encontrada": veiculo_correto.get('trim'),
                    "trim_buscada": trim_nome,
                    "match_exato": veiculo_correto.get('trim', '').lower() == trim_nome
                }
            }

        logger.warning(f"[WS] Nenhuma medida de roda encontrada no veículo.")
        return {"erro": "Medida não encontrada"}

    except Exception as e:
        logger.error(f"[WS] Erro geral ao buscar medida do pneu: {e}")
        return {"erro": f"Falha na API Wheel Size: {str(e)}"}

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
    ano: str,  # Recebe o código completo do ano (ex: "1995-1")
    pecas: str = Query(""), 
    fipe_code: str = Query(None), 
    km: float = Query(0.0),
    estado_interior: str = Query(""), 
    estado_exterior: str = Query(""),
    ipva_valor: float = Query(0.0)
):
    logger.info(f"[PECAS] Endpoint /pecas chamado com: marca={marca}, modelo={modelo}, ano={ano}, pecas={pecas}")
    try:
        from urllib.parse import unquote

        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
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

        logger.info(f"[PECAS] Buscando preços para peças: {lista_pecas}")
        relatorio, total_pecas = await buscar_precos_e_gerar_relatorio(
            marca_nome, modelo_nome, ano_codigo.split('-')[0], lista_pecas
        )
        logger.info(f"[PECAS] Relatório de peças obtido: {len(relatorio)} itens")
        
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
        logger.error(f"[PECAS] Erro na consulta de peças: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro na consulta de peças: {str(e)}")
        
@app.get("/cidades/{uf}")
async def get_cidades_por_estado(uf: str):
    import os
    import json
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
    logger = logging.getLogger("calculadora_fipe")
    api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"

    logger.info(f"[APIFY] Iniciando busca para {len(pecas_selecionadas)} peças")
    logger.info(f"[APIFY] URL da API: {api_url}")

    async with httpx.AsyncClient(timeout=60) as client:
        async def fetch_peca(peca):
            termo_busca = peca.strip() if peca.lower().startswith("kit pneus") else f"{peca} {marca_nome} {modelo_nome} {ano_nome}"
            payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
            try:
                logger.info(f"[APIFY] Buscando peça: '{peca}' com termo: '{termo_busca}'")
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                dados_completos = response.json()
                
                # LOG ESTRATÉGICO: Resposta completa da API
                logger.info(f"[APIFY] Resposta para '{peca}': Status {response.status_code}, {len(dados_completos)} resultados")
                
                if not isinstance(dados_completos, list) or not dados_completos:
                    logger.warning(f"[APIFY] Sem resultados válidos para: {peca}")
                    return {"item": peca, "erro": "Sem resultados válidos"}

                precos, links, imagens, nomes, precos_texto = [], [], [], [], []

                for item in dados_completos[:5]:
                    # Log de debug para cada item retornado
                    logger.debug(f"[APIFY] Item: {item.get('eTituloProduto')} | Preço: {item.get('novoPreco')}")

                    if not peca.strip().lower().startswith("kit pneus"):
                        titulo = item.get("eTituloProduto", "").lower()
                        modelo_base = modelo_nome.lower().split()[0]
                        if modelo_base not in titulo:
                            continue

                    preco_str = item.get("novoPreco")
                    if not preco_str:
                        continue
                    preco = float(str(preco_str).replace(".", "").replace(",", "."))
                    precos.append(preco)
                    links.append(item.get("zProdutoLink", ""))
                    imagens.append(item.get("imagemLink", ""))
                    nomes.append(item.get("eTituloProduto", ""))
                    precos_texto.append(preco_str)

                if not precos:
                    logger.warning(f"[APIFY] Nenhum preço válido para: {peca}")
                    return {"item": peca, "erro": "Nenhum preço válido"}

                preco_medio = round(sum(precos) / len(precos), 2)
                logger.info(f"[APIFY] Preço médio para {peca}: R${preco_medio}")
                                           
                from csv import writer

                with open(LOG_CAMINHO, "a", encoding="utf-8", newline="") as f:
                    log_writer = writer(f)
                    log_writer.writerow([
                        datetime.now().isoformat(),
                        marca_nome,
                        modelo_nome,
                        ano_nome,
                        peca
                    ])
                return {
                    "item": peca,
                    "preco_medio": preco_medio,
                    "abatido": preco_medio,
                    "links": links[:3],
                    "imagens": imagens[:3],
                    "nomes": nomes[:3],
                    "precos": precos_texto[:3]
                }
            except Exception as e:
                logger.error(f"[APIFY ERROR] Falha ao buscar '{peca}': {str(e)}")
                return {"item": peca, "erro": f"Falha: {str(e)}"}

        # Executa todas simultaneamente
        tasks = [fetch_peca(peca) for peca in pecas_selecionadas if peca]
        resultados = await asyncio.gather(*tasks)

        # Log de resumo das peças processadas
        sucessos = sum(1 for r in resultados if 'preco_medio' in r)
        falhas = sum(1 for r in resultados if 'erro' in r)
        logger.info(f"[APIFY] Resumo: {sucessos} peças com sucesso, {falhas} falhas")

        # Soma total
        total_abatimento = sum(item.get("abatido", 0) for item in resultados if isinstance(item, dict))
        logger.info(f"[APIFY] Total abatido por peças: R${total_abatimento}")
        return resultados, total_abatimento

from fastapi.responses import FileResponse

@app.get("/exportar-logs")
async def exportar_log_de_pecas():
    """
    Endpoint para baixar o arquivo log_pecas.csv com as peças pesquisadas.
    """
    try:
        if not os.path.exists(LOG_CAMINHO):
            raise HTTPException(status_code=404, detail="Arquivo de log não encontrado.")

        return FileResponse(
            LOG_CAMINHO,
            filename="log_pecas.csv",
            media_type="text/csv"
        )
    except Exception as e:
        logger.error(f"[EXPORTAÇÃO] Erro ao exportar log: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao exportar log: {str(e)}")
