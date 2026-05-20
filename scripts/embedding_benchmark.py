#!/usr/bin/env python3
"""
Тестирование бэкендов эмбеддингов для проекта onec-context-mcp.

Проверяет: deterministic, local (sentence-transformers), LM Studio (localhost:1234),
Ollama (localhost:11434). Измеряет размерность, задержку и корректность на русских текстах.

Запуск:
  PYTHONPATH=src python scripts/embedding_benchmark.py
  PYTHONPATH=src python scripts/embedding_benchmark.py --compare  # LM Studio vs Ollama, warm cache (32 pts)
  PYTHONPATH=src python scripts/embedding_benchmark.py --compare-full  # Прогрев сотни/тысячи, два прохода A→B и B→A, отчёт
  PYTHONPATH=src python scripts/embedding_benchmark.py --compare-full --warmup 1000 --test 300
  EMBEDDING_BACKEND=local EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v2-moe python scripts/embedding_benchmark.py
  EMBEDDING_BACKEND=openai_api EMBEDDING_API_URL=http://localhost:11434/v1 python scripts/embedding_benchmark.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Batch size for LM Studio vs Ollama comparison (warm run + timed run)
BATCH_COMPARE_SIZE = 32
# Defaults for --compare-full: warm-up batch size, then test batch size
DEFAULT_WARMUP_PTS = 500
DEFAULT_TEST_PTS = 200

# Test texts for batch (Russian, similar to real help chunks)
RU_SAMPLES = [
    ("МенеджерКриптографии.ПодписатьДанные — подписание данных ключом.", "Подпись данных в 1С"),
    ("Запрос.Выполнить возвращает результат выполнения запроса.", "Выполнение запроса к базе"),
    ("Не связанные по смыслу предложения про погоду.", "Как получить хеш строки в 1С"),
]


def _batch_test_texts(n: int) -> list[str]:
    """Return n short texts (from RU_SAMPLES repeated) for batch benchmark."""
    flat = [t for pair in RU_SAMPLES for t in pair]
    out = []
    for i in range(n):
        out.append(flat[i % len(flat)] + f" [{i}]")
    return out


DEFAULT_LM_STUDIO_URL = "http://localhost:1234/v1"
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Косинусное сходство между двумя векторами."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
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


def run_batch_warmup_timed(
    backend: str,
    extra_env: dict[str, str],
    num_texts: int = BATCH_COMPARE_SIZE,
    warmup_pts: int | None = None,
    test_pts: int | None = None,
    include_quality: bool = False,
) -> dict:
    """Run get_embedding_batch: warmup (warmup_pts or num_texts), then timed run (test_pts or num_texts).
    Returns count, time_sec, pts_per_sec; if include_quality adds dim, cosine_similar; with resource: cpu_sec."""
    import subprocess

    env = os.environ.copy()
    env["EMBEDDING_BACKEND"] = backend
    env["EMBEDDING_CACHE_SIZE"] = "0"
    for k, v in extra_env.items():
        env[k] = v
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = os.path.join(proj_root, "src") + (os.pathsep + env.get("PYTHONPATH", ""))
    warmup_n = warmup_pts if warmup_pts is not None else num_texts
    test_n = test_pts if test_pts is not None else num_texts

    quality_block = ""
    if include_quality:
        quality_block = """
# Quality: one pair cosine (same model => comparable)
v1 = emb.get_embedding(samples_quality[0])
v2 = emb.get_embedding(samples_quality[1])
def _cos(a, b):
    if len(a) != len(b) or not a: return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    na = sum(x*x for x in a)**0.5
    nb = sum(x*x for x in b)**0.5
    return dot/(na*nb) if na and nb else 0.0
out["dim"] = len(v1)
out["cosine_similar"] = round(_cos(v1, v2), 4)
"""
    samples_repr = repr([RU_SAMPLES[0][0], RU_SAMPLES[0][1]])
    code = f"""
import time, json, resource
from onec_help import embedding as emb

samples_quality = {samples_repr}
flat = [t for pair in {repr(RU_SAMPLES)} for t in pair]
warmup_texts = [flat[i % len(flat)] + f" [w{{i}}]" for i in range({warmup_n})]
test_texts = [flat[i % len(flat)] + f" [t{{i}}]" for i in range({test_n})]

