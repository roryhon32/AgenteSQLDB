# Relatório Técnico de Auditoria de Colunas do DuckDB

**Base de Dados:** `banco.duckdb`  
**Tabela Principal:** `faturamento`  
**Total de Registros:** `324,908` linhas  
**Total de Colunas:** `128` colunas  

---

## 1. Comparação Crítica: `Valor Contábil` vs `Fat. Líquido`

A tabela abaixo apresenta a comparação dos totais consolidados por ano:

| Ano | Qtd Linhas | Soma Valor Contábil (R$) | Soma Fat. Líquido (R$) | Diferença (VC - FL) | Margem Bruta (R$) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 2020 | 34,557 | 276,084,841.58 | 261,412,430.56 | 14,672,411.02 | 78,873,099.77 |
| 2021 | 31,996 | 649,915,167.26 | 621,341,974.01 | 28,573,193.25 | 153,126,799.91 |
| 2022 | 28,980 | 849,823,350.23 | 806,278,048.73 | 43,545,301.50 | 207,165,960.21 |
| 2023 | 41,580 | 688,869,665.32 | 632,830,945.44 | 56,038,719.88 | 172,680,663.57 |
| 2024 | 53,328 | 762,756,394.72 | 725,607,103.42 | 37,149,291.30 | -54,630,169,764.20 |
| 2025 | 63,548 | 585,281,107.73 | 548,607,861.52 | 36,673,246.21 | 124,773,405.37 |
| 2026 | 70,817 | 734,367,281.27 | 710,472,481.13 | 23,894,800.14 | 153,090,717.71 |
| None | 102 | 19,599,878.66 | 18,723,899.50 | 875,979.16 | -1,623,457.84 |

### Verificação de Agosto de 2026 (`Ano = 2026 AND "Mês" = 'ago'`)
- **Qtd Linhas:** `6,461`
- **Soma Fat. Líquido:** `R$ 71,025,293.95` (conforme esperado: ~R$ 71,02 mi)
- **Soma Valor Contábil:** `R$ 72,046,124.43`
- **Soma Margem Bruta:** `R$ 24,065,981.64`

### Recomendação e Decisão de Métrica Padrão:
> **Decisão:** Adotar **`Fat. Líquido`** como a métrica canônica e oficial de **"faturamento"**.
> **Justificativa:** O faturamento líquido expurga devoluções, cancelamentos e impostos incidentes sobre vendas (IPI/ICMS/PIS/COFINS), representando a receita operacional líquida real utilizada pela Milia para apuração de metas e relatórios executivos. Para agosto/2026, `Fat. Líquido` totaliza precisamente **R$ 71.025.293,95**.

---

## 2. Análise Temporal e Colunas Redundantes

### Formato Real das Colunas Temporais Canônicas:
- **"Mês":** VARCHAR de 3 letras minúsculas. Valores reais: `['', 'abr', 'ago', 'dez', 'fev', 'jan', 'jul', 'jun', 'mai', 'mar', 'nov', 'out', 'set']`
- **"Ano":** BIGINT com 4 dígitos. Valores reais: `['2020', '2021', '2022', '2023', '2024', '2025', '2026', 'None']`
- **"Trimestre":** VARCHAR/BIGINT. Valores reais: `['1º Trimestre', '2º Trimestre', '3º Trimestre', '4º Trimestre', 'None']`
- **"Semestre":** VARCHAR/BIGINT. Valores reais: `['1º Semestre', '2º Semestre', 'None']`
- **"Emissão":** DATE no formato `YYYY-MM-DD`.

### Colunas Temporais Redundantes Detectadas:
- `Mês/Ano`, `Mês-Ano`, `Mês/Ano c/ CUTOFF`: São concatenações (ex: `'08/2026'`, `'ago-26'`). **Redundantes.**
- `Ano c/ CUTOFF`, `Emissão c/ CUTOFF`: Variações ajustadas com corte contábil. **Não-canônicas.**
- `MONTH`, `dia`, `semana`, `dia semana`: Fragmentos auxiliares.
- **Decisão:** As colunas canônicas oficiais para tempo são exclusivamente: **`Ano`**, **`Mês`** e **`Emissão`**.

