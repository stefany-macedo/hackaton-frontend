import os
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.agent_toolkits import create_sql_agent, SQLDatabaseToolkit
from langchain_google_genai import ChatGoogleGenerativeAI
import json
from app.db import engine

class OddsAgentService:
    def __init__(self):
        self.db = SQLDatabase(engine)
        
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.2
        )

    def get_best_odds(self, user_profile: str, question: str, live_games: list) -> str:
        # Transforma a lista de jogos do Python em um texto que a IA consegue ler
        jogos_texto = json.dumps(live_games, indent=2)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é a Raposa da Sorte, um assistente de apostas inteligente.
            
            PERFIL DO USUÁRIO ATUAL: {perfil}
            
            Aqui estão os JOGOS AO VIVO NESTE EXATO MOMENTO com as odds calculadas pelo nosso modelo:
            {jogos}
            
            REGRAS DE RECOMENDAÇÃO:
            - Se o usuário for CONSERVADOR (SAFE): Indique apenas odds baixas e seguras (abaixo de 1.60) ou dupla chance.
            - Se for MODERADO: Indique odds médias (1.60 a 2.50).
            - Se for AGRESSIVO (RISK): Procure as maiores odds (acima de 2.50) e zebras.
            
            Sua tarefa é ler a lista de jogos acima e responder à pergunta do usuário.
            Seja direto, amigável e explique o motivo da sua recomendação em 2 ou 3 frases curtas. Não use jargões técnicos de programação.
            """),
            ("user", "{pergunta}")
        ])

        # Cria a corrente de pensamento e executa
        chain = prompt | self.llm
        
        try:
            resposta = chain.invoke({
                "perfil": user_profile.upper(),
                "jogos": jogos_texto,
                "pergunta": question
            })
            return resposta.content
        except Exception as e:
            print(f"[Erro na IA]: {e}")
            return "Ops! Tive um problema para ler as odds agora. Tente perguntar de novo."