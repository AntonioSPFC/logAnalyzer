"""Correlação entre entradas de log do VPL e do ORK.

Marca como correlacionadas as entradas que compartilham o mesmo Identificador
entre as duas Aplicações. Quando um dos lados está indisponível (lista vazia),
registra um erro e preserva as entradas do lado disponível sem alteração.

Requirements: 8.1, 8.3, 8.4, 8.5
"""

from dataclasses import replace

from log_analyzer.core.modelos import EntradaDeLog, MensagemDeErro


def correlacionar_vpl_ork(
    entradas_vpl: list[EntradaDeLog],
    entradas_ork: list[EntradaDeLog],
    identificador: str,
) -> tuple[list[EntradaDeLog], list[EntradaDeLog], bool, list[MensagemDeErro]]:
    """Correlaciona entradas VPL e ORK que compartilham o mesmo identificador.

    As entradas recebidas já foram filtradas pelo identificador. Portanto, se ambos
    os lados possuem entradas, todas elas são consideradas correlacionadas
    (compartilham o identificador).

    Args:
        entradas_vpl: Entradas de log da aplicação VPL (já filtradas pelo identificador).
        entradas_ork: Entradas de log da aplicação ORK (já filtradas pelo identificador).
        identificador: O identificador usado na busca.

    Returns:
        Tupla com:
        - Lista de entradas VPL atualizadas (correlacionada=True quando aplicável)
        - Lista de entradas ORK atualizadas (correlacionada=True quando aplicável)
        - correlacao_encontrada: True se ambos os lados possuem entradas
        - Lista de MensagemDeErro se um dos lados estiver indisponível
    """
    erros: list[MensagemDeErro] = []

    # Se ambos os lados possuem entradas, há correlação
    if entradas_vpl and entradas_ork:
        vpl_atualizadas = [
            replace(entrada, correlacionada=True) for entrada in entradas_vpl
        ]
        ork_atualizadas = [
            replace(entrada, correlacionada=True) for entrada in entradas_ork
        ]
        return vpl_atualizadas, ork_atualizadas, True, erros

    # Se nenhum dos lados possui entradas, não há correlação
    if not entradas_vpl and not entradas_ork:
        return [], [], False, erros

    # Um dos lados está indisponível — registrar erro e preservar o outro lado
    if not entradas_vpl:
        erros.append(
            MensagemDeErro(
                arquivo_ou_app="VPL",
                descricao=(
                    f"Nenhuma entrada VPL disponível para o identificador "
                    f"'{identificador}' durante a correlação."
                ),
            )
        )
        return [], list(entradas_ork), False, erros

    # not entradas_ork
    erros.append(
        MensagemDeErro(
            arquivo_ou_app="ORK",
            descricao=(
                f"Nenhuma entrada ORK disponível para o identificador "
                f"'{identificador}' durante a correlação."
            ),
        )
    )
    return list(entradas_vpl), [], False, erros
