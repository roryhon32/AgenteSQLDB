"""
benchmark_llm.py — Benchmark comparativo de modelos locais Ollama para Text-to-SQL Milia AI.
Mede acurácia (resultado vs SQL de referência), latência (p50/p95) e taxa de tokens/s.
Descarta o primeiro call (aquecimento de memória).
"""

import duckdb
import json
import time
import statistics
import urllib.request
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB_PATH = Path("data/banco.duckdb").resolve()
OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"

# 25 Perguntas com queries de referência escritas à mão
BENCHMARK_SUITE = [
    {
        "id": 1,
        "question": "qual foi o faturamento de agosto 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2026 AND \"Mês\" = 'ago';"
    },
    {
        "id": 2,
        "question": "qual o faturamento de agosto de 2025",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2025 AND \"Mês\" = 'ago';"
    },
    {
        "id": 3,
        "question": "qual o faturamento total em 2025",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2025;"
    },
    {
        "id": 4,
        "question": "qual o faturamento total em 2024",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2024;"
    },
    {
        "id": 5,
        "question": "faturamento de janeiro de 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2026 AND \"Mês\" = 'jan';"
    },
    {
        "id": 6,
        "question": "faturamento de março de 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2026 AND \"Mês\" = 'mar';"
    },
    {
        "id": 7,
        "question": "qual foi a receita no mês de maio de 2025",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2025 AND \"Mês\" = 'mai';"
    },
    {
        "id": 8,
        "question": "faturamento de dezembro de 2023",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2023 AND \"Mês\" = 'dez';"
    },
    {
        "id": 9,
        "question": "quais os 5 maiores clientes em faturamento",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Nome Cliente\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Nome Cliente\" IS NOT NULL AND \"Nome Cliente\" != '' GROUP BY \"Nome Cliente\" ORDER BY faturamento DESC LIMIT 5;"
    },
    {
        "id": 10,
        "question": "top 10 clientes com maior faturamento",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Nome Cliente\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Nome Cliente\" IS NOT NULL AND \"Nome Cliente\" != '' GROUP BY \"Nome Cliente\" ORDER BY faturamento DESC LIMIT 10;"
    },
    {
        "id": 11,
        "question": "quais os 3 clientes que mais faturaram em 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Nome Cliente\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2026 AND \"Nome Cliente\" IS NOT NULL AND \"Nome Cliente\" != '' GROUP BY \"Nome Cliente\" ORDER BY faturamento DESC LIMIT 3;"
    },
    {
        "id": 12,
        "question": "qual o faturamento por Unidade de Negócio",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Business Unit\", ROUND(SUM(\"Fat. Líquido\"), 2) AS total_faturamento FROM faturamento WHERE \"Business Unit\" IS NOT NULL GROUP BY \"Business Unit\" ORDER BY total_faturamento DESC;"
    },
    {
        "id": 13,
        "question": "qual o faturamento da BU Varejo em 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Business Unit\" ILIKE '%Varejo%' AND \"Ano\" = 2026;"
    },
    {
        "id": 14,
        "question": "qual o faturamento da Unidade de Negócio Corporativo",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Business Unit\" ILIKE '%Corporativo%';"
    },
    {
        "id": 15,
        "question": "qual o faturamento por estado",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Estado\", ROUND(SUM(\"Fat. Líquido\"), 2) AS total_faturamento FROM faturamento WHERE \"Estado\" IS NOT NULL AND \"Estado\" != '' GROUP BY \"Estado\" ORDER BY total_faturamento DESC LIMIT 10;"
    },
    {
        "id": 16,
        "question": "qual o faturamento no estado de SP em 2025",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Estado\" = 'SP' AND \"Ano\" = 2025;"
    },
    {
        "id": 17,
        "question": "top 5 vendedores por faturamento",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Nome Vendedor\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Nome Vendedor\" IS NOT NULL AND \"Nome Vendedor\" != '' GROUP BY \"Nome Vendedor\" ORDER BY faturamento DESC LIMIT 5;"
    },
    {
        "id": 18,
        "question": "qual o vendedor que mais vendeu em 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT \"Nome Vendedor\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2026 AND \"Nome Vendedor\" IS NOT NULL AND \"Nome Vendedor\" != '' GROUP BY \"Nome Vendedor\" ORDER BY faturamento DESC LIMIT 1;"
    },
    {
        "id": 19,
        "question": "qual o faturamento por produto",
        "expected_type": "sql",
        "ref_sql": "SELECT \"PRODUTOS\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"PRODUTOS\" IS NOT NULL AND \"PRODUTOS\" != '' GROUP BY \"PRODUTOS\" ORDER BY faturamento DESC LIMIT 10;"
    },
    {
        "id": 20,
        "question": "top 5 produtos mais vendidos em 2025",
        "expected_type": "sql",
        "ref_sql": "SELECT \"PRODUTOS\", ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"Ano\" = 2025 AND \"PRODUTOS\" IS NOT NULL AND \"PRODUTOS\" != '' GROUP BY \"PRODUTOS\" ORDER BY faturamento DESC LIMIT 5;"
    },
    {
        "id": 21,
        "question": "qual a margem bruta por produto",
        "expected_type": "sql",
        "ref_sql": "SELECT \"PRODUTOS\", ROUND(SUM(\"Margem Bruta (R$)\"), 2) AS margem_bruta, ROUND(SUM(\"Fat. Líquido\"), 2) AS faturamento FROM faturamento WHERE \"PRODUTOS\" IS NOT NULL AND \"PRODUTOS\" != '' GROUP BY \"PRODUTOS\" ORDER BY margem_bruta DESC LIMIT 10;"
    },
    {
        "id": 22,
        "question": "qual a margem bruta total em 2026",
        "expected_type": "sql",
        "ref_sql": "SELECT ROUND(SUM(\"Margem Bruta (R$)\"), 2) AS margem_bruta FROM faturamento WHERE \"Ano\" = 2026;"
    },
    {
        "id": 23,
        "question": "qual o salário dos funcionários da empresa",
        "expected_type": "schema_insufficient",
        "ref_sql": None
    },
    {
        "id": 24,
        "question": "qual a idade média e cargo dos clientes",
        "expected_type": "schema_insufficient",
        "ref_sql": None
    },
    {
        "id": 25,
        "question": "qual o saldo de estoque atual no almoxarifado",
        "expected_type": "schema_insufficient",
        "ref_sql": None
    }
]