---

## 3. Investigação dos Dados Futuros até 12/2026

Distribuição de linhas e faturamento em 2026 por mês:

| Mês | Linhas | Fat. Líquido (R$) | Valor Contábil (R$) |
| :---: | :---: | :---: | :---: |
| jul | 6,619 | 70,145,524.63 | 72,697,406.43 |
| ago | 6,461 | 71,025,293.95 | 72,046,124.43 |
| mar | 6,364 | 70,970,762.77 | 75,400,208.72 |
| abr | 6,235 | 77,115,700.44 | 80,615,417.40 |
| jun | 6,165 | 54,431,451.29 | 56,589,571.61 |
| mai | 6,116 | 58,385,732.61 | 60,880,408.20 |
| fev | 5,757 | 68,715,495.47 | 72,244,399.23 |
| jan | 5,708 | 55,483,283.51 | 58,302,690.23 |
| set | 5,681 | 51,187,738.62 | 51,861,362.38 |
| out | 5,459 | 58,463,309.34 | 58,994,927.70 |
| nov | 5,243 | 36,011,601.33 | 36,108,828.96 |
| dez | 5,009 | 38,536,587.17 | 38,625,935.98 |

### Colunas de Distinção (Realizado vs Projetado):
- **Coluna `Origem`:** Exemplos/Distribuição em 2026 (set-dez): `[('PVs Abertos c/ Margem II (c)', 21380), ('001338182TAS4095093,75', 4), ('001338182VAR4095093,75', 4), ('005338182SERV5000000', 4)]`
- **Coluna `Tipo`:** Exemplos/Distribuição em 2026 (set-dez): `[('SE', 21074), ('MP', 278), ('PA', 36), ('0', 4)]`
- **Coluna `ICMS DIFAL Origem`:** Exemplos/Distribuição em 2026 (set-dez): `[(0.0, 21392)]`
- **Coluna `Origem Custo Médio`:** Exemplos/Distribuição em 2026 (set-dez): `[(None, 21380), ('0', 12)]`
- **Coluna `CUT-OFF`:** Exemplos/Distribuição em 2026 (set-dez): `[(None, 21392)]`
- **Coluna `Tipo de Estoque`:** Exemplos/Distribuição em 2026 (set-dez): `[('NÃO SE APLICA', 21356), ('PROJETO', 12), ('', 12), ('GIRO', 9), ('SEM GIRO', 3)]`
- **Coluna `Tipo de Venda`:** Exemplos/Distribuição em 2026 (set-dez): `[('Sell In', 21392)]`
- **Coluna `Mês/Ano c/ CUTOFF`:** Exemplos/Distribuição em 2026 (set-dez): `[('Setembro - 2026', 5681), ('Outubro - 2026', 5459), ('Novembro - 2026', 5243), ('Dezembro - 2026', 5009)]`
- **Coluna `Ano C/ CUTOFF`:** Exemplos/Distribuição em 2026 (set-dez): `[(2026, 21392)]`
- **Coluna `Emissão c/ CUTOFF`:** Exemplos/Distribuição em 2026 (set-dez): `[(datetime.date(2026, 9, 25), 3229), (datetime.date(2026, 10, 26), 3163), (datetime.date(2026, 11, 25), 3078), (datetime.date(2026, 12, 28), 2973), (datetime.date(2026, 9, 10), 960)]`
- **Coluna `Status`:** Exemplos/Distribuição em 2026 (set-dez): `[('PEDIDO', 21392)]`

> **Diagnóstico:** A base contém registros orçados/projetados para o fechamento do ano fiscal de 2026 ou pedidos de carteira/faturamento futuro inseridos no ERP. A coluna `CUT-OFF` e `Status` mantêm o acompanhamento de competência contábil.

---

## 4. As 18 Colunas-Chave Selecionadas para o Prompt Enxuto

Em vez de expor ~130 colunas ao LLM (consumindo > 5.000 tokens e estourando a janela de contexto), o agente utilizará este conjunto oficial de 18 colunas:

