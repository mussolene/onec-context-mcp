#!/usr/bin/env python3
"""
Тестирование бэкендов эмбеддингов для проекта 1c_hbk_helper.

Проверяет: deterministic, local (sentence-transformers), LM Studio (localhost:1234),
Ollama (localhost:11434). Измеряет размерность, задержку и корректность на русских текстах.

Запуск:
  PYTHONPATH=src python scripts/embedding_benchmark.py
  EMBEDDING_BACKEND=local EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v2-moe python scripts/embedding_benchmark.py
  EMBEDDING_BACKEND=openai_api EMBEDDING_API_URL=http://localhost:11434/v1 python scripts/embedding_benchmark.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# Тестовые русские тексты для проверки семантики (похожие должны быть ближе по косинусу)
RU_SAMPLES = [
    ("МенеджерКриптографии.ПодписатьДанные — подписание данных ключом.", "Подпись данных в 1С"),
    ("Запрос.Выполнить возвращает результат выполнения запроса.", "Выполнение запроса к базе"),
    ("Не связанные по смыслу предложения про погоду.", "Как получить хеш строки в 1С"),
]

DEFAULT_LM_STUDIO_URL = "http://localhost:1234/v1"
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Косинусное сходство между двумя векторами."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def probe_url(url: str, timeout: int = 5) -> tuple[bool, str]:
    """Проверка доступности URL и при необходимости списка моделей."""
    try:
        req = urllib.request.Request(
            f"{url.rstrip('/')}/models",
            method="GET",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = []
        for item in (data.get("data") or []):
            if isinstance(item, dict) and item.get("id"):
                models.append(item["id"])
        for item in (data.get("models") or []):
            if isinstance(item, dict) and item.get("key"):
                models.append(item["key"])
        if models:
            return True, f"OK, models: {models[:5]}{'...' if len(models) > 5 else ''}"
        return True, "OK (no model list)"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:80]


def run_with_env(
    backend: str,
    extra_env: dict[str, str],
    label: str,
) -> dict:
    """Запуск теста с заданным окружением (через subprocess для изоляции)."""
    import subprocess

    env = os.environ.copy()
    env["EMBEDDING_BACKEND"] = backend
    env["EMBEDDING_CACHE_SIZE"] = "0"
    for k, v in extra_env.items():
        env[k] = v
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(proj_root, "src")
    env["PYTHONPATH"] = src_dir + (os.pathsep + env.get("PYTHONPATH", ""))
    code = """
import os, sys, time, json
from onec_help import embedding as emb

samples = [
    ("МенеджерКриптографии.ПодписатьДанные — подписание данных ключом.", "Подпись данных в 1С"),
    ("Запрос.Выполнить возвращает результат выполнения запроса.", "Выполнение запроса к базе"),
]
dim = emb.get_embedding_dimension()
# Один запрос
t0 = time.perf_counter()
v1 = emb.get_embedding(samples[0][0])
t1 = time.perf_counter()
# Второй для пары
v2 = emb.get_embedding(samples[0][1])
t2 = time.perf_counter()
# Косинус
def cos(a, b):
    if len(a) != len(b) or not a: return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    na = sum(x*x for x in a)**0.5
    nb = sum(x*x for x in b)**0.5
    return dot/(na*nb) if na and nb else 0.0
sim = cos(v1, v2)
out = {"dim": dim, "latency_first_ms": round((t1-t0)*1000, 1), "latency_second_ms": round((t2-t1)*1000, 1), "cosine_similar": round(sim, 4)}
print(json.dumps(out))
"""
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if r.returncode != 0:
            return {"error": r.stderr or r.stdout or "non-zero exit"}
        return json.loads(r.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"error": "timeout 60s"}
    except Exception as e:
        return {"error": str(e)}


def main() -> None:
    print("=== Embedding backends benchmark (1c_hbk_helper) ===\n")
    results = []

    # 1) Deterministic
    print("1. deterministic (no external service)")
    r = run_with_env("deterministic", {}, "deterministic")
    if "error" in r:
        print(f"   FAIL: {r['error']}\n")
        results.append(("deterministic", r))
    else:
        print(f"   dim={r['dim']}, latency ~{r['latency_first_ms']} ms, cosine(similar)={r['cosine_similar']}\n")
        results.append(("deterministic", r))

    # 2) Local (sentence-transformers)
    print("2. local (sentence-transformers)")
    r = run_with_env(
        "local",
        {"EMBEDDING_MODEL": os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v2-moe")},
        "local",
    )
    if "error" in r:
        print(f"   FAIL: {r['error'][:200]}\n")
        results.append(("local", r))
    else:
        print(f"   dim={r['dim']}, latency ~{r['latency_first_ms']} ms, cosine(similar)={r['cosine_similar']}\n")
        results.append(("local", r))

    # 3) LM Studio
    print("3. openai_api @ LM Studio (localhost:1234)")
    ok, msg = probe_url(DEFAULT_LM_STUDIO_URL)
    print(f"   Probe: {msg}")
    if ok:
        # LM Studio: авто-выбор модели (nomic-embed 768, paraphrase 384 и др.)
        r = run_with_env(
            "openai_api",
            {"EMBEDDING_API_URL": DEFAULT_LM_STUDIO_URL},
            "lm_studio",
        )
        if "error" in r:
            print(f"   FAIL: {r['error'][:200]}\n")
            results.append(("lm_studio", r))
        else:
            print(f"   dim={r['dim']}, latency ~{r['latency_first_ms']} ms, cosine(similar)={r['cosine_similar']}\n")
            results.append(("lm_studio", r))
    else:
        print("   Skip (LM Studio not reachable)\n")
        results.append(("lm_studio", {"error": "not reachable"}))

    # 4) Ollama
    print("4. openai_api @ Ollama (localhost:11434)")
    ok, msg = probe_url(DEFAULT_OLLAMA_URL)
    print(f"   Probe: {msg}")
    if ok:
        # Явно nomic-embed 768 (v2-moe — мультиязычный, лучше для русского)
        r = run_with_env(
            "openai_api",
            {
                "EMBEDDING_API_URL": DEFAULT_OLLAMA_URL,
                "EMBEDDING_MODEL": "nomic-embed-text-v2-moe",
                "EMBEDDING_DIMENSION": "768",
            },
            "ollama",
        )
        if "error" in r:
            r2 = run_with_env(
                "openai_api",
                {"EMBEDDING_API_URL": DEFAULT_OLLAMA_URL, "EMBEDDING_MODEL": "nomic-embed-text", "EMBEDDING_DIMENSION": "768"},
                "ollama",
            )
            if "error" not in r2:
                r = r2
        if "error" in r:
            print(f"   FAIL: {r['error'][:200]}\n")
            results.append(("ollama", r))
        else:
            print(f"   dim={r['dim']}, latency ~{r['latency_first_ms']} ms, cosine(similar)={r['cosine_similar']}\n")
            results.append(("ollama", r))
    else:
        print("   Skip (Ollama not reachable)\n")
        results.append(("ollama", {"error": "not reachable"}))

    # Summary
    print("=== Summary ===")
    for name, data in results:
        if "error" in data:
            print(f"  {name}: ERROR - {data['error'][:100]}")
        else:
            print(f"  {name}: dim={data['dim']}, latency_ms~{data['latency_first_ms']}, cosine={data['cosine_similar']}")
    print("\nDone. Use results to choose EMBEDDING_BACKEND and EMBEDDING_API_URL (see docs/embedding-models-analysis.md).")


if __name__ == "__main__":
    main()