# Warmup (full batch)
emb.get_embedding_batch(warmup_texts)

# Timed run
t0 = time.perf_counter()
vecs = emb.get_embedding_batch(test_texts)
t1 = time.perf_counter()
ru = resource.getrusage(resource.RUSAGE_SELF)
out = {{
    "count": len(vecs) if vecs else 0,
    "time_sec": round(t1 - t0, 3),
    "pts_per_sec": round(len(vecs) / (t1 - t0), 1) if vecs and (t1 - t0) > 0 else 0,
    "cpu_sec": round(ru.ru_utime + ru.ru_stime, 3),
}}
{quality_block}
print(json.dumps(out))
"""
    timeout = 60 + (warmup_n + test_n) // 10
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=max(120, timeout),
            cwd=proj_root,
        )
        if r.returncode != 0:
            return {"error": (r.stderr or r.stdout or "non-zero exit")[:300]}
        return json.loads(r.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"error": f"timeout {max(120, timeout)}s"}
    except Exception as e:
        return {"error": str(e)[:200]}


def main() -> None:
    print("=== Embedding backends benchmark (onec-context-mcp) ===\n")
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
    print("\nDone. Use results to choose EMBEDDING_BACKEND and EMBEDDING_API_URL (see docs/archive/embedding-models-analysis.md).")


def main_compare() -> None:
    """LM Studio vs Ollama with same model (nomic-embed): warmup run then timed run on each."""
    print("=== LM Studio vs Ollama (same model, warm cache) ===\n")
    print(f"Batch size: {BATCH_COMPARE_SIZE} texts. First run = warmup, second = measured.\n")

    model = "nomic-embed-text-v2-moe"
    dim = "768"

    # LM Studio
    print("LM Studio (localhost:1234)")
    ok_lm, _ = probe_url(DEFAULT_LM_STUDIO_URL)
    if not ok_lm:
        print("  Not reachable. Start LM Studio and load nomic-embed.\n")
        res_lm = {"error": "not reachable"}
    else:
        res_lm = run_batch_warmup_timed(
            "openai_api",
            {"EMBEDDING_API_URL": DEFAULT_LM_STUDIO_URL, "EMBEDDING_MODEL": model, "EMBEDDING_DIMENSION": dim},
        )
        if "error" in res_lm:
            print(f"  FAIL: {res_lm['error'][:200]}\n")
        else:
            print(f"  {res_lm['count']} pts in {res_lm['time_sec']} s → {res_lm['pts_per_sec']} pts/s\n")

    # Ollama
    print("Ollama (localhost:11434)")
    ok_ollama, _ = probe_url(DEFAULT_OLLAMA_URL)
    if not ok_ollama:
        print("  Not reachable. Start Ollama and run: ollama pull nomic-embed-text-v2-moe\n")
        res_ollama = {"error": "not reachable"}
    else:
        res_ollama = run_batch_warmup_timed(
            "openai_api",
            {"EMBEDDING_API_URL": DEFAULT_OLLAMA_URL, "EMBEDDING_MODEL": model, "EMBEDDING_DIMENSION": dim},
        )
        if "error" in res_ollama:
            print(f"  FAIL: {res_ollama['error'][:200]}\n")
        else:
            print(f"  {res_ollama['count']} pts in {res_ollama['time_sec']} s → {res_ollama['pts_per_sec']} pts/s\n")

    # Comparison
    print("=== Result ===")
    if "error" in res_lm and "error" in res_ollama:
        print("  Neither backend available. Start LM Studio or Ollama with nomic-embed.")
    elif "error" in res_lm:
        print("  Ollama only: use EMBEDDING_API_URL=http://localhost:11434/v1")
    elif "error" in res_ollama:
        print("  LM Studio only: use EMBEDDING_API_URL=http://localhost:1234/v1")
    else:
        lm_pps = res_lm.get("pts_per_sec") or 0
        ol_pps = res_ollama.get("pts_per_sec") or 0
        if lm_pps > ol_pps:
            faster = "LM Studio"
            ratio = lm_pps / ol_pps if ol_pps else 0
        else:
            faster = "Ollama"
            ratio = ol_pps / lm_pps if lm_pps else 0
        print(f"  LM Studio: {lm_pps} pts/s  |  Ollama: {ol_pps} pts/s")
        print(f"  Faster: {faster} ({ratio:.2f}x)")
    print()


def main_compare_full(
    warmup_pts: int,
    test_pts: int,
    batch_size: int | None = None,
    workers: int | None = None,
) -> None:
    """Сравнение Ollama и LM Studio на прогретом кэше: два прохода (A→B, B→A), отчёт по времени и CPU."""
    model = "nomic-embed-text-v2-moe"
    dim = "768"
    ollama_env = {
        "EMBEDDING_API_URL": DEFAULT_OLLAMA_URL,
        "EMBEDDING_MODEL": model,
        "EMBEDDING_DIMENSION": dim,
    }
    lm_env = {
        "EMBEDDING_API_URL": DEFAULT_LM_STUDIO_URL,
        "EMBEDDING_MODEL": model,
        "EMBEDDING_DIMENSION": dim,
    }
    if batch_size is not None:
        ollama_env["EMBEDDING_BATCH_SIZE"] = str(batch_size)
        lm_env["EMBEDDING_BATCH_SIZE"] = str(batch_size)
    if workers is not None:
        ollama_env["EMBEDDING_WORKERS"] = str(workers)
        lm_env["EMBEDDING_WORKERS"] = str(workers)

    print("=== Ollama vs LM Studio (прогрев + два прохода с переменой порядка) ===\n")
    print(f"Модель: {model}, dim={dim}")
    print(f"Прогрев: {warmup_pts} pts, тестовый батч: {test_pts} pts")
    if batch_size is not None:
        print(f"Очередь: батч по {batch_size} текстов", end="")
        if workers is not None:
            print(f", воркеров (параллельных батчей): {workers}")
        else:
            print()
    else:
        print()

    def run_one(label: str, env: dict) -> dict:
        return run_batch_warmup_timed(
            "openai_api",
            env,
            num_texts=32,
            warmup_pts=warmup_pts,
            test_pts=test_pts,
            include_quality=True,
        )

    results: list[tuple[str, int, dict]] = []  # (backend, run_num, metrics)

    # Проход 1: Ollama
    print("Проход 1: Ollama (прогрев → тест)...")
    r1 = run_one("Ollama", ollama_env)
    if "error" in r1:
        print(f"  Ошибка: {r1['error'][:200]}\n")
        results.append(("Ollama", 1, r1))
    else:
        print(f"  {r1['count']} pts за {r1['time_sec']} s → {r1['pts_per_sec']} pts/s, CPU {r1.get('cpu_sec', 0)} s\n")
        results.append(("Ollama", 1, r1))

    # Проход 2: LM Studio
    print("Проход 2: LM Studio (прогрев → тест)...")
    r2 = run_one("LM Studio", lm_env)
    if "error" in r2:
        print(f"  Ошибка: {r2['error'][:200]}\n")
        results.append(("LM Studio", 2, r2))
    else:
        print(f"  {r2['count']} pts за {r2['time_sec']} s → {r2['pts_per_sec']} pts/s, CPU {r2.get('cpu_sec', 0)} s\n")
        results.append(("LM Studio", 2, r2))

    # Проход 3: LM Studio снова (перемена порядка)
    print("Проход 3: LM Studio (прогрев → тест, повтор)...")
    r3 = run_one("LM Studio", lm_env)
    if "error" in r3:
        print(f"  Ошибка: {r3['error'][:200]}\n")
        results.append(("LM Studio", 3, r3))
    else:
        print(f"  {r3['count']} pts за {r3['time_sec']} s → {r3['pts_per_sec']} pts/s, CPU {r3.get('cpu_sec', 0)} s\n")
        results.append(("LM Studio", 3, r3))

    # Проход 4: Ollama снова
    print("Проход 4: Ollama (прогрев → тест, повтор)...")
    r4 = run_one("Ollama", ollama_env)
    if "error" in r4:
        print(f"  Ошибка: {r4['error'][:200]}\n")
        results.append(("Ollama", 4, r4))
    else:
        print(f"  {r4['count']} pts за {r4['time_sec']} s → {r4['pts_per_sec']} pts/s, CPU {r4.get('cpu_sec', 0)} s\n")
        results.append(("Ollama", 4, r4))

    # Таблица и итог
    print("=== Результаты ===")
    print(f"{'Бэкенд':<12} {'Проход':<6} {'Время (с)':<10} {'pts/s':<10} {'CPU (с)':<10} {'dim':<6} {'cosine':<8}")
    print("-" * 70)
    for backend, run_num, data in results:
        if "error" in data:
            print(f"{backend:<12} {run_num:<6} ERROR: {data['error'][:40]}")
        else:
            t = data.get("time_sec", 0)
            pps = data.get("pts_per_sec", 0)
            cpu = data.get("cpu_sec", 0)
            d = data.get("dim", "")
            cos = data.get("cosine_similar", "")
            print(f"{backend:<12} {run_num:<6} {t:<10.3f} {pps:<10.1f} {cpu:<10.3f} {d!s:<6} {cos!s:<8}")

    ok = [d for _, _, d in results if "error" not in d]
    if len(ok) < 2:
        print("\nНедостаточно успешных прогонов для сравнения.")
        return

    ollama_runs = [d for b, _, d in results if b == "Ollama" and "error" not in d]
    lm_runs = [d for b, _, d in results if b == "LM Studio" and "error" not in d]

    def avg_pps(runs: list) -> float:
        if not runs:
            return 0.0
        return sum(d.get("pts_per_sec") or 0 for d in runs) / len(runs)

    def avg_time(runs: list) -> float:
        if not runs:
            return 0.0
        return sum(d.get("time_sec") or 0 for d in runs) / len(runs)

    def avg_cpu(runs: list) -> float:
        if not runs:
            return 0.0
        return sum(d.get("cpu_sec") or 0 for d in runs) / len(runs)

    o_pps = avg_pps(ollama_runs)
    l_pps = avg_pps(lm_runs)
    o_time = avg_time(ollama_runs)
    l_time = avg_time(lm_runs)
    o_cpu = avg_cpu(ollama_runs)
    l_cpu = avg_cpu(lm_runs)

    print("\n--- Итог (среднее по проходам) ---")
    print(f"  Ollama:    {o_pps:.1f} pts/s, время {o_time:.2f} s, CPU {o_cpu:.2f} s")
    print(f"  LM Studio: {l_pps:.1f} pts/s, время {l_time:.2f} s, CPU {l_cpu:.2f} s")
    if o_pps > 0 and l_pps > 0:
        faster = "Ollama" if o_pps > l_pps else "LM Studio"
        ratio = max(o_pps, l_pps) / min(o_pps, l_pps)
        print(f"  Быстрее: {faster} ({ratio:.2f}x по pts/s)")
    if o_cpu > 0 or l_cpu > 0:
        less_cpu = "Ollama" if o_cpu < l_cpu else "LM Studio"
        print(f"  Меньше нагрузка CPU (клиент): {less_cpu}")
    print()


def main_compare_variants(warmup_pts: int, test_pts: int) -> None:
    """Несколько комбинаций batch×workers на прогретом кэше, один прогон на бэкенд; итоговая таблица и победитель."""
    model = "nomic-embed-text-v2-moe"
    dim = "768"
    variants = [
        ("batch=150 workers=6", 150, 6),
        ("batch=100 workers=1", 100, 1),
        ("batch=32 workers=6", 32, 6),
        ("batch=50 workers=8", 50, 8),
        ("batch=5 workers=50", 5, 50),
    ]
    results: list[tuple[str, dict, dict]] = []  # (variant_name, ollama_metrics, lm_metrics)

    print("=== Сравнение комбинаций batch × workers (прогрев, один прогон на бэкенд) ===\n")
    print(f"Модель: {model}, прогрев: {warmup_pts} pts, тест: {test_pts} pts\n")

    for name, batch_size, workers in variants:
        print(f"--- {name} ---")
        ollama_env = {
            "EMBEDDING_API_URL": DEFAULT_OLLAMA_URL,
            "EMBEDDING_MODEL": model,
            "EMBEDDING_DIMENSION": dim,
            "EMBEDDING_BATCH_SIZE": str(batch_size),
            "EMBEDDING_WORKERS": str(workers),
        }
        lm_env = {
            "EMBEDDING_API_URL": DEFAULT_LM_STUDIO_URL,
            "EMBEDDING_MODEL": model,
            "EMBEDDING_DIMENSION": dim,
            "EMBEDDING_BATCH_SIZE": str(batch_size),
            "EMBEDDING_WORKERS": str(workers),
        }
        ro = run_batch_warmup_timed(
            "openai_api", ollama_env,
            warmup_pts=warmup_pts, test_pts=test_pts,
            include_quality=False,
        )
        rl = run_batch_warmup_timed(
            "openai_api", lm_env,
            warmup_pts=warmup_pts, test_pts=test_pts,
            include_quality=False,
        )
        results.append((name, ro, rl))
        o_pps = ro.get("pts_per_sec", 0) if "error" not in ro else 0
        l_pps = rl.get("pts_per_sec", 0) if "error" not in rl else 0
        print(f"  Ollama: {o_pps} pts/s" if "error" not in ro else f"  Ollama: {ro.get('error', '')[:50]}")
        print(f"  LM Studio: {l_pps} pts/s" if "error" not in rl else f"  LM Studio: {rl.get('error', '')[:50]}")
        print()

    print("=== Итоговая таблица (pts/s) ===")
    print(f"{'Комбинация':<22} {'Ollama':<12} {'LM Studio':<12} {'Лучше':<10}")
    print("-" * 58)
    best_ollama = 0.0
    best_lm = 0.0
    best_combo_ollama = ""
    best_combo_lm = ""
    for name, ro, rl in results:
        o_pps = ro.get("pts_per_sec", 0) if "error" not in ro else 0
        l_pps = rl.get("pts_per_sec", 0) if "error" not in rl else 0
        better = "Ollama" if o_pps >= l_pps else "LM Studio"
        print(f"{name:<22} {o_pps:<12.1f} {l_pps:<12.1f} {better:<10}")
        if o_pps > best_ollama:
            best_ollama = o_pps
            best_combo_ollama = name
        if l_pps > best_lm:
            best_lm = l_pps
            best_combo_lm = name

    print("\n--- Победитель ---")
    best_overall = 0.0
    for _, ro, rl in results:
        o = ro.get("pts_per_sec", 0) or 0 if "error" not in ro else 0
        loc = rl.get("pts_per_sec", 0) or 0 if "error" not in rl else 0
        best_overall = max(best_overall, o, loc)
    for name, ro, rl in results:
        o_pps = ro.get("pts_per_sec", 0) if "error" not in ro else 0
        l_pps = rl.get("pts_per_sec", 0) if "error" not in rl else 0
        if max(o_pps, l_pps) == best_overall:
            winner = "Ollama" if o_pps >= l_pps else "LM Studio"
            print(f"  Лучшая скорость: {winner} при {name} ({best_overall:.1f} pts/s)")
            break
    print(f"  Лучшая комбинация для Ollama: {best_combo_ollama} ({best_ollama:.1f} pts/s)")
    print(f"  Лучшая комбинация для LM Studio: {best_combo_lm} ({best_lm:.1f} pts/s)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark embedding backends (Ollama, LM Studio, local, deterministic).")
    parser.add_argument("--compare", action="store_true", help="LM Studio vs Ollama, один батч 32 pts (warm cache)")
    parser.add_argument("--compare-full", action="store_true", help="Прогрев + два прохода Ollama/LM Studio, отчёт")
    parser.add_argument("--compare-variants", action="store_true", help="Несколько комбинаций batch×workers, таблица и победитель")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP_PTS, help=f"Размер батча прогрева (default {DEFAULT_WARMUP_PTS})")
    parser.add_argument("--test", type=int, default=DEFAULT_TEST_PTS, help=f"Размер тестового батча (default {DEFAULT_TEST_PTS})")
    parser.add_argument("--batch-size", type=int, default=None, help="EMBEDDING_BATCH_SIZE (размер очереди батча: 100, 150, …; default — из env или 32)")
    parser.add_argument("--workers", type=int, default=None, help="EMBEDDING_WORKERS (параллельных батчей в очереди; default — из env или 2)")
    args = parser.parse_args()

    if args.compare_variants:
        main_compare_variants(warmup_pts=args.warmup, test_pts=args.test)
    elif args.compare_full:
        main_compare_full(
            warmup_pts=args.warmup,
            test_pts=args.test,
            batch_size=args.batch_size,
            workers=args.workers,
        )
    elif args.compare:
        main_compare()
    else:
        main()
