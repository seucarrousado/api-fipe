from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from cachetools import TTLCache
import httpx
import logging
import os
import asyncio
from datetime import datetime
import re
import unidecode
import csv
from fastapi.responses import FileResponse
from email.mime.text import MIMEText
import smtplib
from pathlib import Path
from pydantic import BaseModel
import sqlite3
from typing import Dict, List
import json
import time
import hashlib

# Configuração de diretórios
BASE_DIR = Path(__file__).parent
PASTA_RELATORIOS = BASE_DIR / "relatorios"
PASTA_RELATORIOS.mkdir(exist_ok=True)

# Caminhos de arquivos
LOG_CAMINHO = PASTA_RELATORIOS / "log_pecas.csv"
ARQUIVO_CIDADES = BASE_DIR / "cidades_por_estado.json"
LEADS_CAMINHO = PASTA_RELATORIOS / "leads.csv"
SQLITE_DB = PASTA_RELATORIOS / "dados.db"

app = FastAPI()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PASTA_RELATORIOS / "api.log")
    ]
)
logger = logging.getLogger("calculadora_fipe")

# PROD-ENV START: Configuração CORS para produção
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else [
    "https://calculadora.seucarrousado.com.br",           # FRONT REAL
    "https://seucarrousado.com.br",                       # FRONT REAL (se houver)
    "https://www.seucarrousado.com.br",                   # FRONT REAL (se houver)
    "https://powderblue-squid-275540.hostingersite.com",  # FRONT TESTE
    "http://localhost"                                    # DESENVOLVIMENTO
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# TEST-ENV END

# TEST-ENV START: Endpoint de healthcheck
@app.get("/healthz")
def healthz():
    return {"ok": True, "env": os.getenv("ENV", "test")}
# TEST-ENV END

# Configurações de API
BASE_URL = "https://api.invertexto.com/v1/fipe"
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR = os.getenv("APIFY_ACTOR")
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")

# SHOPEE START: Configurações da Shopee Affiliate API
SHOPEE_ID = os.getenv("SHOPEE_ID", "")
SENHA_SHOPEE = os.getenv("SENHA_SHOPEE", "")
SHOPEE_GQL = "https://open-api.affiliate.shopee.com.br/graphql"

# Query GraphQL para buscar produtos - versão simplificada para teste
PRODUCT_OFFER_Q = """
query ProductOffer($keyword: String!) {
  productOfferV2(keyword: $keyword) {
    nodes {
      productName
      itemId
      price
      imageUrl
      shopName
      productLink
      offerLink
    }
  }
}
"""
# SHOPEE END

# Normalização leve para fallbacks de busca
PLURAL_TO_SINGULAR = {
    "pastilhas": "pastilha",
    "discos": "disco",
    "filtros": "filtro",
    "freios": "freio",
    "amortecedores": "amortecedor",
    "retrovisores": "retrovisor",
}

def _remove_kit_prefix(piece_text: str) -> str:
    text = piece_text.strip()
    if text.lower().startswith("kit "):
        return text[4:].strip()
    return text

def _to_singular_words(piece_text: str) -> str:
    words = piece_text.split()
    normalized_words = []
    for word in words:
        lowered = word.lower()
        normalized_words.append(PLURAL_TO_SINGULAR.get(lowered, word))
    return " ".join(normalized_words)

# SHOPEE START: Funções de autenticação e integração
def _canonical_json(obj: dict) -> str:
    """Converte objeto para JSON canônico (sem espaços extras, ordenado)"""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)

def _auth_header(payload_str: str) -> str:
    """Gera header de autenticação SHA256 para Shopee"""
    ts = str(int(time.time()))
    factor = f"{SHOPEE_ID}{ts}{payload_str}{SENHA_SHOPEE}"
    
    sig = hashlib.sha256(factor.encode("utf-8")).hexdigest()
    
    return f"SHA256 Credential={SHOPEE_ID}, Timestamp={ts}, Signature={sig}"