def load_lean_prompt() -> str:
    from src.sql_agent.v2.agent import _SYSTEM_PROMPT
    from src.sql_agent.v2.database import fetch_database_schema
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    schema = fetch_database_schema(conn, lean=True)
    conn.close()
    return _SYSTEM_PROMPT.replace("{schema}", schema)


def call_ollama(model: str, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Pergunta do usuário: {user_prompt}\n\nGere o JSON:"}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": 300,
            "num_thread": 6
        },
        "keep_alive": "30m"
    }

    t0 = time.perf_counter()
    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    t1 = time.perf_counter()

    latency = t1 - t0
    eval_count = res.get("eval_count", 0)
    eval_duration = res.get("eval_duration", 1) / 1e9  # em segundos
    tokens_per_sec = eval_count / eval_duration if eval_duration > 0 else 0.0

    return {
        "content": res.get("message", {}).get("content", "").strip(),
        "latency": latency,
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec
    }


def parse_and_validate(raw_text: str, item: Dict[str, Any], conn: duckdb.DuckDBPyConnection) -> bool:
    from src.sql_agent.v2.agent import _extract_plan, _sanitize_generated_sql

    if item["expected_type"] == "schema_insufficient":
        return "SCHEMA_INSUFICIENTE" in raw_text.upper() or "schema_insufficient" in raw_text.lower()

    # Espera SQL
    if "SCHEMA_INSUFICIENTE" in raw_text.upper():
        return False

    plan = _extract_plan(raw_text)
    gen_sql = plan.get("sql", "")
    if not gen_sql:
        return False

    gen_sql = _sanitize_generated_sql(gen_sql)

    try:
        # Executa a query de referência e a query gerada
        ref_rows = conn.execute(item["ref_sql"]).fetchall()
        gen_rows = conn.execute(gen_sql).fetchall()

        # Compara resultados
        if not ref_rows and not gen_rows:
            return True
        if len(ref_rows) != len(gen_rows):
            return False

        # Compara primeira linha numérica
        r1, g1 = ref_rows[0], gen_rows[0]
        # Se for agregação de 1 valor
        if len(r1) == 1 and len(g1) == 1:
            try:
                return abs(float(r1[0]) - float(g1[0])) < 1.0
            except Exception:
                return r1[0] == g1[0]

        # Compara formato geral
        return True
    except Exception as e:
        return False


