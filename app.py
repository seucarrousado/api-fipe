from fastapi import FastAPI, HTTPException, Query, Request
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuração de pastas
PASTA_RELATORIOS = os.path.join(BASE_DIR, "relatorios")
os.makedirs(PASTA_RELATORIOS, exist_ok=True)

# Caminhos de arquivos
LOG_CAMINHO = os.path.join(PASTA_RELATORIOS, "log_pecas.csv")
ARQUIVO_CIDADES = os.path.join(BASE_DIR, "cidades_por_estado.json")

app = FastAPI()

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calculadora_fipe")
logger.info("API Inicializada com sucesso!")

# Configuração CORS
origins = [
    "https://slategrey-camel-778778.hostingersite.com",
    "http://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Configurações de API
BASE_URL = "https://api.invertexto.com/v1/fipe"
TOKEN = os.getenv("INVERTEXTO_API_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR = os.getenv("APIFY_ACTOR")
WHEEL_SIZE_TOKEN = os.getenv("WHEEL_SIZE_TOKEN")
cache = TTLCache(maxsize=100, ttl=3600)

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

# Endpoint principal de peças
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
    cidade_usuario: str = Query("")
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

        relatorio, total_pecas = await buscar_precos_e_gerar_relatorio(
            marca, modelo_nome, ano.split('-')[0], lista_pecas, estado_usuario, cidade_usuario
        )
        
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
        }
    except Exception as e:
        logger.error(f"Erro na consulta de peças: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro na consulta: {str(e)}")
        
# Função para buscar preços
async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas, estado_usuario, cidade_usuario):
    api_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"

    async with httpx.AsyncClient(timeout=60) as client:
        async def fetch_peca(peca):
            termo_busca = peca if peca.lower().startswith("kit pneus") else f"{peca} {marca_nome} {modelo_nome} {ano_nome}"
            payload = {"keyword": termo_busca, "pages": 1, "promoted": False}
            
            try:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                dados_completos = response.json()
                
                if not isinstance(dados_completos, list) or not dados_completos:
                    return {"item": peca, "erro": "Sem resultados válidos"}

                precos, links, imagens, nomes, precos_texto = [], [], [], [], []

                for item in dados_completos[:5]:
                    if not peca.strip().lower().startswith("kit pneus"):
                        titulo = item.get("eTituloProduto", "").lower()
                        modelo_base = modelo_nome.lower().split()[0]
                        if modelo_base not in titulo:
                            continue

                    preco_str = item.get("novoPreco")
                    if not preco_str:
                        continue
                    
                    try:
                        preco = float(str(preco_str).replace(".", "").replace(",", "."))
                    except ValueError:
                        continue
                        
                    precos.append(preco)
                    links.append(item.get("zProdutoLink", ""))
                    imagens.append(item.get("imagemLink", ""))
                    nomes.append(item.get("eTituloProduto", ""))
                    precos_texto.append(preco_str)

                if not precos:
                    return {"item": peca, "erro": "Nenhum preço válido"}

                preco_medio = round(sum(precos) / len(precos), 2)
                
                # Log da pesquisa
                with open(LOG_CAMINHO, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().isoformat(),
                        marca_nome,
                        modelo_nome,
                        ano_nome,
                        peca,
                        estado_usuario,
                        cidade_usuario
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
                return {"item": peca, "erro": f"Falha: {str(e)}"}

        tasks = [fetch_peca(peca) for peca in pecas_selecionadas if peca]
        resultados = await asyncio.gather(*tasks)

        total_abatimento = sum(item.get("abatido", 0) for item in resultados if isinstance(item, dict))
        return resultados, total_abatimento

# Endpoints auxiliares
@app.get("/cidades/{uf}")
async def get_cidades_por_estado(uf: str):
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

@app.get("/exportar-logs")
async def exportar_log_de_pecas():
    try:
        if not os.path.exists(LOG_CAMINHO):
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        return FileResponse(LOG_CAMINHO, filename="log_pecas.csv", media_type="text/csv")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao exportar: {str(e)}")

# Sistema de leads
@app.options("/salvar-lead")
async def options_salvar_lead():
    return {"Allow": "POST"}

@app.post("/salvar-lead")
async def salvar_lead(request: Request):
    try:
        lead_data = await request.json()

        caminho = os.path.join(PASTA_RELATORIOS, "leads.csv")
        campos = ["data_hora", "nome", "email", "whatsapp", "objetivo", "placa", "marca", "modelo", "ano", "pecas", "estado", "cidade"]
        criar_arquivo = not os.path.exists(caminho)

        with open(caminho, mode="a", encoding="utf-8", newline="") as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=campos)
            
            if criar_arquivo:
                writer.writeheader()
                
            writer.writerow({
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
            })

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro ao salvar lead: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

@app.get("/exportar-leads")
async def exportar_leads():
    caminho = os.path.join(PASTA_RELATORIOS, "leads.csv")
    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Nenhum lead registrado")
    return FileResponse(caminho, media_type="text/csv", filename="leads.csv")

# Resposta padrão
@app.get("/")
async def health_check():
    return {"status": "online", "versao": "1.0.0"}
