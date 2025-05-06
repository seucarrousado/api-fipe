from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "API da FIPE está no ar"}
