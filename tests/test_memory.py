"""Testes unitários para o componente ConversationMemory."""

from src.sql_agent.memory.conversation_memory import ConversationMemory


def test_empty_memory():
    memory = ConversationMemory()
    assert len(memory) == 0
    assert "Nenhum histórico" in memory.get_history_text()
    assert memory.get_last_turn() is None
    assert memory.get_last_sql() is None


def test_add_turn():
    memory = ConversationMemory()
    memory.add_turn(
        question="Quais clientes estão inativos?",
        interpretation="Clientes com última compra há 180 dias ou mais",
        sql="SELECT * FROM usuarios WHERE ultima_compra <= CURRENT_DATE - INTERVAL '180 days';"
    )
    assert len(memory) == 1
    last_turn = memory.get_last_turn()
    assert last_turn is not None
    assert last_turn.turn_id == 1
    assert last_turn.question == "Quais clientes estão inativos?"
    assert "180 days" in memory.get_last_sql()
    assert "Turno 1" in memory.get_history_text()


def test_sliding_window_max_turns():
    max_turns = 3
    memory = ConversationMemory(max_turns=max_turns)

    for i in range(1, 6):
        memory.add_turn(
            question=f"Pergunta {i}",
            interpretation=f"Interpretacao {i}",
            sql=f"SELECT {i};"
        )

    # Não pode ultrapassar max_turns
    assert len(memory) == max_turns

    # Os turnos mantidos devem ser os últimos (3, 4, 5)
    history = memory.get_history_text()
    assert "Turno 3" in history
    assert "Turno 4" in history
    assert "Turno 5" in history
    assert "Turno 1" not in history
    assert "Turno 2" not in history
    assert memory.get_last_sql() == "SELECT 5;"


def test_clear_memory():
    memory = ConversationMemory()
    memory.add_turn("Pergunta", "Interpretacao", "SELECT 1;")
    assert len(memory) == 1

    memory.clear()
    assert len(memory) == 0
    assert memory.get_last_turn() is None
    assert "Nenhum histórico" in memory.get_history_text()


if __name__ == "__main__":
    test_empty_memory()
    test_add_turn()
    test_sliding_window_max_turns()
    test_clear_memory()
    print("Todos os testes de memória passaram com sucesso!")

