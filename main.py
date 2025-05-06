from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
from bs4 import BeautifulSoup

app = FastAPI()

# Permitir CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/fipe")
async def get_fipe_price(modelo: str = Query(..., description="Modelo do veículo")):
    try:
        url = f"https://www.google.com/search?q=tabela+fipe+{modelo.replace(' ', '+')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")

            valor_span = soup.find("span", string=lambda x: x and "R$" in x)
            if valor_span:
                return {"modelo": modelo, "fipe": valor_span.text.strip()}

        return {"modelo": modelo, "fipe": "Não encontrado"}
    except Exception as e:
        return {"erro": str(e)}