def run_benchmark(models: List[str]):
    print(f"Iniciando Benchmark com {len(BENCHMARK_SUITE)} perguntas...")
    system_prompt = load_lean_prompt()
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    results_table = []

    for model in models:
        print(f"\n==========================================")
        print(f"Testando Modelo: {model}")
        print(f"==========================================")

        # Aquecimento (Warm-up) descartado
        print("Aquecendo modelo (descartando 1ª chamada)...")
        try:
            call_ollama(model, system_prompt, "qual foi o faturamento total em 2025")
            print("Aquecimento OK.")
        except Exception as e:
            print(f"Erro no aquecimento do modelo {model}: {e}")
            continue

        latencies = []
        tokens_per_sec_list = []
        correct_count = 0

        for item in BENCHMARK_SUITE:
            q_id = item["id"]
            question = item["question"]
            print(f"[{model}] P{q_id:02d}: {question[:45]}...", end=" ", flush=True)

            try:
                res = call_ollama(model, system_prompt, question)
                lat = res["latency"]
                tps = res["tokens_per_sec"]
                latencies.append(lat)
                tokens_per_sec_list.append(tps)

                is_correct = parse_and_validate(res["content"], item, conn)
                if is_correct:
                    correct_count += 1
                    status = "OK"
                else:
                    status = "FAIL"

                print(f"-> {status} ({lat:.2f}s | {tps:.1f} tok/s)")
            except Exception as e:
                print(f"-> ERRO: {e}")
                latencies.append(10.0)

        accuracy_pct = (correct_count / len(BENCHMARK_SUITE)) * 100
        p50 = statistics.median(latencies) if latencies else 0.0
        # p95 aproximado
        sorted_lat = sorted(latencies)
        idx_p95 = int(0.95 * len(sorted_lat))
        p95 = sorted_lat[min(idx_p95, len(sorted_lat) - 1)] if sorted_lat else 0.0
        avg_tps = statistics.mean(tokens_per_sec_list) if tokens_per_sec_list else 0.0

        summary = {
            "model": model,
            "accuracy": f"{accuracy_pct:.1f}% ({correct_count}/{len(BENCHMARK_SUITE)})",
            "p50_s": f"{p50:.2f}s",
            "p95_s": f"{p95:.2f}s",
            "tokens_sec": f"{avg_tps:.1f}"
        }
        results_table.append(summary)
        print(f"\nResumo para {model}: Acurácia={summary['accuracy']} | p50={summary['p50_s']} | p95={summary['p95_s']} | Vel={summary['tokens_sec']} tok/s")

    conn.close()

    print("\n\n==========================================")
    print("TABELA CONSOLIDADA DE BENCHMARK")
    print("==========================================")
    print(f"| Modelo | Acurácia (25 Qs) | Latência p50 | Latência p95 | Tokens/s |")
    print(f"| :--- | :---: | :---: | :---: | :---: |")
    for r in results_table:
        print(f"| {r['model']} | {r['accuracy']} | {r['p50_s']} | {r['p95_s']} | {r['tokens_sec']} |")

    return results_table


if __name__ == "__main__":
    import sys
    models_to_test = sys.argv[1:] if len(sys.argv) > 1 else ["qwen2.5-coder:1.5b", "qwen2.5-coder:3b"]
    run_benchmark(models_to_test)

