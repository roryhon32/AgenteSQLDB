"""Exemplo de estudo: Gerador de Roteiro de Viagem usando LangChain e OpenAI."""

import os
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

modelo_de_prompt = PromptTemplate.from_template("""
Crie um roteiro de viagem de {dias} dias para uma família com {numero_criancas} crianças,
com foco em {atividade}.
""")

numero_dias = 5
numero_criancas = 2
atividade = "parques temáticos"

prompt = modelo_de_prompt.format(
    dias=numero_dias,
    numero_criancas=numero_criancas,
    atividade=atividade
)

print("Prompt formatado:\n", prompt)

if api_key:
    modelo = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.5,
        api_key=api_key
    )
    resposta = modelo.invoke(prompt)
    print("\nResposta do Modelo:\n", resposta.content)
else:
    print("\nAVISO: OPENAI_API_KEY não configurada no .env.")

