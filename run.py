"""Avvio di sviluppo su porta 8090.

Usa questo script per non dover ricordare la porta:

    python run.py

L'app sarà disponibile su http://127.0.0.1:8090
"""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8090, reload=True)
