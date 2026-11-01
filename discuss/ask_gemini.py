"""把 discuss/rNN_prompt.md 发给 Gemini，回答写到 discuss/rNN_gemini.md。
模型按顺序尝试，先用最强的，不可用就换下一个。"""
import os, sys, time, glob, requests

KEY = os.environ["GEMINI_API_KEY"].strip()
BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
MODELS = [m.strip() for m in os.environ.get("MODELS",
    "gemini-3.8-pro,gemini-pro-latest,gemini-3-pro-preview,gemini-2.5-pro,gemini-3.8-flash,gemini-flash-latest").split(",") if m.strip()]

def ask(prompt):
    last = ""
    for model in MODELS:
        for wait in (0, 30, 60):
            time.sleep(wait)
            try:
                r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                                  json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                        "temperature": 1.0}, timeout=900)
            except requests.RequestException as e:
                last = f"{model} 网络错误 {e}"; print(last); continue
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            print(f"{model} {r.status_code}，重试")
        if r.ok:
            return model, r.json()["choices"][0]["message"]["content"]
        last = f"{model} {r.status_code} {r.text[:200]}"; print(last)
    raise SystemExit(last)

for p in sorted(glob.glob("discuss/r*_prompt.md")):
    out = p.replace("_prompt.md", "_gemini.md")
    if os.path.exists(out):
        continue
    model, text = ask(open(p, encoding="utf-8").read())
    print(f"{p} -> {model}，{len(text)} 字")
    open(out, "w", encoding="utf-8").write(f"<!-- model: {model} -->\n{text}\n")
