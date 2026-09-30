<div align="center">

# Milia AI

**Intelligent SQL Agent — Transforme perguntas em linguagem natural em consultas SQL controladas**

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.3-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)](https://www.langchain.com/)
[![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=for-the-badge&logo=groq&logoColor=white)](https://groq.com/)
[![GitHub Models](https://img.shields.io/badge/GitHub%20Models-gpt--4o--mini%20(Fallback)-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/marketplace/models)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.5-FFF000?style=for-the-badge&logo=duckdb&logoColor=black)](https://duckdb.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

*Milia AI é um agente Text-to-SQL desenvolvido para transformar perguntas em linguagem natural em consultas SQL controladas, mantendo a execução dos dados isolada do modelo de linguagem.*

</div>

---

## Sobre o Projeto

**Milia AI** é um sistema de agentes especializados que converte perguntas em português natural em consultas SQL válidas para [DuckDB](https://duckdb.org/), com foco em **segurança**, **isolamento de dados** e **auditabilidade**.

### Arquitetura do Pipeline

```
USUÁRIO
   │
   ▼
SCOPE GUARDRAIL
(Validação de Escopo + Anti Prompt Injection)
   │
   ▼
AGENTE ANALÍTICO
(Interpretação + Geração SQL via LLM)
   │
   ├── LLM recebe apenas: Schema estrutural (nomes de tabelas/colunas)
   │   LLM NÃO recebe: Registros, valores ou dados reais do banco
   │
   ▼
RLS ENFORCER
(Isolamento por Unidade de Negócio)
   │
   ▼
SQL GUARDRAIL
(Validação AST + Read-only enforcement)
   │
   ▼
DUCKDB EXECUTOR
(Execução segura em ambiente isolado)
   │
   ▼
AUDIT LOGGER
(Trilha de auditoria imutável com SHA-256)
   │
   ▼
RESULTADO FORMATADO
```

> **Privacy-oriented architecture:** O LLM recebe apenas o contexto estrutural (schema) necessário para gerar a consulta. Os dados reais permanecem completamente isolados no ambiente controlado da aplicação.

---

## Tecnologias

| Componente | Tecnologia | Função |
|---|---|---|
| **LLM Principal** | GroqCloud — `llama-3.3-70b-versatile` | Geração ultra-rápida de SQL e análise (LPU) |
| **LLM Fallback** | GitHub Models — `gpt-4o-mini` | Failover automático em rate limit ou indisponibilidade |
| **Orquestração** | LangChain 0.3.x | Encadeamento de agentes e prompts |
| **Engine SQL** | DuckDB 1.5.x | Execução analítica colunar em memória |
| **Backend API** | FastAPI | REST API + Autenticação JWT |
| **Auth DB** | SQLite | Gestão de usuários, permissões e auditoria |
| **Frontend** | HTML/CSS/JavaScript + GSAP 3 | SPA com transições cinematográficas |

---

## Arquitetura de Segurança

### Defesa em Profundidade

| Camada | Mecanismo | Proteção |
|---|---|---|
| **Scope Guardrail** | Regex + padrões de injeção | Prompt injection, jailbreak, temas fora do domínio |
| **LLM Context** | Schema-only context | O LLM nunca vê registros reais |
| **RLS Enforcer** | Isolamento por BU | Usuário acessa apenas sua Unidade de Negócio |
| **SQL Guardrail** | AST Analysis (sqlglot) | Apenas SELECT/WITH, blocklist de DDL/DML |
| **DuckDB Connection** | Read-only mode | Impossível escrever ou modificar dados |
| **Rate Limiter** | Sliding window (30 req/min) | Proteção contra abuso |
| **Circuit Breaker** | Auto-suspend em violações | Suspensão temporária após anomalias repetidas |
| **Audit Trail** | SHA-256 hash chain | Auditoria imutável e verificável |
| **PII Redactor** | Mascaramento dinâmico | Proteção de dados pessoais nos logs |

### Controle de Acesso

```
READ-ONLY DATA ACCESS
├── Apenas SELECT e WITH...SELECT são permitidos
├── INSERT, UPDATE, DELETE, DROP, ALTER → Bloqueados
├── Múltiplos statements → Bloqueados
├── Colunas e tabelas não autorizadas → Bloqueadas
└── Acesso isolado por Unidade de Negócio (RLS)
```

---

## Funcionalidades

### Text-to-SQL com Guardrails
- Transforma perguntas em linguagem natural em SQL DuckDB seguro
- Entende linguagem comercial informal ("quem está parando de comprar?")
- Aplica regras de negócio automaticamente (clientes em risco, ranking)
- Fallback automático para recuperação de queries com erro

### Memória Conversacional
- Sliding window de 5 turnos
- Suporte a perguntas de follow-up ("e agora filtre por São Paulo")

### Alta Disponibilidade de LLM
- GroqCloud como provedor principal (LPU — baixíssima latência)
- GitHub Models como fallback automático (sem interrupção ao usuário)

### Plataforma Web Completa
- Interface chat conversacional responsiva
- Autenticação JWT com cookies HttpOnly
- Gestão de usuários com aprovação por administrador
- Central de monitoramento com métricas Prometheus
- Trilha de auditoria com incidentes de segurança
- Painel de segurança com alertas em tempo real

---

## Início Rápido

### Pré-requisitos

- Python 3.13+
- Chave de API da **GroqCloud** (`GROQ_API_KEY`) e/ou Token do **GitHub** (`GITHUB_TOKEN`)

### Instalação

```bash
# Clone o repositório
git clone https://github.com/roryhon32/AgenteSql.git
cd AgenteSql

# Crie e ative o ambiente virtual
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

# Instale as dependências
pip install -r requirements.txt

# Configure as credenciais
cp .env.example .env
# Edite .env com suas chaves de API
```

### Variáveis de Ambiente

```env
# LLM Principal (GroqCloud)
GROQ_API_KEY=gsk_suachaveaqui
GROQ_MODEL=llama-3.3-70b-versatile

# LLM Fallback (GitHub Models)
GITHUB_TOKEN=ghp_seutokenaqui
GITHUB_MODEL=gpt-4o-mini
```

### Executar

```bash
# Servidor Web (Interface completa)
uvicorn app:app --port 8000 --reload
# Acesse: http://localhost:8000

# CLI interativa (terminal)
python main.py
```

### Credenciais de Demonstração

| Usuário | Senha | Perfil |
|---|---|---|
| `admin` | `milia123` | Administrador (acesso global) |
| `demo.analyst` | `demo123` | Analista (Varejo) |
| `demo.fiscal` | `demo123` | Fiscal |
| `demo.contabil` | `demo123` | Contábil |

---

## Estrutura do Projeto

```
Milia AI/
├── app.py                               # Servidor FastAPI + rotas SPA
├── main.py                              # CLI interativa de terminal
├── config.yaml                          # Configuração declarativa de políticas
├── requirements.txt                     # Dependências
├── .env.example                         # Modelo de variáveis de ambiente
│
├── frontend/
│   ├── login.html                       # SPA completa (Login, Chat e Dashboard)
│   └── animations/
│       ├── auth-transition.js           # Transição cinematográfica (GSAP 3)
│       └── gsap-feedback.js             # Micro-interações e feedback visual
│
├── Assets/                              # Logos e ícones Milia AI
│
└── src/
    └── sql_agent/
        ├── auth/                        # Autenticação JWT + SQLite + RBAC
        ├── chat/                        # Pipeline de chat analítico (7 esteiras)
        ├── config/                      # Settings centralizados
        ├── database/                    # Schema e executor DuckDB
        ├── guardrails/                  # Scope, SQL e RLS Guardrails
        ├── memory/                      # Memória conversacional (sliding window)
        ├── prompts/                     # Engenharia de prompts analíticos
        ├── security/                    # AST, PII Redactor, Rate Limiter, Auditoria
        ├── services/                    # Orquestrador e agentes especializados
        └── v2/                          # Agente analítico v2 (agent, config, database)
```

---

## Exemplo de Interação

```
Milia AI — Agente SQL (v2)
Backend: Groq (llama-3.3-70b-versatile) | Fallback: GitHub Models (gpt-4o-mini)

Pergunta: Qual foi o faturamento total por Unidade de Negócio?

Processando...

SQL GERADO:
SELECT "Business Unit",
       ROUND(SUM("Valor Contábil"), 2) AS total_faturamento,
       COUNT(DISTINCT "Nome Cliente") AS total_clientes
FROM faturamento
GROUP BY "Business Unit"
ORDER BY total_faturamento DESC;

[✓ Consulta validada — Apenas Leitura]
[✓ Schema-only context — Dados isolados do modelo]

ANÁLISE:
Faturamento consolidado (Valor Contábil) por Unidade de Negócio:

- BU CORPORATIVO: R$ 45.234.891,00 (1.204 clientes)
- BU VAREJO: R$ 28.102.445,50 (5.892 clientes)
- BU SERVIÇOS: R$ 12.891.234,00 (347 clientes)
...
```

---

## Perguntas Fora do Domínio

O agente possui classificação explícita de escopo. Para perguntas não relacionadas aos dados:

```
Usuário: Como fazer macarrão?

Milia AI: Essa pergunta não está relacionada aos dados disponíveis para consulta.
          Posso ajudar com análises de faturamento, clientes, produtos e vendas.
```

---

## Testes

```bash
# Executar todos os testes
python -m pytest tests/ -v

# Testes individuais
python tests/test_schema.py
python tests/test_validator.py
python tests/test_memory.py
python tests/test_advanced_security.py
```

---

## Diferenciais Técnicos

- **Schema-only LLM context** — O modelo nunca recebe dados reais, apenas estrutura
- **Multi-agent pipeline** — Interpretador de negócio + Gerador SQL especializados
- **Self-healing SQL** — Auto-recuperação de queries com erro de sintaxe
- **Immutable audit trail** — SHA-256 hash chain para detecção de adulteração
- **Read-only execution** — Conexão DuckDB estritamente somente leitura
- **AST-level validation** — Análise estrutural da query antes da execução
- **LLM failover** — Alta disponibilidade sem interrupção ao usuário
- **RBAC + RLS** — Controle de acesso por perfil e isolamento por Business Unit

---

## Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

**Milia AI — Converse com seus dados usando linguagem natural.**

*Transforme perguntas em consultas SQL de forma segura e controlada.*

</div>
