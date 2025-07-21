import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# .env のロード
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 環境変数から取得
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    raise RuntimeError("Environment variable GOOGLE_MAPS_API_KEY is not set.")

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # テンプレートにキーを渡す
    return templates.TemplateResponse(
        "MapTMobileMapPage.html",
        {"request": request, "google_maps_api_key": GOOGLE_MAPS_API_KEY}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)