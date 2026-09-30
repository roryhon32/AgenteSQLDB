"""Exemplo de estudo Alura: Consultores de Negócios e Matemática usando LangChain."""

import os
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("AVISO: OPENAI_API_KEY não encontrada no arquivo .env.")

model = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.5,
    api_key=api_key
)

prompt_consultor = ChatPromptTemplate.from_messages([
    ("system", "Apresente-se como Raphael. Você é um consultor de negócios especializado em análise de dados. Sua função é interpretar perguntas de negócio e fornecer insights claros e acionáveis."),
    ("human", "Pergunta do usuário: {pergunta}")
])

prompt_consultor_matematico = ChatPromptTemplate.from_messages([
    ("system", "Apresente-se como Jhon. Você é um consultor de matemática especializado em análise de dados. Sua função é interpretar perguntas de negócio e fornecer insights claros e acionáveis para aplicação de ML dentro da empresa na área de pricing e controladoria."),
    ("human", "Pergunta do usuário: {pergunta}")
])

cadeia_consultor = prompt_consultor | model | StrOutputParser()
cadeia_consultor_matematico = prompt_consultor_matematico | model | StrOutputParser()

if __name__ == "__main__":
    print("--- Consultor de Negócios ---")
    print(cadeia_consultor.invoke({"pergunta": "Quais clientes estão em risco de churn?"}))

    print("\n--- Consultor de Matemática / ML ---")
    print(cadeia_consultor_matematico.invoke({"pergunta": "Como posso colocar um modelo de ML dentro do meu setor?"}))

