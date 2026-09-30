"""Uses your OpenCode login to test Jarvis AI. Never prints the full key."""
import asyncio
import sys
sys.path.insert(0, ".")
from backend.config import get_key, mask
from backend.providers import chat, provider_status

async def main():
    print("Provider status:")
    for k, v in provider_status().items():
        print(f"  {k:10s} configured={v['configured']} key={v['key']}")
    key = get_key("OPENCODE_API_KEY")
    print(f"\nOpenCode key: {mask(key)} (source: auth.json or env)")
    if not key:
        print("No OpenCode key found. Add OPENCODE_API_KEY to .env or log in to OpenCode.")
        print("Trying free chain anyway (Ollama/offline)...")
    res = await chat([{"role": "user", "content": "Reply with exactly: JARVIS ONLINE. Then one short witty line."}],
                     provider="auto")
    print(f"\n[{res['provider']}/{res['model']}]")
    print(res["text"])
    assert res["text"].strip(), "Empty reply — router failed"
    print("\nOK — Jarvis brain test passed.")

if __name__ == "__main__":
    asyncio.run(main())
