"""Gerenciamento de memória e histórico conversacional multi-turn."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ConversationTurn:
    """Representa um turno de interação no diálogo analítico."""
    turn_id: int
    question: str
    interpretation: str
    sql: Optional[str] = None


@dataclass
class ConversationMemory:
    """Gerencia o histórico de turnos com janela deslizante (sliding window)."""

    max_turns: int = 5
    _turns: List[ConversationTurn] = field(default_factory=list)
    _turn_counter: int = 0

    def add_turn(self, question: str, interpretation: str, sql: Optional[str] = None) -> None:
        """Adiciona um novo turno concluído com sucesso ao histórico."""
        self._turn_counter += 1
        turn = ConversationTurn(
            turn_id=self._turn_counter,
            question=question.strip(),
            interpretation=interpretation.strip(),
            sql=sql.strip() if sql else None
        )
        self._turns.append(turn)
        # Mantém apenas os últimos max_turns
        if len(self._turns) > self.max_turns:
            self._turns.pop(0)

    def get_history_text(self) -> str:
        """Formata o histórico recente em texto claro para injeção nos prompts."""
        if not self._turns:
            return "Nenhum histórico anterior. Esta é a primeira interação da conversa."

        history_blocks = []
        for turn in self._turns:
            block = [
                f"[Turno {turn.turn_id}]",
                f"Pergunta do Usuário: {turn.question}",
                f"Interpretação Aplicada:\n{turn.interpretation}"
            ]
            if turn.sql:
                block.append(f"SQL DuckDB Gerado:\n{turn.sql}")
            history_blocks.append("\n".join(block))

        return "\n\n---\n\n".join(history_blocks)

    def get_last_turn(self) -> Optional[ConversationTurn]:
        """Retorna o último turno registrado, se houver."""
        return self._turns[-1] if self._turns else None

    def get_last_sql(self) -> Optional[str]:
        """Retorna o último SQL gerado com sucesso, se houver."""
        last_turn = self.get_last_turn()
        return last_turn.sql if last_turn else None

    def clear(self) -> None:
        """Limpa todo o histórico de conversação."""
        self._turns.clear()
        self._turn_counter = 0

    def __len__(self) -> int:
        """Retorna o número de turnos atualmente armazenados na janela."""
        return len(self._turns)

