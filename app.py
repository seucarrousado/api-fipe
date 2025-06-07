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
    Busca a medida do pneu na API da Wheel Size
    """
    logger.info(f"[WS] Requisição recebida: marca={marca}, modelo={modelo}, ano_id={ano_id}")

    Parâmetros:
        marca: texto (ex: "Fiat")
        modelo: texto (ex: "Argo Drive")
        ano_id: string no formato "AAAA-X" (ex: "2022-1")
    """
    # Extrair apenas o ano base (AAAA) do ano_id
    try:
        ano_base = ano_id.split('-')[0]  # Pega apenas o ano (ex: "2022")
    except:
        logger.error(f"[WS] Erro ao extrair ano base de {ano_id}: {e}")
        return {"erro": "Formato de ano inválido"}

    # Obter nome completo da trim da API FIPE
    async with httpx.AsyncClient() as client:
        # 1. Buscar todas as versões do veículo
        fipe_code = f"{criar_slug(marca)}-{criar_slug(modelo)}-{ano_base}"
        url_fipe = f"{BASE_URL}/years/{fipe_code}?token={TOKEN}"
        logger.info(f"[WS] Buscando nome da versão FIPE: {url_fipe}")
        response_fipe = await client.get(url_fipe)
        
        if response_fipe.status_code != 200:
            logger.warning(f"[WS] Resposta FIPE inesperada: {response_fipe.status_code} - {response_fipe.text}")
            return {"erro": "Falha ao buscar dados FIPE"}
        
        anos_data = response_fipe.json().get("years", [])
        
        # 2. Encontrar o nome da trim pelo ID
        trim_nome = ""
        for item in anos_data:
            if item.get("year_id") == ano_id:
                trim_nome = item.get("name", "").lower()
                break
        logger.info(f"[WS] Trim detectada: {trim_nome}")
        
    # Preparar slugs para busca
    marca_slug = criar_slug(marca)
    modelo_slug = criar_slug(modelo.split()[0])  # Pega apenas o modelo base

    # Chamar API Wheel Size
    url_wheel = (
        f"https://api.wheel-size.com/v2/search/by_model/"
        f"?make={marca_slug}"
        f"&model={modelo_slug}"
        f"&year={ano_base}"
        f"&region=ladm"
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

        # Tentar encontrar a trim exata
        veiculo_correto = None
        melhor_match = None
        melhor_pontuacao = 0
        
        if data.get('data'):
            for veiculo in data['data']:
                trim_atual = veiculo.get('trim', '').lower()
                logger.info(f"[WS] Comparando trim: {trim_atual} vs {trim_nome}")
                
                # 1. Tentativa: Match exato com nome da trim
                if trim_nome and trim_atual == trim_nome:
                    veiculo_correto = veiculo
                    logger.info(f"[WS] Trim exato encontrado.")
                    break
                
                # 2. Tentativa: Similaridade de strings
                if trim_nome:
                    # Calcular similaridade baseada em tokens comuns
                    tokens_nome = set(trim_nome.split())
                    tokens_atual = set(trim_atual.split())
                    pontos = len(tokens_nome & tokens_atual)
                    
                    if pontos > melhor_pontuacao:
                        melhor_pontuacao = pontos
                        melhor_match = veiculo
        
        # Fallback: Usar melhor match ou primeiro veículo
        if not veiculo_correto:
            veiculo_correto = melhor_match if melhor_match else data['data'][0]
            logger.info(f"[WS] Usando melhor match ou fallback.")
        
        # Processar medidas
        if veiculo_correto and veiculo_correto.get('wheels'):
            roda = veiculo_correto['wheels'][0]['front']
            medida = roda.get('tire_full', '')
            
            if not medida:
                medida = f"{roda['section_width']}/{roda['aspect_ratio']} R{roda['rim_diameter']}"
            
            # Informações de debug
            debug_info = {
                "trim_encontrada": veiculo_correto.get('trim'),
                "trim_buscada": trim_nome,
                "match_exato": True if veiculo_correto.get('trim', '').lower() == trim_nome else False
            }
            
            return {
                "medida": medida.replace('R', ' R'),  # Formata para padrão brasileiro
                "debug": debug_info
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
    import logging
    import httpx

    logger = logging.getLogger("calculadora_fipe")
    relatorio = []
    total_abatimento = 0

    # REMOVIDO: Filtro de pneus
    api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"

    logger.info("[DEBUG] Função buscar_precos_e_gerar_relatorio foi chamada.")
    logger.info(f"[DEBUG] URL Apify: {api_url}")
    logger.info(f"[DEBUG] Peças Selecionadas: {pecas_selecionadas}")
    logger.info(f"[DEBUG] Marca: {marca_nome}, Modelo: {modelo_nome}, Ano: {ano_nome}")

    async with httpx.AsyncClient(timeout=60) as client:
        for peca in pecas_selecionadas:
            if not peca or peca.lower() == "não":
                continue

            # NOVO TRATAMENTO PARA PNEUS
            if peca.strip().lower().startswith("kit pneus"):
                termo_busca = peca.strip()   # Termo exato para pneus
            else:
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

                    # NOVO: Só aplicar filtro se não for pneu
                    if not peca.strip().lower().startswith("kit pneus"):
                        titulo = item.get("eTituloProduto", "").lower()
                        modelo_normalizado = modelo_nome.lower().split()[0]
                        peca_normalizada = peca.lower().split()[0]

                        if peca_normalizada not in titulo or modelo_normalizado not in titulo:
                            logger.info(f"[DEBUG] Ignorado: título irrelevante → {titulo}")
                            continue

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
                    "links": links[:3],
                    "imagens": imagens[:3],
                    "nomes": nomes[:3],
                    "precos": precos_texto[:3]
                })

            except Exception as e:
                logger.error(f"[ERROR] Erro inesperado ao buscar preços via Apify: {str(e)}")
                relatorio.append({"item": peca, "erro": f"Erro inesperado ao buscar preços: {str(e)}"})

    logger.info(f"[DEBUG] Relatório final: {relatorio}")
    return relatorio, total_abatimento
