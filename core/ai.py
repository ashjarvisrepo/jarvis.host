import httpx

class LocalAI:
    def __init__(self, cfg): self.cfg=cfg
    async def ask(self, prompt):
        c=self.cfg.get("ai",{})
        if not c.get("enabled"): return "Local AI is disabled. Shop commands remain fully operational."
        url=c.get("base_url","http://127.0.0.1:11434").rstrip("/")+"/api/generate"
        payload={"model":c.get("model","qwen2.5:3b"),"prompt":prompt[:3000],"stream":False}
        try:
            async with httpx.AsyncClient(timeout=c.get("timeout_seconds",20)) as client:
                r=await client.post(url,json=payload); r.raise_for_status()
                return r.json().get("response","I couldn't generate a response.")
        except Exception:
            return "Local AI is unavailable. Start Ollama and pull the configured model, or continue using normal shop commands."