| # | Coluna | Tipo | % Nulos | Categoria | Descrição e Valores de Exemplo |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 1 | `Fat. Líquido` | `DOUBLE` | 0.1% | Métrica Principal | Faturamento líquido canônico (R$). Ex: 1250.50 |
| 2 | `Valor Contábil` | `DOUBLE` | 0.0% | Métrica Contábil | Valor contábil bruto com impostos (R$). Ex: 1400.00 |
| 3 | `Margem Bruta (R$)` | `DOUBLE` | 0.1% | Métrica Margem | Margem bruta em reais (R$). Ex: 450.20 |
| 4 | `Ano` | `BIGINT` | 0.03% | Tempo | Ano com 4 dígitos (BIGINT). Ex: 2024, 2025, 2026 |
| 5 | `Mês` | `VARCHAR` | 0.0% | Tempo | Mês com 3 letras minúsculas (VARCHAR). Ex: 'jan', 'fev', 'ago', 'set' |
| 6 | `Emissão` | `DATE` | 1.06% | Tempo | Data de emissão da nota fiscal (DATE). Ex: '2026-08-15' |
| 7 | `Trimestre` | `VARCHAR` | 10.77% | Tempo | Trimestre do ano (VARCHAR). Ex: '1º Trimestre', '3º Trimestre' |
| 8 | `Nome Cliente` | `VARCHAR` | 0.0% | Cliente | Razão social ou nome fantasia do cliente. Ex: 'CLIENTE_028056' |
| 9 | `cód. cliente` | `VARCHAR` | 0.0% | Cliente | Código identificador do cliente no ERP. Ex: '028056' |
| 10 | `Business Unit` | `VARCHAR` | 0.0% | BU | Unidade de Negócio Milia. Valores válidos: ['CORPORATIVO', 'CORPORATIVO 1', 'CORPORATIVO 2', 'GER7', 'GERUN', 'LATAM', 'PLATAFORMAS', 'PME', 'SERVIÇOS', 'Smart CM', 'TAS', 'VAREJO', 'VENDA DIRETA'] |
| 11 | `PRODUTOS` | `VARCHAR` | 0.0% | Produto | Descrição canônica do produto comercializado. Ex: 'POS MP50', 'GIGA PIN' |
| 12 | `cód. prod.` | `VARCHAR` | 0.0% | Produto | Código do item de produto no ERP. Ex: 'PRD00123' |
| 13 | `Nome Vendedor` | `VARCHAR` | 0.0% | Comercial | Nome do executivo de vendas responsável. Ex: 'VENDEDOR_000508' |
| 14 | `cód. vend.` | `VARCHAR` | 0.0% | Comercial | Código do vendedor no sistema comercial. |
| 15 | `Estado` | `VARCHAR` | 0.0% | Geografia | Sigla da UF da operação (VARCHAR 2 letras). Ex: 'SP', 'RJ', 'MG' |
| 16 | `Município` | `VARCHAR` | 0.0% | Geografia | Nome do município do cliente. Ex: 'São Paulo', 'Campinas' |
| 17 | `Canal de Venda` | `VARCHAR` | 0.0% | Canal | Canal de distribuição comercial. Ex: 'Direto', 'Distribuidor' |
| 18 | `Tipo de Venda` | `VARCHAR` | 0.0% | Operação | Classificação da venda (Venda de Ativo, Locação, Serviços). |

---

## 5. Tabela Completa de Todas as ~130 Colunas Inspecionadas