async def shopee_graphql(query: str, variables: dict):
    """Executa query GraphQL na Shopee com autenticação"""
    # Verificar credenciais
    if not SHOPEE_ID or not SENHA_SHOPEE:
        logger.error("Credenciais da Shopee não configuradas!")
        raise RuntimeError("Credenciais da Shopee não configuradas")
    
    body = {"query": query, "variables": variables}
    payload_str = _canonical_json(body)
    headers = {
        "Content-Type": "application/json",
        "Authorization": _auth_header(payload_str),
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(SHOPEE_GQL, headers=headers, content=payload_str.encode("utf-8"))
        r.raise_for_status()
        data = r.json()
        
        if "errors" in data and data["errors"]:
            raise RuntimeError(f"Shopee GraphQL error: {data['errors']}")
        return data["data"]

async def buscar_pecas_shopee(keyword: str, page: int = 1, limit: int = 20):
    """Busca produtos na Shopee usando GraphQL"""
    try:
        data = await shopee_graphql(PRODUCT_OFFER_Q, {"keyword": keyword})
        nodes = data["productOfferV2"]["nodes"]
        cards = []
        for it in nodes:
            link = it.get("offerLink") or it.get("productLink")
            cards.append({
                "titulo": it["productName"],
                "preco": float(str(it["price"]).replace(",", ".")),
                "imagem": it["imageUrl"],
                "link": link,
                "loja": it.get("shopName", ""),
            })
        return cards
    except Exception as e:
        logger.error(f"Erro ao buscar produtos na Shopee: {str(e)}")
        return []
# SHOPEE END

cache = TTLCache(maxsize=100, ttl=3600)

# Inicialização do SQLite
def init_db():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs_pecas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT NOT NULL,
        marca TEXT NOT NULL,
        modelo TEXT NOT NULL,
        ano TEXT NOT NULL,
        peca TEXT NOT NULL,
        estado TEXT NOT NULL,
        cidade TEXT NOT NULL
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_hora TEXT NOT NULL,
        nome TEXT NOT NULL,
        email TEXT NOT NULL,
        whatsapp TEXT NOT NULL,
        objetivo TEXT NOT NULL,
        placa TEXT NOT NULL,
        marca TEXT NOT NULL,
        modelo TEXT NOT NULL,
        ano TEXT NOT NULL,
        pecas TEXT NOT NULL,
        estado TEXT NOT NULL,
        cidade TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

init_db()
logger.info("API e banco de dados inicializados com sucesso!")

# Funções auxiliares para SQLite
def salvar_log_peca(log_data: Dict):
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO logs_pecas (data_hora, marca, modelo, ano, peca, estado, cidade)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        log_data['data_hora'],
        log_data['marca'],
        log_data['modelo'],
        log_data['ano'],
        log_data['peca'],
        log_data['estado'],
        log_data['cidade']
    ))
    conn.commit()
    conn.close()

def salvar_lead_db(lead_data: Dict):
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO leads (
        data_hora, nome, email, whatsapp, objetivo, placa, 
        marca, modelo, ano, pecas, estado, cidade
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead_data['data_hora'],
        lead_data['nome'],
        lead_data['email'],
        lead_data['whatsapp'],
        lead_data['objetivo'],
        lead_data['placa'],
        lead_data['marca'],
        lead_data['modelo'],
        lead_data['ano'],
        lead_data['pecas'],
        lead_data['estado'],
        lead_data['cidade']
    ))
    conn.commit()
    conn.close()

def salvar_log_basico(marca: str, modelo: str, ano: str, pecas: str, estado: str, cidade: str):
    """Salva log básico quando usuário clica 'Calcular Valor Final'"""
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO leads (
        data_hora, nome, email, whatsapp, objetivo, placa, 
        marca, modelo, ano, pecas, estado, cidade
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",  # nome vazio
        "",  # email vazio
        "",  # whatsapp vazio
        "",  # objetivo vazio
        "",  # placa vazia
        marca,
        modelo,
        ano,
        pecas,
        estado,
        cidade
    ))
    conn.commit()
    lead_id = cursor.lastrowid
    conn.close()
    return lead_id

