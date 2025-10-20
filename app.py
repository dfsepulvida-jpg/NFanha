
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import io
import traceback
import csv
import typing

# importe sua função existente de extração
# ajuste o import se o módulo tiver outro nome ou estiver em subpasta
from extractor import process_bytes_files

app = FastAPI(title="NF Extractor")

# permitir acesso do browser localmente
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def form_index():
    # formulário simples para selecionar múltiplos arquivos e enviar para o endpoint /process
    return """
    <html>
      <head>
        <title>Upload Notas</title>
      </head>
      <body>
        <h3>Enviar múltiplas notas</h3>
        <form action="/process" enctype="multipart/form-data" method="post">
          <input name="files" type="file" multiple>
          <input type="submit" value="Enviar">
        </form>
      </body>
    </html>
    """


@app.post("/process")
async def process_files(files: typing.List[UploadFile] = File(...), return_format: str = Form("csv")):
    """
    Endpoint robusto para processar múltiplos PDFs.
    - files: lista de arquivos (multipart/form-data)
    - return_format: 'csv' ou 'json' (opcional)
    """
    try:
        if not files:
            raise HTTPException(status_code=400, detail="Nenhum arquivo enviado")

        # ler bytes de cada arquivo
        payloads = []
        for f in files:
            content = await f.read()
            payloads.append({"filename": f.filename or "unknown.pdf", "bytes": content})

        # chamar o extractor (process_bytes_files) — deve retornar DataFrame
        df = process_bytes_files(payloads)

        if df is None:
            # o extractor retornou None -> tratar como erro interno
            raise RuntimeError("Extractor retornou None para os arquivos enviados")

        # escolher formato de retorno
        if return_format.lower() == "json":
            # converter DataFrame para JSON (orient='records')
            data = df.fillna("").to_dict(orient="records")
            return JSONResponse(content={"rows": data})

        # gerar CSV em memória (sep=';') para compatibilidade Excel PT-BR
        stream = io.StringIO()
        df.to_csv(stream, index=False, sep=';', encoding='utf-8')
        stream.seek(0)
        return StreamingResponse(
            io.BytesIO(stream.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="extracao_notas.csv"'}
        )

    except HTTPException:
        # repassa HTTPExceptions (400 etc.)
        raise
    except Exception as exc:
        # log no servidor e retornar erro amigável; em desenvolvimento devolvemos também stacktrace
        tb = traceback.format_exc()
        app.logger = getattr(app, "logger", None)
        try:
            # tentar imprimir no stdout/uvicorn logs
            print("Erro no endpoint /process:", tb)
        except Exception:
            pass
        # retornar detalhes em JSON para facilitar debug local (remover em produção)
        return JSONResponse(status_code=500, content={"error": "Internal Server Error", "detail": str(exc), "trace": tb})