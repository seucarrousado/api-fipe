# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import httpx
from bs4 import BeautifulSoup

app = FastAPI()

# Permitir CORS para o domínio da Hostinger
origins = [
    "https://slategrey-camel-778778.hostingersite.com",
    "http://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros/marcas"

@app.get("/marcas")
def listar_marcas():
    try:
        response = requests.get(BASE_URL)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter marcas: {str(e)}")

@app.get("/modelos/{marca_id}")
def listar_modelos(marca_id: str):
    try:
        url = f"{BASE_URL}/{marca_id}/modelos"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter modelos: {str(e)}")

@app.get("/anos/{marca_id}/{modelo_id}")
def listar_anos(marca_id: str, modelo_id: str):
    try:
        url = f"{BASE_URL}/{marca_id}/modelos/{modelo_id}/anos"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter anos: {str(e)}")
        
@app.get("/fipe")
def consultar_fipe(marca: str, modelo: str, ano: str):
    try:
        # ✅ Agora os parâmetros já são códigos corretos
        url = f"{BASE_URL}/{marca}/modelos/{modelo}/anos/{ano}"
        fipe_data = requests.get(url).json()

        valor = fipe_data.get("Valor")
        if not valor:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        return {"valor_fipe": valor}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar FIPE: {str(e)}")
from bs4 import BeautifulSoup
import httpx
@app.get("/calcular")
def calcular_preco_final(marca: str, modelo: str, ano: str, pecas: str):
    try:
        # Consulta valor FIPE
        url_fipe = f"{BASE_URL}/{marca}/modelos/{modelo}/anos/{ano}"
        fipe_data = requests.get(url_fipe).json()

        valor_fipe_str = fipe_data.get("Valor")
        if not valor_fipe_str:
            raise HTTPException(status_code=404, detail="Valor FIPE não encontrado")

        # Remove R$ e converte para float
        valor_fipe = float(re.sub(r'[^\d,]', '', valor_fipe_str).replace(',', '.'))

        # Processa as peças (espera uma string separada por vírgulas)
        lista_pecas = [p.strip() for p in pecas.split(",")]

        relatorio, total_abatido = buscar_precos_e_gerar_relatorio(
            marca_nome=marca,
            modelo_nome=modelo,
            ano_nome=ano,
            pecas_selecionadas=lista_pecas
        )

        valor_final = round(valor_fipe - total_abatido, 2)

        return {
            "valor_fipe": f"R$ {valor_fipe:.2f}",
            "total_abatido": f"R$ {total_abatido:.2f}",
            "valor_final": f"R$ {valor_final:.2f}",
            "relatorio_detalhado": relatorio
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no cálculo: {str(e)}")


def buscar_precos_e_gerar_relatorio(marca_nome, modelo_nome, ano_nome, pecas_selecionadas):
    url_base = "https://api.mercadolibre.com/sites/MLB/search"
    relatorio = []
    total_abatimento = 0

    for peca in pecas_selecionadas:
        termo_busca = f"{peca} {marca_nome} {modelo_nome} {ano_nome}"
        params = {"q": termo_busca, "limit": 5}

        try:
            response = requests.get(url_base, params=params)
            if response.status_code != 200:
                relatorio.append({"item": peca, "erro": "Erro na consulta"})
                continue

            data = response.json()
            resultados = []

            for item in data.get("results", []):
                preco = item.get("price")
                titulo = item.get("title")
                link = item.get("permalink")

                if preco and preco > 50:
                    resultados.append({"titulo": titulo, "preco": preco, "link": link})

            if not resultados:
                relatorio.append({"item": peca, "erro": "Nenhum preço válido encontrado"})
                continue

            # Calcula o preço médio das 3 melhores opções
            top_resultados = resultados[:3]
            media = sum(item["preco"] for item in top_resultados) / len(top_resultados)
            total_abatimento += media

            relatorio.append({
                "item": peca,
                "preco_medio": round(media, 2),
                "abatido": round(media, 2),
                "links": [item["link"] for item in top_resultados]
            })

        except Exception as e:
            relatorio.append({"item": peca, "erro": f"Erro: {str(e)}"})

    return relatorio, total_abatimento
