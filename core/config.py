import os
import yaml
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))

def load_config():
    load_dotenv(os.path.join(ROOT, ".env"))
    path = os.path.join(ROOT, "config", "settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    token_env = cfg.get("discord", {}).get("token_env", "DISCORD_TOKEN")
    cfg["discord"]["token"] = os.getenv(token_env, "")
    verify = cfg.setdefault("verify", {})
    verify["client_id"] = os.getenv(verify.get("client_id_env", "DISCORD_OAUTH_CLIENT_ID"), verify.get("client_id", ""))
    verify["client_secret"] = os.getenv(verify.get("client_secret_env", "DISCORD_OAUTH_CLIENT_SECRET"), verify.get("client_secret", ""))
    verify["recovery_key"] = os.getenv(verify.get("recovery_key_env", "JARVIS_RECOVERY_KEY"), verify.get("recovery_key", ""))
    verify["pull_api_key"] = os.getenv(verify.get("pull_api_key_env", "JARVIS_PULL_API_KEY"), verify.get("pull_api_key", ""))
    # Railway injects PORT and requires public services to bind to 0.0.0.0.
    # Keep the local defaults intact when these variables are not present.
    if os.getenv("PORT"):
        verify["host"] = "0.0.0.0"
        verify["port"] = int(os.environ["PORT"])
    if os.getenv("JARVIS_VERIFY_HOST"):
        verify["host"] = os.environ["JARVIS_VERIFY_HOST"]
    if os.getenv("JARVIS_VERIFY_PORT"):
        verify["port"] = int(os.environ["JARVIS_VERIFY_PORT"])
    verify["public_base_url"] = os.getenv("JARVIS_PUBLIC_BASE_URL", verify.get("public_base_url", "")).rstrip("/")
    verify["redirect_uri"] = os.getenv("JARVIS_REDIRECT_URI", verify.get("redirect_uri", ""))
    database = cfg.setdefault("database", {})
    if os.getenv("JARVIS_DATABASE_PATH"):
        database["path"] = os.environ["JARVIS_DATABASE_PATH"]
    sellauth = cfg.setdefault("sellauth", {})
    sellauth["store_url"] = os.getenv(sellauth.get("store_url_env", "SELLAUTH_STORE_URL"), sellauth.get("store_url", "")).strip()
    sellauth["webhook_secret"] = os.getenv(sellauth.get("webhook_secret_env", "SELLAUTH_WEBHOOK_SECRET"), sellauth.get("webhook_secret", ""))
    if not cfg["discord"]["token"]:
        raise RuntimeError(f"Missing Discord token. Set {token_env} in .env")
    for key in ("data", "logs", "backups"):
        os.makedirs(os.path.join(ROOT, key), exist_ok=True)
    return cfg
