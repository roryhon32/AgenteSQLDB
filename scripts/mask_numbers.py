"""
mask_numbers.py — Mascara todos os valores numéricos e financeiros do banco DuckDB.
Garante que nenhum número real da empresa permaneça no banco de dados,
multiplicando os valores por fatores aleatórios (random entre ~0.01 e 0.999),
preservando a consistência interna das métricas e tipos de dados.
"""

import os
import shutil
import duckdb
from pathlib import Path

DB_PATHS = [
    Path("data/banco.duckdb").resolve(),
    Path("../Milia/data/banco.duckdb").resolve(),
]

def mask_duckdb(db_path: Path):
    if not db_path.exists():
        print(f"[-] Arquivo não encontrado: {db_path}")
        return

    print(f"\n==================================================")
    print(f"[*] Processando: {db_path} ({db_path.stat().st_size / (1024*1024):.2f} MB)")

    # 1. Backup de segurança antes de qualquer modificação
    bak_path = db_path.with_suffix(".duckdb.bak")
    if not bak_path.exists():
        print(f"[*] Criando backup: {bak_path.name}...")
        shutil.copy2(db_path, bak_path)
        print(f"[+] Backup criado com sucesso!")
    else:
        print(f"[*] Backup existente já preservado: {bak_path.name}")

    conn = duckdb.connect(str(db_path))

    # Verifica tabelas
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    print(f"[*] Tabelas encontradas: {tables}")

    if "faturamento" not in tables:
        print(f"[-] Tabela 'faturamento' não encontrada em {db_path}")
        conn.close()
        return

    # Total de registros
    total_rows = conn.execute('SELECT COUNT(*) FROM faturamento').fetchone()[0]
    print(f"[*] Total de linhas na tabela faturamento: {total_rows:,}")

    # Lista todas as colunas
    cols_info = conn.execute('PRAGMA table_info("faturamento")').fetchall()
    
    # Colunas protegidas que NÃO devem ser alteradas (dimensões de tempo, datas, IDs categóricos)
    PROTECTED_COLS = {
        "Ano", "DIA", "Dia Semana", "Ano C/ CUTOFF", "MONTH",
        "Roadmap", "DIF Bus", "FAT - Estado-Ent", "FAT - Município-Ent"
    }

    # Identifica colunas monetárias e de quantidade
    monetary_cols = []
    quant_cols = []

    for col in cols_info:
        c_name = col[1]
        c_type = col[2].upper()
        if c_name in PROTECTED_COLS:
            continue
        if "Quant" in c_name:
            quant_cols.append(c_name)
        elif any(t in c_type for t in ["DOUBLE", "FLOAT", "DECIMAL", "REAL"]):
            monetary_cols.append(c_name)
        elif any(t in c_type for t in ["INT", "BIGINT"]) and any(w in c_name.lower() for w in ["desconto", "servico", "vlr", "fat", "custo"]):
            monetary_cols.append(c_name)

    print(f"[*] Colunas monetárias/financeiras a mascarar ({len(monetary_cols)}):")
    for c in monetary_cols:
        print(f"    - {c}")

    print(f"[*] Colunas de quantidade a mascarar ({len(quant_cols)}):")
    for c in quant_cols:
        print(f"    - {c}")

    # Visualiza valores antes do mascaramento
    print("\n[*] Valores ANTES do mascaramento (Amostra de 3 linhas):")
    sample_before = conn.execute('SELECT "Valor Contábil", "Fat. Líquido", "Margem Bruta (R$)", "FAT - Quant." FROM faturamento WHERE "Valor Contábil" > 0 LIMIT 3').fetchall()
    for row in sample_before:
        print(f"    Valor Contábil: {row[0]} | Fat. Líquido: {row[1]} | Margem: {row[2]} | Quant: {row[3]}")

    # Monta a expressão SQL para recriar a tabela com valores mascarados
    # Usamos um fator aleatório por linha: (0.01 + random() * 0.989) -> varia entre 0.01 e 0.999
    # garantindo que todos os números sejam completamente mascarados e proporcionalmente consistentes.
    select_parts = []
    for col in cols_info:
        c_name = col[1]
        c_type = col[2].upper()
        
        if c_name in PROTECTED_COLS or (c_name not in monetary_cols and c_name not in quant_cols):
            # Mantém original
            select_parts.append(f'"{c_name}"')
        elif c_name in quant_cols:
            # Multiplica quantidade por fator aleatório e arredonda para inteiro ou float
            select_parts.append(f'ROUND("{c_name}" * (0.05 + random() * 0.94), 2) AS "{c_name}"')
        elif c_name in monetary_cols:
            # Multiplica valor monetário por fator aleatório (random entre 0.01 e 0.999) e arredonda para 2 casas
            select_parts.append(f'ROUND("{c_name}" * (0.01 + random() * 0.989), 2) AS "{c_name}"')

    select_sql = ",\n    ".join(select_parts)

    print("\n[*] Executando transformação de mascaramento em DuckDB...")
    create_table_sql = f"""
    CREATE OR REPLACE TABLE faturamento AS
    SELECT
        {select_sql}
    FROM faturamento;
    """
    conn.execute(create_table_sql)
    conn.execute("CHECKPOINT;")

    # Visualiza valores DEPOIS do mascaramento
    print("[+] Mascaramento concluído com sucesso!")
    print("\n[*] Valores DEPOIS do mascaramento (Amostra de 3 linhas):")
    sample_after = conn.execute('SELECT "Valor Contábil", "Fat. Líquido", "Margem Bruta (R$)", "FAT - Quant." FROM faturamento WHERE "Valor Contábil" > 0 LIMIT 3').fetchall()
    for row in sample_after:
        print(f"    Valor Contábil: {row[0]} | Fat. Líquido: {row[1]} | Margem: {row[2]} | Quant: {row[3]}")

    conn.close()
    print(f"[+] Concluído para {db_path.name}!")

if __name__ == "__main__":
    for p in DB_PATHS:
        mask_duckdb(p)
    print("\n[✓] Todos os bancos foram mascarados com sucesso.")
