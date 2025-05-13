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

# Configurações iniciais mantidas...

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

# Rotas de marcas, modelos e anos mantidas...

@app.get("/fipe/{marca}/{modelo}/{ano}")
async def consultar_fipe(marca: str, modelo: str, ano: str):
    try:
        cache_key = f"{marca}_{modelo}_{ano}"
        if cache_key in cache:
            logger.info(f"Valor FIPE recuperado do cache para {cache_key}")
            return {"valor_fipe": cache[cache_key]}

        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/cars/brands/{marca}/models/{modelo}/years/{ano}"
            response = await client.get(url)
            response.raise_for_status()
            fipe_data = response.json()

        valor = fipe_data.get("valor") or fipe_data.get("Valor")
        if not valor:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        # Formatação numérica aprimorada
        valor_numerico = float(re.sub(r"[^\d,]", "", valor).replace(",", "."))
        cache[cache_key] = valor_numerico

        return {"valor_fipe": valor_numerico}

    except httpx.HTTPStatusError as e:
        logger.error(f"Erro HTTP na consulta FIPE: {e}")
        raise HTTPException(status_code=e.response.status_code, detail="Erro na API FIPE")
    except Exception as e:
        logger.error(f"Erro geral na consulta FIPE: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na consulta FIPE: {str(e)}")

@app.get("/calcular")
async def calcular_preco_final(
    marca: str = Query(...),
    modelo: str = Query(...),
    ano: str = Query(...),
    pecas: str = Query("")
):
    try:
        # Consulta FIPE (com cache)
        cache_key = f"{marca}_{modelo}_{ano}"
        if cache_key in cache:
            valor_fipe = cache[cache_key]
        else:
            fipe_response = await consultar_fipe(marca, modelo, ano)
            valor_fipe = fipe_response["valor_fipe"]

        # Processamento das peças
        lista_pecas = [p.strip() for p in pecas.split("|") if p.strip()]
        
        # Simulação de cálculo (substituir por sua lógica real)
        relatorio = []
        total_abatido = 0.0
        
        for peca in lista_pecas:
            # Exemplo de lógica para cada peça
            preco_medio = 500.00  # Valor simulado
            relatorio.append({
                "item": peca,
                "preco_medio": preca_medio,
                "links": [],
                "erro": None
            })
            total_abatido += preco_medio

        valor_final = valor_fipe - total_abatido

        return {
            "valor_fipe": round(valor_fipe, 2),
            "total_abatido": round(total_abatido, 2),
            "valor_final": round(valor_final, 2),
            "relatorio_detalhado": relatorio
        }

    except Exception as e:
        logger.error(f"Erro no cálculo: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no cálculo: {str(e)}")



async def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    relatorio = []
    total_abatimento = 0

    for peca in pecas_selecionadas:
        if not peca or peca.lower() == "não":
            continue  # Ignora peças não selecionadas

        try:
            ia_response = buscar_via_ia(peca, marca_nome, modelo_nome, ano_nome)

            # Extração do preço médio da resposta da IA
            preco_match = re.search(r"Preço Médio: R\$ ([\d\.,]+)", ia_response)
            preco_medio = float(preco_match.group(1).replace(".", "").replace(",", ".")) if preco_match else 0.0

            # Extração dos links
            links = re.findall(r"https?://\S+", ia_response)

            if preco_medio == 0.0:
                relatorio.append({"item": peca, "erro": "Preço médio não encontrado pela IA."})
                continue

            total_abatimento += preco_medio

            relatorio.append({
                "item": peca,
                "preco_medio": preco_medio,
                "abatido": preco_medio,
                "links": links
            })

        except Exception as e:
            relatorio.append({"item": peca, "erro": f"Erro na resposta da IA: {str(e)}"})

    return relatorio, total_abatimento
