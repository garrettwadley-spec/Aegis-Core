# 1) Activate venv (lives at the project root)
& "$PSScriptRoot\.venv\Scripts\Activate.ps1"

# 2) Env vars for the orchestrator -> Ollama
$env:AEGIS_MODEL = "llama3.1"
$env:OLLAMA_URL  = "http://127.0.0.1:11434/api/generate"

# 3) Run the server from project root
python -m uvicorn aegis.api.orchestrator:app --reload --port 8088
