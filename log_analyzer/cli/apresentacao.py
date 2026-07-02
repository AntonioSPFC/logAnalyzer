"""Renderização do Resultado_de_Analise para saída CLI.

Este módulo consome um ResultadoDeAnalise e o renderiza como string formatada:
- Agrupa entradas por Aplicação e renderiza a linha do tempo
- Entradas de erro recebem marcação visual distinta "[ERRO]"
- Exibe contagens por categoria e por Aplicação
- Se não houver entradas, exibe mensagem informativa (Req 9.2)
- Em caso de falha na renderização, retorna mensagem de erro preservando as entradas (Req 9.5)
"""

from log_analyzer.core.modelos import Categoria, EntradaDeLog, ResultadoDeAnalise


def _formatar_entrada(entrada: EntradaDeLog) -> str:
    """Formata uma única EntradaDeLog para exibição.

    Inclui conteúdo, aplicação de origem e categoria.
    Entradas classificadas como ERRO recebem prefixo "[ERRO]" (Req 9.3).
    """
    marcador = "[ERRO] " if entrada.categoria == Categoria.ERRO else ""

    if entrada.interpretada:
        carimbo = (
            entrada.carimbo_de_tempo.strftime("%Y-%m-%d %H:%M:%S")
            if entrada.carimbo_de_tempo
            else "?"
        )
        linha = (
            f"  {marcador}{carimbo} "
            f"[{entrada.nivel_de_severidade}] "
            f"{entrada.mensagem} "
            f"({entrada.categoria.value})"
        )
    else:
        linha = (
            f"  {marcador}{entrada.texto_original} "
            f"({entrada.categoria.value})"
        )

    return linha


def _renderizar_contagens(resultado: ResultadoDeAnalise) -> str:
    """Renderiza as contagens por categoria e por aplicação."""
    linhas: list[str] = []

    if resultado.contagem_por_categoria:
        linhas.append("Contagem por categoria:")
        for categoria, contagem in resultado.contagem_por_categoria.items():
            linhas.append(f"  {categoria.value}: {contagem}")

    if resultado.contagem_por_aplicacao:
        linhas.append("Contagem por aplicação:")
        for app, contagem in resultado.contagem_por_aplicacao.items():
            linhas.append(f"  {app}: {contagem}")

    return "\n".join(linhas)


def renderizar_resultado(resultado: ResultadoDeAnalise) -> str:
    """Renderiza o ResultadoDeAnalise como string formatada para saída CLI.

    - Agrupa entradas por Aplicação (Req 3.3, 9.1)
    - Mostra linha do tempo com timestamps, severidade e mensagem
    - Entradas de erro marcadas com indicador visual distinto "[ERRO]" (Req 9.3)
    - Mostra contagens por categoria e por aplicação (Req 9.4)
    - Retorna mensagem apropriada se nenhuma entrada encontrada (Req 9.2)
    - Em caso de falha, retorna mensagem de erro (entradas preservadas no objeto) (Req 9.5)

    Args:
        resultado: O ResultadoDeAnalise a ser renderizado.

    Returns:
        String formatada representando o resultado da análise.
    """
    try:
        linhas: list[str] = []

        linhas.append(f"Resultado da análise para: {resultado.identificador}")
        linhas.append("")

        # Verificar se não há entradas (Req 9.2)
        total_entradas = sum(
            len(entradas) for entradas in resultado.entradas_por_aplicacao.values()
        )

        if total_entradas == 0:
            linhas.append(
                "Nenhuma entrada encontrada para o identificador informado."
            )
            # Incluir mensagens acumuladas
            for msg in resultado.mensagens:
                linhas.append(msg)
            return "\n".join(linhas)

        # Agrupar por aplicação e renderizar a linha do tempo (Req 9.1)
        for app, entradas in resultado.entradas_por_aplicacao.items():
            linhas.append(f"[{app}] ({len(entradas)} entradas)")
            for entrada in entradas:
                linhas.append(_formatar_entrada(entrada))
            linhas.append("")

        # Exibir contagens (Req 9.4)
        contagens = _renderizar_contagens(resultado)
        if contagens:
            linhas.append(contagens)

        # Incluir mensagens acumuladas
        if resultado.mensagens:
            linhas.append("")
            for msg in resultado.mensagens:
                linhas.append(msg)

        # Incluir erros acumulados
        if resultado.erros:
            linhas.append("")
            linhas.append("Erros:")
            for erro in resultado.erros:
                linhas.append(f"  [{erro.arquivo_ou_app}] {erro.descricao}")

        return "\n".join(linhas)

    except Exception as e:
        # Req 9.5: Em caso de falha, retorna mensagem de erro.
        # As entradas selecionadas permanecem preservadas no objeto resultado.
        return (
            f"Falha ao exibir o resultado da análise: {e}. "
            f"As entradas selecionadas foram preservadas."
        )
