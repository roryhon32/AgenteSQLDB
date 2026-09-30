"""
main.py — Ponto de entrada interativo do AgenteSQL v2.

Pipeline: Pergunta → SQL (LLM) → Execução DuckDB → Síntese analítica (LLM)
Backend LLM: Ollama (local) ou OpenAI — configurado em config.yaml / .env
"""

from __future__ import annotations

import sys

from src.sql_agent.v2.config import settings
from src.sql_agent.v2.database import DatabaseManager
from src.sql_agent.v2.agent import AnalyticalAgent, AnalyticalResult


# ---------------------------------------------------------------------------
# Exibição
# ---------------------------------------------------------------------------

def print_banner(agent: AnalyticalAgent) -> None:
    backend_label = (
        f"Ollama  ({settings.ollama_model})"
        if settings.llm_backend == "ollama"
        else f"OpenAI  ({settings.openai_model})"
    )
    schema_text = agent.get_schema()

    print("=" * 65)
    print("           AGENTE ANALÍTICO TEXT-TO-SQL  (v2)")
    print("=" * 65)
    print(f"Backend LLM   : {backend_label}")
    print(f"Banco DuckDB  : {settings.db_path}")
    print(f"Max rows (LLM): {settings.max_rows_context}")
    print()
    print("Schema carregado:")
    for line in schema_text.splitlines():
        print("  " + line)
    print()
    print("Comandos disponíveis:")
    print("  sair      — Encerrar o agente")
    print("  limpar    — Reiniciar a memória da conversa")
    print("  historico — Exibir histórico de interações")
    print("-" * 65)


def display_result(result: AnalyticalResult) -> None:
    """Exibe o resultado completo de uma interação."""

    # --- SQL Gerado ---
    print("\n" + "-" * 40)
    print("SQL GERADO:")
    print("-" * 40)
    if result.sql:
        print(result.sql)
    else:
        print("(nenhum SQL gerado)")

    if result.retries > 0:
        print(f"\n[Auto-recuperação: {result.retries} tentativa(s) de correção]")

    # --- Resultado da Execução ---
    if result.execution_result:
        exec_res = result.execution_result
        if exec_res.success and exec_res.row_count > 0:
            print("\n" + "-" * 40)
            print(f"DADOS RETORNADOS ({exec_res.row_count} registro(s)):")
            print("-" * 40)
            # Largura de coluna adaptativa
            cols = exec_res.columns
            rows = exec_res.rows[:settings.max_rows_context]
            widths = [len(c) for c in cols]
            for row in rows:
                for i, val in enumerate(row):
                    widths[i] = max(widths[i], len(str(val)))
            header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
            print(header)
            print("-" * len(header))
            for row in rows:
                print(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))
            if exec_res.row_count > settings.max_rows_context:
                print(f"... ({exec_res.row_count - settings.max_rows_context} registros adicionais não exibidos)")

    # --- Análise / Erro ---
    print("\n" + "-" * 40)
    if result.success:
        print("ANÁLISE:")
        print("-" * 40)
        print(result.analysis if result.analysis else "(sem análise)")
    else:
        print("ERRO:")
        print("-" * 40)
        print(result.error)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    # Inicializa banco e agente
    try:
        db = DatabaseManager(db_path=settings.db_path, auto_seed=True)
        agent = AnalyticalAgent(db=db, settings=settings)
    except Exception as exc:
        print(f"\n[ERRO DE INICIALIZAÇÃO] {exc}\n")
        sys.exit(1)

    print_banner(agent)

    while True:
        try:
            turns = agent.memory_turns_count
            mem_label = f" [memória: {turns} turno(s)]" if turns > 0 else ""
            prompt_label = f"\nPergunta{mem_label}: "

            pergunta = input(prompt_label).strip()
            if not pergunta:
                continue

            cmd = pergunta.lower()

            if cmd in {"sair", "exit", "quit", "q"}:
                print("\nEncerrando. Até logo!")
                break

            if cmd in {"limpar", "clear", "reset"}:
                agent.clear_memory()
                print("\n[Memória reiniciada.]")
                continue

            if cmd in {"historico", "history"}:
                print("\n" + "=" * 40)
                print("HISTÓRICO EM MEMÓRIA:")
                print("=" * 40)
                print(agent.memory.get_history_text())
                continue

            print("\nProcessando...")
            resultado = agent.process_query(pergunta)
            display_result(resultado)

        except KeyboardInterrupt:
            print("\n\nInterrompido pelo usuário.")
            break
        except Exception as exc:
            print(f"\n[ERRO INESPERADO] {exc}")

    db.close()


if __name__ == "__main__":
    main()
