"""The sales tracker on Vercel: sign-in, the call list, leads, PDFs.

The lead finder (scraping), publishing previews and site exports stay on your
Mac. deploy/vercel.sh copies pipeline/ next to this file before deploying.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from pipeline import auth  # noqa: E402
from pipeline.web import router  # noqa: E402

app = FastAPI(title="DuNous sales pipeline", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)
auth.install(app)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/pipeline", 307)
