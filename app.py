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

# Configurações essenciais
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}
BASE_URL = "https://parallelum.com.br/fipe/api/v1"
cache = TTLCache(maxsize=100, ttl=3600)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calculadora_fipe")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://slategrey-camel-778778.hostingersite.com", "http://localhost"],
    allow_methods=["GET"]
)

class FipeQuery(BaseModel):
    marca: str
    modelo: str
    ano: str
    pecas: str = Query("", description="Lista de peças separadas por |")

    @validator('marca', 'modelo', 'ano')
    def check_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Campo obrigatório não pode ser vazio.')
        return v

# --- ROTA MARCA (CRÍTICA PARA O FRONTEND) ---
@app.get("/marcas")
async def listar_marcas():
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BASE_URL}/cars/brands", headers=HEADERS)
            response.raise_for_status()
            
            # Verifica formato dos dados
            marcas = response.json()
            if not isinstance(marcas, list) or not all('codigo' in m and 'nome' in m for m in marcas):
                raise ValueError("Formato inválido de resposta da API FIPE")
            
            return marcas
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP FIPE: {e.response.status_code}")
        raise HTTPException(status_code=502, detail="Falha na comunicação com a tabela FIPE")
    
    except Exception as e:
        logger.error(f"Erro crítico: {str(e)}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar marcas")

# Resto das rotas (modelos, anos, fipe, calcular) mantidas conforme seu código original...