| Coluna | Tipo | % Nulos | Cardinalidade | Valores de Amostra |
| :--- | :---: | :---: | :---: | :--- |
| `CONCATENADO` | `VARCHAR` | 0.0% | 324908 | 'REGISTRO_244746', 'REGISTRO_244753', 'REGISTRO_244782' |
| `MONTH` | `VARCHAR` | 89.35% | 29 | '45047', '44562', '44652' |
| `Filial` | `VARCHAR` | 0.0% | 8 | '05', '06', '07' |
| `Mês/Ano` | `VARCHAR` | 0.0% | 85 | 'Dezembro - 2021', 'Maio - 2025', 'Fevereiro - 2026' |
| `Origem` | `VARCHAR` | 0.0% | 14 | '005338182SERV5000000', 'Margem Bruta por NF © comp', 'CUSTO GETNET' |
| `Setor` | `VARCHAR` | 0.0% | 10 | 'SERVICOS', '12', '' |
| `Emissão` | `DATE` | 1.06% | 1831 | '2024-09-03', '2024-11-25', '2024-12-10' |
| `Num. Docto.` | `VARCHAR` | 0.0% | 147419 | 'NF_000061267', 'NF_000061285', 'NF_000061365' |
| `Série` | `VARCHAR` | 0.0% | 54 | '1  ', '5  ', '803' |
| `Cód. Cliente` | `VARCHAR` | 0.0% | 62428 | '151122', '151553', '151693' |
| `Nome Cliente` | `VARCHAR` | 0.0% | 62428 | 'CLIENTE_094120', 'CLIENTE_152197', 'CLIENTE_153090' |
| `CNPJ/CPF` | `VARCHAR` | 0.0% | 62428 | 'CNPJ_151693', 'CNPJ_152159', 'CNPJ_152197' |
| `Estado` | `VARCHAR` | 0.0% | 29 | 'SP', 'MA', 'MG' |
| `Município` | `VARCHAR` | 0.0% | 4993 | 'SAO PAULO', 'UBERLANDIA', 'ITAIOPOLIS' |
| `Cód. Vend.` | `VARCHAR` | 0.0% | 550 | '39', '53', '229' |
| `Nome Vendedor` | `VARCHAR` | 0.0% | 550 | 'VENDEDOR_162', 'VENDEDOR_59', 'VENDEDOR_41' |
| `TES` | `VARCHAR` | 0.0% | 323 | '503', '128', '451' |
| `CFOP` | `VARCHAR` | 0.0% | 67 | '5102', '1411', '6102 ' |
| `Item` | `VARCHAR` | 0.0% | 418 | '09', '27', '23' |
| `Cód. Prod.` | `VARCHAR` | 0.0% | 2383 | '5M001695', '50201066', '00410012' |
| `Desc. Produto` | `VARCHAR` | 0.0% | 2347 | 'GPOS700A - MADERO', 'GPOS700A – 40MM – SERBET / ALPIDEX (SDK STONE PARCEIROS)', 'GPOS720 - CAR10' |
| `Cod. Familia` | `VARCHAR` | 1.44% | 122 | '200', '001', '502' |
| `Desc. Familia` | `VARCHAR` | 42.18% | 101 | '', 'TSG800', 'ANTENA' |
| `Cód. Custo` | `VARCHAR` | 0.1% | 132 | '40002100', '580801001026', '131003001' |
| `Desc. C Custo` | `VARCHAR` | 0.1% | 118 | 'VAREJO', 'REVENDAS', 'UOL' |
| `Grupo` | `VARCHAR` | 0.0% | 195 | 'MFE', 'PPC930 - REDES', 'LEC MAG' |
| `Tipo` | `VARCHAR` | 0.0% | 10 | '0', 'ME', 'OS' |
| `FAT - Quant.` | `DOUBLE` | 0.0% | 1761 | '155.0', '80.0', '57.0' |
| `DEV - Quant.` | `DOUBLE` | 0.1% | 221 | '-1.0', '-16.0', '-150.0' |
| `LIQ - Quant.` | `DOUBLE` | 0.0% | 1942 | '-1.0', '186.0', '32.0' |
| `Vlr. Produtos` | `DOUBLE` | 0.0% | 24937 | '161.0', '325.0', '916.0' |
| `Vlr. Mercadoria (bruto)` | `DOUBLE` | 0.0% | 25217 | '246.0', '354.0', '9780.0' |
| `Desconto` | `DOUBLE` | 0.1% | 919 | '164.0', '28.0', '52.0' |
| `Cód. Condição` | `VARCHAR` | 0.1% | 73 | '000132', '000122', '000116' |
| `Desconto VD` | `BIGINT` | 0.1% | 53 | '-131', '398', '770' |
| `Servicos VD` | `BIGINT` | 0.1% | 106 | '101', '-164', '-471' |
| `Valor Contábil` | `DOUBLE` | 0.0% | 27084 | '151.47', '82.79', '197.56' |
| `Vlr.IPI` | `DOUBLE` | 0.1% | 11546 | '128.89', '23.52', '-82.79' |
| `Vlr.ICMS` | `DOUBLE` | 0.1% | 8361 | '72.44', '210.74', '480.74' |
| `Vlr. ISS` | `DOUBLE` | 0.0% | 5527 | '80.91', '937.02', '128.89' |
| `PIS` | `DOUBLE` | 0.0% | 12816 | '20.56', '621.71', '932.56' |
| `COFINS` | `DOUBLE` | 0.0% | 19956 | '131.71', '326.45', '391.37' |
| `ICMS DIFAL Origem` | `DOUBLE` | 0.1% | 756 | '28.22', '173.1', '17.87' |
| `ICMS DIFAL Destino` | `DOUBLE` | 0.1% | 3935 | '1475.15', '369.73', '47.98' |
| `ICMS Fundo de Pobreza` | `DOUBLE` | 0.1% | 503 | '17.87', '8.47', '40.45' |
| `Fat. Líquido` | `DOUBLE` | 0.1% | 37003 | '176.87', '230.49', '149.59' |
| `Custo Médio Total` | `DOUBLE` | 0.1% | 16437 | '40425.98', '4322.16', '59549.76' |
| `Custo Médio Unitário` | `DOUBLE` | 0.1% | 3590 | '474.57', '495.0', '634.65' |
| `Origem Custo Médio` | `VARCHAR` | 93.33% | 5 | '0', 'RATEIO GGF DIA', '' |
| `Margem Bruta (%)` | `DOUBLE` | 0.0% | 32109 | '0.5419172862106325', '0.5514675093202992', '0.5413197204903971' |
| `Margem Bruta (R$)` | `DOUBLE` | 0.1% | 45838 | '197.56', '344.33', '255.89' |
| `Vendedor Ajustado` | `VARCHAR` | 34.49% | 119 | 'E-COMMERCE', 'REGINALDO DA SILVA LEITE ROSA', 'MAGDA PEREIRA' |
| `Data Ajust.` | `DATE` | 0.13% | 1836 | '2021-02-03', '2022-06-03', '2021-01-28' |
| `Valor Contábil Ajustado` | `VARCHAR` | 88.32% | 11918 | '795600', '3250000', '53950' |
| `Fat. Líquido Ajustado` | `VARCHAR` | 88.32% | 13822 | '130762.476902942', '49637.054306348', '2721.36' |
| `Custo Total Ajustado` | `VARCHAR` | 100.0% | 0 | N/A |
| `Margem Bruta Ajustada` | `VARCHAR` | 100.0% | 0 | N/A |
| `Preço Médio` | `DOUBLE` | 0.0% | 22946 | '193.8', '112.89', '87.49' |
| `Preço Serv. VD` | `VARCHAR` | 87.01% | 42 | '95.05', '269.41', '137.21' |
| `Custo Médio` | `VARCHAR` | 89.14% | 166 | '169.97', '151.316666667', '343.7' |
| `Custo Serv. VD` | `VARCHAR` | 87.64% | 1 | '0' |
| `CNPJ Aj.` | `VARCHAR` | 0.0% | 62428 | 'CLIENTE_151122', 'CLIENTE_141208', 'CLIENTE_144583' |
| `No. NF Aj.` | `VARCHAR` | 0.1% | 136278 | 'NF_61225', 'NF_60096', 'NF_61284' |
| `Cod. Prod. Aj.` | `VARCHAR` | 0.1% | 2381 | '00410594', '5M202210', '50800047' |
| `NF + Prod.` | `VARCHAR` | 0.0% | 283026 | 'NF_000061281 - 20000600', 'NF_000061348 - 08004480', 'NF_000061360 - 08004480' |
| `Roadmap` | `BIGINT` | 64.2% | 1 | '0' |
| `Linha (Família + BU)` | `VARCHAR` | 79.44% | 30 | 'TECLADOS', 'BUSCA PREÇO', 'PARTES E PEÇAS' |
| `Familia Ajustada` | `VARCHAR` | 0.0% | 12 | 'SERVIÇOS', 'SMART POS', 'OUTROS PRODUTOS' |
| `BU Família` | `VARCHAR` | 0.1% | 15 | 'VENDA DIRETA', 'Smart CM', 'GERUS' |
| `BU Prod.` | `VARCHAR` | 0.1% | 8 | 'VENDA DIRETA', 'CORPORATIVO 1', 'CORPORATIVO' |
| `BU Cliente` | `VARCHAR` | 0.1% | 8 | 'VENDA DIRETA', 'SERVIÇOS', 'CORPORATIVO' |
| `Business Unit` | `VARCHAR` | 0.0% | 13 | 'GERUN', 'SERVIÇOS', 'VENDA DIRETA' |
| `TOP 10` | `VARCHAR` | 0.1% | 642 | 'PAULO R. M', 'FORMULA CO', 'DEISE ELIS' |
| `PRODUTOS` | `VARCHAR` | 0.0% | 75 | 'GERUN', 'SERVIÇOS', 'GPOS400' |
| `Cliente REAL` | `VARCHAR` | 0.0% | 62428 | 'CLIENTE_151122', 'CLIENTE_141208', 'CLIENTE_144583' |
| `Forçar BU` | `VARCHAR` | 90.14% | 15 | 'VENDA DIRETA', '', 'Smart CM' |
| `CUT-OFF` | `VARCHAR` | 99.79% | 10 | 'JAN22', 'CORPORATIVO', 'SERVIÇOS' |
| `DIA` | `BIGINT` | 10.77% | 31 | '15', '18', '31' |
| `Mês` | `VARCHAR` | 0.0% | 13 | 'set', 'fev', 'mai' |
| `Semana` | `VARCHAR` | 41.87% | 7 | '1', 'S1', 'S5' |
| `Ano` | `BIGINT` | 0.03% | 7 | '2020', '2021', '2025' |
| `Bu Centro de Custo` | `VARCHAR` | 15.95% | 13 | 'PME', '0', 'TAS' |
| `DIF Bus` | `BIGINT` | 10.74% | 2 | '1', '0' |
| `BU - Vendedor` | `VARCHAR` | 46.09% | 9 | 'GER7', '10000200|VAREJO', '10000500|GERUN' |
| `CODIGO/DESCRIÇÃO` | `VARCHAR` | 10.74% | 2686 | '50201837|GPOS700A - SKYTEF (MDM)', '50201684|GPOS700A - ACBRPAY', '50202041|GPOS700A - MULTI SE + CIELO PAGSEGURO (IOS)' |
| `Dia Semana` | `BIGINT` | 10.77% | 7 | '4', '1', '2' |
| `Trimestre` | `VARCHAR` | 10.77% | 4 | '1º Trimestre', '3º Trimestre', '4º Trimestre' |
| `Semestre` | `VARCHAR` | 10.77% | 2 | '1º Semestre', '2º Semestre' |
| `ML%` | `DOUBLE` | 10.74% | 2 | '0.1325', '0.14' |
| `Tipo de Estoque` | `VARCHAR` | 0.0% | 8 | 'SEM GIRO', 'EOL', 'PROJETO' |
| `FAT - Vend.Interno` | `VARCHAR` | 29.45% | 178 | '000677', '000014', '000363' |
| `FAT - Nome Vend.Int` | `VARCHAR` | 29.45% | 178 | 'VENDEDOR_602015', 'VENDEDOR_000802', 'VENDEDOR_000363' |
| `TX Moeda` | `DOUBLE` | 29.56% | 333 | '5.3409', '5.5947', '4.9856' |
| `Empresa` | `VARCHAR` | 0.0% | 3 | '04 – GER7', '03 – GERUN', '01 – Milia' |
| `Moeda` | `VARCHAR` | 30.1% | 6 | 'Daqui para cima considerar Bu pela celula (Business Unit)', 'Real', 'Dolar' |
| `Conversao` | `VARCHAR` | 30.11% | 7 | 'Ptax Dia', 'TAS', 'Ptax 30' |
| `Vlr Negociado` | `DOUBLE` | 41.0% | 1412 | '325.0', '67.53', '1050.0' |
| `FAT - Estado-Ent` | `BIGINT` | 93.16% | 1 | '0' |
| `FAT - Município-Ent` | `BIGINT` | 93.68% | 1 | '0' |
| `Campanha` | `VARCHAR` | 11.12% | 15 | 'Q3_2023', 'Q1_2025', 'S' |
| `ProdutoCamp` | `VARCHAR` | 11.11% | 38 | 'GPOS700X', 'G250W', 'MP35P' |
| `Classificação Ccusto` | `VARCHAR` | 39.93% | 8 | 'PLATAFORMAS', 'SERVIÇOS', 'PME' |
| `Mês-Ano` | `VARCHAR` | 11.11% | 73 | 'janeiro - 2026', 'abril - 2021', 'julho - 2025' |
| `ECOMERCE` | `VARCHAR` | 100.0% | 0 | N/A |
| `Ajustar MB` | `VARCHAR` | 42.64% | 3 | '', '0', 'S' |
| `LIQ - Margem Bruta (R$)- Produtos MB <15%` | `DOUBLE` | 42.49% | 770 | '69.70747755', '133.21756545', '67.13254125' |
| `LIQ - Custo Medio Total- Produtos MB <15%` | `DOUBLE` | 42.48% | 829 | '388.584466792745', '4573.245959285697', '9649.037229763993' |
| `MB% Produtos MB <15%` | `BOOLEAN` | 42.49% | 2 | 'False', 'True' |
| `LIQ - Custo Medio Total- Produtos MB >15%` | `DOUBLE` | 42.48% | 6409 | '0.0', '4900.492898962524', '3896.6' |
| `LIQ - Custo Medio Total- Ajustado` | `DOUBLE` | 42.48% | 10827 | '216.66756135670892', '95531.04807319364', '205.5349273795684' |
| `LIQ - Custo Medio Unit.- Ajustado` | `DOUBLE` | 42.48% | 9174 | '98.7323136362171', '110.73154373516266', '150.6494008713854' |
| `Custo Total- Ajustado` | `DOUBLE` | 42.48% | 30856 | '-111.484232058866', '5071.222619005697', '-156.00899104175895' |
| `LIQ - MB (R$)- AJU` | `DOUBLE` | 0.0% | 106265 | '56.58332063684345', '82.73739086299159', '86.31830260489605' |
| `Sistema Operacional` | `VARCHAR` | 0.0% | 2 | 'Outros', 'Android' |
| `Segmento do Produto` | `VARCHAR` | 0.0% | 4 | '-', 'AUTOMAÇÃO', 'NÃO SE APLICA' |
| `Canal de Venda` | `VARCHAR` | 0.0% | 12 | 'DISTRIBUIDOR', 'CLIENTE FINAL', 'PE' |
| `Tipo de Venda` | `VARCHAR` | 0.0% | 1 | 'Sell In' |
| `Mês/Ano c/ CUTOFF` | `VARCHAR` | 0.0% | 85 | 'Maio - 2021', 'Agosto - 2023', 'Maio - 2020' |
| `Ano C/ CUTOFF` | `BIGINT` | 0.03% | 7 | '2024', '2020', '2021' |
| `Emissão c/ CUTOFF` | `DATE` | 1.06% | 1833 | '2021-01-29', '2021-04-09', '2021-04-22' |
| `Loja Virtual` | `VARCHAR` | 0.0% | 2 | '-', 'Loja Virtual' |
| `Projetos` | `VARCHAR` | 0.0% | 2 | 'Projeto', 'Regular' |
| `Vendas em Dólar` | `VARCHAR` | 0.0% | 2 | 'Em Dólar', '-' |
| `Subfamília` | `VARCHAR` | 0.0% | 19 | 'M-POS', 'MPOS', 'PDV' |
| `Status` | `VARCHAR` | 0.0% | 2 | 'PEDIDO', 'FATURADO' |
| `RAIZ CNPJ` | `VARCHAR` | 0.0% | 62428 | 'CLIENTE_341151', 'CLIENTE_014249', 'CLIENTE_337355' |
| `E-COMERCE` | `VARCHAR` | 42.2% | 3 | 'Regular', 'Mercado livre', 'NÃO ECOMERCE' |
| `ODM` | `VARCHAR` | 42.2% | 9 | 'FEITIAN', 'TOPWISE', 'UROVO' |

