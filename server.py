import os
import re
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import json
import time
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from openai import OpenAI

# ===== 1) env 読み込み =====
load_dotenv()

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")    
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")   
ENDPOINT_NAME = os.getenv("ENDPOINT_NAME")        

# ===== 2) FastAPI =====
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ===== 3) Databricks client =====
client = None
if DATABRICKS_HOST and DATABRICKS_TOKEN:
    client = OpenAI(
        api_key=DATABRICKS_TOKEN,
        base_url=f"{DATABRICKS_HOST.rstrip('/')}/serving-endpoints"
    )

# ===== 4) helpers =====
def extract_reply(resp) -> str | None:
    # A) OpenAI互換: choices[0].message.content
    choices = getattr(resp, "choices", None)
    if choices:
        msg = getattr(choices[0], "message", None)
        content = getattr(msg, "content", None) if msg else None
        if content:
            return content

    # B) Databricks形式: resp.messages の assistant
    msgs = getattr(resp, "messages", None)
    if msgs:
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content"):
                return m["content"]

    return None

def clean_text(s: str) -> str:
    """Markdownっぽい装飾を軽く落として、画面がキレイに見えるようにする"""
    s = s.strip()

    # 見出し # / ## などを削除
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)

    # 太字 **text** -> text
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)

    # 箇条書きの先頭記号を整える
    s = re.sub(r"(?m)^\s*-\s*", "・", s)

    # 連番はそのままでもOKだが、余計な空行を詰める
    s = re.sub(r"\n{3,}", "\n\n", s)

    # URLの前後が崩れやすいので余計な空白を少し整える
    s = s.replace("公式サイト：", "公式サイト: ")

    return s

# ===== 5) API =====
@app.post("/chat")
def chat(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        return {"reply": "入力が空です。"}

    if client is None or not ENDPOINT_NAME:
        # デモを安定させたいなら 200で返してもOK
        return JSONResponse(
            status_code=503,
            content={"reply": "Databricks未設定: .env を確認してください。"}
        )

    try:
        resp = client.chat.completions.create(
            model=ENDPOINT_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたは『おもてなし規格認証』の案内AIです。"
                        "日本語で、短く・要点だけ・Markdown記号（# ** - など）を極力使わずに答えてください。"
                        "URLは最後に1つだけ。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )

        reply = extract_reply(resp)
        if not reply:
            # ここはログだけ濃く、UI返答は短く
            try:
                dumped = resp.model_dump()
            except Exception:
                dumped = str(resp)
            print("[WARN] reply not found:", dumped)
            return JSONResponse(status_code=502, content={"reply": "すみません、回答の生成に失敗しました。もう一度お試しください。"})

        return {"reply": clean_text(reply)}

    except Exception as e:
        print("[ERROR] databricks call failed:", type(e).__name__, str(e))
        return JSONResponse(status_code=502, content={"reply": "すみません、現在接続が不安定です。少し待ってから再度お試しください。"})


@app.get("/chat_stream")
def chat_stream(text: str):
    text = (text or "").strip()

    def sse(payload: dict):
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def gen():
        if not text:
            yield "event: end\ndata: {}\n\n"
            return

        if client is None or not ENDPOINT_NAME:
            yield sse({"type": "error", "msg": "[LOCAL] Databricks未設定: .env確認"})
            yield "event: end\ndata: {}\n\n"
            return

        # ✅ まず start（これがないとUIが永遠に「考え中…」になりやすい）
        yield sse({"type": "start"})

        # ----------------------------
        # 1) まずは「本物の stream」を試す
        # ----------------------------
        streamed_any = False
        try:
            stream = client.chat.completions.create(
                model=ENDPOINT_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "あなたは『おもてなし規格認証』の案内AIです。"
                            "日本語で、短く・要点だけ・Markdown記号（# ** - など）を極力使わずに答えてください。"
                            "URLは最後に1つだけ。"
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                stream=True,
            )

            for chunk in stream:
                piece = None

                # OpenAI互換: chunk.choices[0].delta.content
                choices = getattr(chunk, "choices", None)
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    piece = getattr(delta, "content", None) if delta else None

                # Databricksで別形式が来る可能性もあるので保険（dictの場合）
                if piece is None and isinstance(chunk, dict):
                    try:
                        piece = chunk["choices"][0]["delta"].get("content")
                    except Exception:
                        piece = None

                if piece:
                    streamed_any = True
                    yield sse({"type": "token", "t": piece})

            # ✅ 本物ストリームで1回でも出たならそのまま終了
            if streamed_any:
                yield "event: end\ndata: {}\n\n"
                return

        except Exception:
            # ここで落ちても下でフォールバックする
            pass

        # ----------------------------
        # 2) フォールバック：全文取得 → 擬似ストリーム
        # ----------------------------
        try:
            resp = client.chat.completions.create(
                model=ENDPOINT_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "あなたは『おもてなし規格認証』の案内AIです。"
                            "日本語で、短く・要点だけ・Markdown記号（# ** - など）を極力使わずに答えてください。"
                            "URLは最後に1つだけ。"
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
            )

            answer = extract_reply(resp)
            if not answer:
                try:
                    dumped = resp.model_dump()
                except Exception:
                    dumped = str(resp)
                yield sse({"type": "error", "msg": f"[LOCAL] 応答から本文が取れない: {dumped}"})
                yield "event: end\ndata: {}\n\n"
                return

            answer = clean_text(answer)

            for ch in answer:
                yield sse({"type": "token", "t": ch})
                time.sleep(0.008)  # 好みで調整

            yield "event: end\ndata: {}\n\n"

        except Exception as e:
            yield sse({"type": "error", "msg": f"[LOCAL] Databricks接続失敗: {type(e).__name__}: {e}"})
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