def atualizar_lead_completo(lead_id: int, nome: str, email: str, whatsapp: str, objetivo: str, placa: str):
    """Atualiza lead com dados pessoais quando usuário preenche modal"""
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE leads SET 
        nome = ?, email = ?, whatsapp = ?, objetivo = ?, placa = ?
    WHERE id = ?
    """, (nome, email, whatsapp, objetivo, placa, lead_id))
    conn.commit()
    conn.close()

def exportar_logs_para_csv():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM logs_pecas")
    logs = cursor.fetchall()
    
    temp_file = PASTA_RELATORIOS / "log_pecas_temp.csv"
    with open(temp_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(['id', 'data_hora', 'marca', 'modelo', 'ano', 'peca', 'estado', 'cidade'])
        writer.writerows(logs)
    
    if LOG_CAMINHO.exists():
        LOG_CAMINHO.unlink()
    temp_file.rename(LOG_CAMINHO)
    
    conn.close()
    return LOG_CAMINHO

def exportar_leads_para_csv():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM leads")
    leads = cursor.fetchall()
    
    temp_file = PASTA_RELATORIOS / "leads_temp.csv"
    with open(temp_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            'id', 'data_hora', 'nome', 'email', 'whatsapp', 'objetivo',
            'placa', 'marca', 'modelo', 'ano', 'pecas', 'estado', 'cidade'
        ])
        writer.writerows(leads)
    
    if LEADS_CAMINHO.exists():
        LEADS_CAMINHO.unlink()
    temp_file.rename(LEADS_CAMINHO)
    
    conn.close()
    return LEADS_CAMINHO

# Endpoint de ping
@app.api_route("/ping", methods=["GET", "HEAD"])
def ping(response: Response):
    return {"status": "ok"}

# Endpoints Fipe
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

# Funções auxiliares
def criar_slug(texto):
    texto = unidecode.unidecode(texto)
    texto = texto.lower()
    texto = re.sub(r'[^a-z0-9]+', '-', texto)
    return texto.strip('-')

# Endpoint Wheel Size
@app.get("/wheel-size")
async def buscar_medida_pneu(marca: str, modelo: str, ano_id: str):
    try:
        if '-' in marca:
            marca = marca.split('-')[-1]
        ano_base = ano_id.split('-')[0]
        trim_nome = modelo.lower().strip()
        marca_slug = criar_slug(marca)
        modelo_slug = criar_slug(modelo.split()[0])

        url_wheel = (
            f"https://api.wheel-size.com/v2/search/by_model/"
            f"?make={marca_slug}"
            f"&model={modelo_slug}"
            f"&year={ano_base}"
            f"&region=ladm"
            f"&ordering=trim"
            f"&user_key={WHEEL_SIZE_TOKEN}"
        )

        async with httpx.AsyncClient() as client:
            response_wheel = await client.get(url_wheel)
            response_wheel.raise_for_status()
            data = response_wheel.json()

        veiculo_correto = None
        melhor_match = None
        melhor_pontuacao = 0

        if data.get('data'):
            for veiculo in data['data']:
                trim_atual = veiculo.get('trim', '').lower()
                
                if trim_nome and trim_atual == trim_nome:
                    veiculo_correto = veiculo
                    break
                
                if trim_nome:
                    tokens_nome = set(trim_nome.split())
                    tokens_atual = set(trim_atual.split())
                    pontos = len(tokens_nome & tokens_atual)

                    if pontos > melhor_pontuacao:
                        melhor_pontuacao = pontos
                        melhor_match = veiculo

        if not veiculo_correto:
            veiculo_correto = melhor_match or (data['data'][0] if data['data'] else None)

        if veiculo_correto and veiculo_correto.get('wheels'):
            roda = veiculo_correto['wheels'][0]['front']
            medida = roda.get('tire_full') or f"{roda['section_width']}/{roda['aspect_ratio']} R{roda['rim_diameter']}"
            return {"medida": medida.replace('R', ' R')}

        return {"erro": "Medida não encontrada"}
    except Exception as e:
        logger.error(f"Erro na Wheel Size API: {str(e)}")
        return {"erro": f"Falha na API: {str(e)}"}

# Cálculos de desconto
def calcular_desconto_estado(interior, exterior, valor_fipe):
    desconto = 0
    
    if interior == "bom":
        desconto += valor_fipe * 0.01
    elif interior == "regular":
        desconto += valor_fipe * 0.03
    elif interior == "ruim":
        desconto += valor_fipe * 0.05
    
    if exterior == "bom":
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

# SHOPEE START: Endpoint principal de peças usando Shopee
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
    estado_usuario: str = Query(""),
    cidade_usuario: str = Query(""),
    limit: int = Query(20)
):
    try:
        from urllib.parse import unquote
        marca = unquote(marca)
        modelo = unquote(modelo)
        pecas = unquote(pecas)
        
        lista_pecas = [p.strip() for p in pecas.split(",") if p.strip()]
        modelo_nome = modelo.replace("  ", " ").strip()

        valor_fipe = 0
        if fipe_code:
            cache_key = f"{fipe_code}-{ano}"
            
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
                    if item.get("year_id") == ano:
                        valor_encontrado = item.get("price")
                        break
                
                if not valor_encontrado and valores:
                    valor_encontrado = valores[0]["price"]
                    
                if not valor_encontrado:
                    raise HTTPException(status_code=404, detail="Valor não encontrado")
                    
                valor_fipe = float(valor_encontrado)
                cache[cache_key] = valor_fipe

        # Caso não haja peças selecionadas, sugerir kits úteis
        relatorio = []
        total_pecas = 0

        if not lista_pecas:
            logger.info("Nenhuma peça selecionada. Gerando sugestões automáticas (óleo, limpeza, socorro)...")
            modelo_basico = modelo_nome.split()[0] if modelo_nome else ""
            base_ano = ano.split('-')[0] if '-' in ano else ano

            # Sugerir kit de óleo e filtros com modelo/ano
            sugeridos_oleo = []
            try:
                keywords_oleo = [
                    f"kit óleo filtros {modelo_basico} {base_ano}".strip(),
                    f"kit óleo filtros {modelo_basico}".strip(),
                ]
                for kw in keywords_oleo:
                    if not kw.strip():
                        continue
                    logger.info(f"Sugestão óleo - tentando keyword: '{kw}'")
                    sugeridos_oleo = await buscar_pecas_shopee(kw, page=1, limit=5)
                    if sugeridos_oleo:
                        break
                sugeridos_oleo = sugeridos_oleo[:3]
            except Exception as e:
                logger.warning(f"Falha ao buscar sugestão 'kit óleo filtros': {e}")
                sugeridos_oleo = []

            # Sugerir kits genéricos SEM dados do carro
            try:
                sugeridos_limpeza = (await buscar_pecas_shopee("kit limpeza automotiva", page=1, limit=5))[:3]
            except Exception:
                sugeridos_limpeza = []

            try:
                sugeridos_socorro = (await buscar_pecas_shopee("kit socorro automotivo", page=1, limit=5))[:3]
            except Exception:
                sugeridos_socorro = []

            # Salvar log básico
            pecas_str = ", ".join(lista_pecas)
            lead_id = salvar_log_basico(marca, modelo_nome, ano, pecas_str, estado_usuario, cidade_usuario)
            logger.info(f"📝 Log básico salvo com ID: {lead_id}")

            desconto_estado = calcular_desconto_estado(estado_interior, estado_exterior, valor_fipe)
            desconto_km = calcular_desconto_km(km, valor_fipe, base_ano)
            total_descontos = desconto_estado + desconto_km + ipva_valor + total_pecas
            valor_final = valor_fipe - total_descontos

            return {
                "valor_fipe": valor_fipe,
                "total_abatido": total_descontos,
                "valor_final": valor_final,
                "desconto_estado": desconto_estado,
                "ipva_desconto": ipva_valor,
                "km_desconto": {"valor": desconto_km},
                "relatorio_detalhado": relatorio,
                "lead_id": lead_id,
                "sugestao_auto": True,
                "sugestoes": {
                    "oleo": sugeridos_oleo,
                    "limpeza": sugeridos_limpeza,
                    "socorro": sugeridos_socorro
                }
            }

        # Buscar produtos na Shopee para cada peça
        for peca in lista_pecas:
            # SHOPEE START: Estratégia de busca melhorada
            logger.info(f"🔍 Buscando peça: '{peca}'")
            logger.info(f"📋 Dados do veículo - Marca: '{marca}', Modelo: '{modelo_nome}', Ano: '{ano}'")
            
            # Tratamento especial para pneus - buscar apenas com a medida, sem modelo/ano
            if peca.lower().startswith("kit pneus"):
                keywords_tentativas = [peca]  # Buscar apenas "kit pneus 175/65 R14 82T"
            else:
                # SHOPEE API: Funciona apenas com peça + modelo básico (sem marca, sem versão)
                # Extrair apenas o nome básico do modelo (ex: "ARGO" em vez de "ARGO 1.0 6V Flex")
                modelo_basico = modelo_nome.split()[0]  # Pega apenas a primeira palavra
                
                base_ano = ano.split('-')[0]
                # Fallbacks leves: remover prefixo kit e normalizar plural -> singular
                peca_sem_kit = _remove_kit_prefix(peca)
                peca_singular = _to_singular_words(peca_sem_kit)

                # Construir tentativas mantendo ordem curta (ano primeiro)
                keywords_tentativas = []
                # 1) termo original
                keywords_tentativas.append(f"{peca} {modelo_basico} {base_ano}")
                keywords_tentativas.append(f"{peca} {modelo_basico}")
                # 2) sem kit
                if peca_sem_kit != peca:
                    keywords_tentativas.append(f"{peca_sem_kit} {modelo_basico} {base_ano}")
                    keywords_tentativas.append(f"{peca_sem_kit} {modelo_basico}")
                # 3) singular simples
                if peca_singular not in {peca, peca_sem_kit}:
                    keywords_tentativas.append(f"{peca_singular} {modelo_basico} {base_ano}")
                    keywords_tentativas.append(f"{peca_singular} {modelo_basico}")

                # Limitar tentativas para não alongar consulta
                keywords_tentativas = keywords_tentativas[:6]
            
            logger.info(f"📝 Keywords que serão testadas: {keywords_tentativas}")
            
            cards = []
            keyword_usado = ""
            
            for keyword in keywords_tentativas:
                logger.info(f"Tentando keyword: '{keyword}'")
                cards = await buscar_pecas_shopee(keyword, page=1, limit=5)
                logger.info(f"Resultado para '{keyword}': {len(cards)} cards encontrados")
                if cards:
                    keyword_usado = keyword
                    logger.info(f"✅ Sucesso com keyword: '{keyword}' - {len(cards)} produtos")
                    # Mostrar os primeiros produtos encontrados
                    for i, card in enumerate(cards[:2]):  # Mostrar apenas os 2 primeiros
                        logger.info(f"   📦 Produto {i+1}: '{card['titulo']}' - R$ {card['preco']}")
                    break
                else:
                    logger.info(f"❌ Nenhum resultado para: '{keyword}'")
            
            logger.info(f"Cards retornados para {peca}: {len(cards)} (keyword: {keyword_usado})")
            
            if cards:
                preco_medio = sum(card["preco"] for card in cards) / len(cards)
                total_pecas += preco_medio
                logger.info(f"Preço médio calculado para {peca}: {preco_medio}")
                
                relatorio.append({
                    "item": peca,
                    "preco_medio": round(preco_medio, 2),
                    "abatido": round(preco_medio, 2),
                    "cards": cards[:3]  # Primeiros 3 produtos
                })
            else:
                logger.warning(f"Nenhum card encontrado para {peca} em nenhuma tentativa")
                relatorio.append({
                    "item": peca,
                    "preco_medio": 0,
                    "abatido": 0,
                    "cards": []
                })
            # SHOPEE END
        
        logger.info(f"Relatório final: {json.dumps(relatorio, indent=2)}")
        
        # Salvar log básico quando usuário clica "Calcular Valor Final"
        pecas_str = ", ".join(lista_pecas)  # Converter lista para string
        lead_id = salvar_log_basico(marca, modelo_nome, ano, pecas_str, estado_usuario, cidade_usuario)
        logger.info(f"📝 Log básico salvo com ID: {lead_id}")
        
        desconto_estado = calcular_desconto_estado(estado_interior, estado_exterior, valor_fipe)
        desconto_km = calcular_desconto_km(km, valor_fipe, ano.split('-')[0])
        total_descontos = desconto_estado + desconto_km + ipva_valor + total_pecas
        valor_final = valor_fipe - total_descontos

        return {
            "valor_fipe": valor_fipe,
            "total_abatido": total_descontos,
            "valor_final": valor_final,
            "desconto_estado": desconto_estado,
            "ipva_desconto": ipva_valor,
            "km_desconto": {"valor": desconto_km},
            "relatorio_detalhado": relatorio,
            "lead_id": lead_id  # Retornar ID para o frontend
        }
    except Exception as e:
        logger.error(f"Erro na consulta de peças: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro na consulta: {str(e)}")
# SHOPEE END
        
# Função antiga removida - agora usando Shopee

# Endpoints auxiliares
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

@app.get("/exportar-logs")
async def exportar_log_de_pecas():
    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()
        
        # Cria arquivo temporário
        temp_file = PASTA_RELATORIOS / "logs_temp.csv"
        
        # Busca dados e escreve no CSV
        cursor.execute("SELECT * FROM logs_pecas ORDER BY data_hora DESC")
        with open(temp_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'data_hora', 'marca', 'modelo', 'ano', 'peca', 'estado', 'cidade'])
            writer.writerows(cursor.fetchall())
        
        # Substitui o arquivo antigo
        if LOG_CAMINHO.exists():
            LOG_CAMINHO.unlink()
        temp_file.rename(LOG_CAMINHO)
        
        conn.close()
        
        if not LOG_CAMINHO.exists():
            raise HTTPException(status_code=404, detail="Arquivo de logs não foi criado")
            
        return FileResponse(
            path=LOG_CAMINHO,
            filename="log_pecas.csv",
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=log_pecas.csv"}
        )
        
    except Exception as e:
        logger.error(f"Falha ao exportar logs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro na exportação: {str(e)}")

# Sistema de leads
@app.options("/salvar-lead")
async def options_salvar_lead():
    return {"Allow": "POST"}

@app.post("/salvar-lead")
async def salvar_lead(request: Request):
    try:
        lead_data = await request.json()
        logger.info(f"📩 Dados recebidos no salvar-lead: {lead_data}")
        
        # Garante que o diretório existe
        os.makedirs(PASTA_RELATORIOS, exist_ok=True)
        
        # Verifica permissões de escrita
        if not os.access(PASTA_RELATORIOS, os.W_OK):
            logger.error("❌ Sem permissão para escrever no diretório")
            raise HTTPException(status_code=500, detail="Sem permissão para escrever no diretório")
        
        # Verificar se tem lead_id (atualizar existente) ou criar novo
        lead_id = lead_data.get("lead_id")
        
        if lead_id:
            # Atualizar lead existente com dados pessoais
            atualizar_lead_completo(
                lead_id,
                lead_data.get("nome", ""),
                lead_data.get("email", ""),
                lead_data.get("whatsapp", ""),
                lead_data.get("objetivo", ""),
                lead_data.get("placa", "")
            )
            logger.info(f"✅ Lead {lead_id} atualizado com dados pessoais")
        else:
            # Criar novo lead completo (fallback)
        linha = {
            "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nome": lead_data.get("nome", ""),
            "email": lead_data.get("email", ""),
            "whatsapp": lead_data.get("whatsapp", ""),
            "objetivo": lead_data.get("objetivo", ""),
            "placa": lead_data.get("placa", ""),
            "marca": lead_data.get("marca", ""),
            "modelo": lead_data.get("modelo", ""),
            "ano": lead_data.get("ano", ""),
            "pecas": lead_data.get("pecas", ""),
            "estado": lead_data.get("estado", ""),
            "cidade": lead_data.get("cidade", "")
        }
        salvar_lead_db(linha)
            logger.info(f"✅ Novo lead criado: {linha}")
            
        return {"status": "ok", "arquivo": str(LEADS_CAMINHO)}
        
    except Exception as e:
        logger.error(f"❌ Erro ao salvar lead: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

@app.get("/exportar-leads")
async def exportar_leads():
    try:
        exportar_leads_para_csv()
        
        if not LEADS_CAMINHO.exists():
            logger.error(f"Arquivo de leads não encontrado em {LEADS_CAMINHO}")
            raise HTTPException(status_code=404, detail="Nenhum lead registrado")
            
        logger.info(f"Enviando arquivo de leads: {LEADS_CAMINHO}")
        return FileResponse(
            path=LEADS_CAMINHO,
            filename="leads.csv",
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=leads.csv"}
        )
    except Exception as e:
        logger.error(f"Erro ao exportar leads: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao exportar leads: {str(e)}")

# Modelo para sugestões
class SugestaoForm(BaseModel):
    mensagem: str

# Endpoint de saúde
@app.get("/")
async def health_check():
    return {"status": "online", "versao": "1.0.0"}

# Endpoint para enviar sugestões
@app.post("/enviar-sugestao-email")
async def enviar_sugestao_email(form: SugestaoForm):
    try:
        # Corpo do e-mail com formatação melhorada
        corpo = f"""
        Nova sugestão recebida no site:

        Mensagem:
        {form.mensagem}
        
        ---
        Enviado automaticamente pelo sistema
        """
        
        msg = MIMEText(corpo)
        msg["Subject"] = "Sugestão recebida – Seu Carro Usado"
        msg["From"] = "blog@seucarrousado.com.br"
        msg["To"] = "contato@seucarrousado.com.br"

        smtp_server = "smtp.hostinger.com"
        smtp_port = 587
        smtp_user = "blog@seucarrousado.com.br"
        smtp_password = os.getenv("EMAIL_SENHA")

        if not smtp_password:
            logger.error("ERRO CRÍTICO: Variável EMAIL_SENHA não configurada")
            return {"status": "erro", "detalhe": "Configuração de email incompleta"}

        logger.info(f"Enviando email via {smtp_server}:{smtp_port} com usuário {smtp_user}")

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.set_debuglevel(1)  # Ativa logging detalhado SMTP
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, ["contato@seucarrousado.com.br"], msg.as_string())
            logger.info("Email enviado com sucesso!")

        return {"status": "sucesso"}
    except smtplib.SMTPException as e:
        logger.error(f"Erro SMTP: {str(e)}")
        return {"status": "erro", "detalhe": f"Falha SMTP: {str(e)}"}
    except Exception as e:
        logger.error(f"Erro geral: {str(e)}", exc_info=True)
        return {"status": "erro", "detalhe": f"Erro inesperado: {str(e)}"}
        
# ... (outros endpoints existentes)

@app.get("/ver-leads-completo")
async def ver_leads_completo():
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    colunas = [desc[0] for desc in cursor.description]  # Pega os nomes das colunas
    resultados = cursor.fetchall()
    conn.close()
    
    leads = []
    for lead in resultados:
        leads.append(dict(zip(colunas, lead)))  # Converte para dicionário
    
    return {"leads": leads}

@app.get("/ver-logs-completo")
async def ver_logs_completo():
    # CORREÇÃO: Mostrar dados da tabela 'leads' em vez de 'logs_pecas'
    # para evitar duplicação (uma entrada por análise completa)
    conn = sqlite3.connect(SQLITE_DB)
    cursor = conn.cursor()
    
    # Obtém os nomes das colunas da tabela leads
    cursor.execute("PRAGMA table_info(leads)")
    colunas = [col[1] for col in cursor.fetchall()]
    
    # Obtém todos os leads (análises completas)
    cursor.execute("SELECT * FROM leads ORDER BY data_hora DESC")
    resultados = cursor.fetchall()
    conn.close()
    
    # Formata os resultados
    logs_formatados = []
    for lead in resultados:
        lead_dict = {}
        for i, coluna in enumerate(colunas):
            lead_dict[coluna] = lead[i]
        logs_formatados.append(lead_dict)
    
    return {
        "total_logs": len(resultados),
        "colunas": colunas,
        "logs": logs_formatados
    }
