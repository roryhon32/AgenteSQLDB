# Módulo Antigo (V1) - AgenteSQL

Esta pasta reúne a implementação **V1** original do pipeline Text-to-SQL:

- **`services/`**: Agentes originais (`InterpreterAgent`, `SQLGeneratorAgent`, `SQLAgentOrchestrator`).
- **`prompts/`**: Templates de prompt da V1.
- **`database/`**: Catálogo de schema e executor DuckDB em memória com mock de dados.
- **`utils/`**: Validador de segurança `SQLSecurityValidator` inicial.

> **Importante:**
> A versão oficial de produção do projeto corporativo é a **V2**, localizada em [`src/sql_agent/v2/`](../v2/) e executada através do servidor web em [`app.py`](../../../app.py).
