"""Renderização segura do resultado para a saída da CLI.

A apresentação da Fase 2 aceita somente uma visão marcada como sanitizada e
concluída. Ela nunca consulta ``texto_original``: entradas são exibidas por
``representacao_sanitizada``. O adaptador puramente legado fica isolado no
wrapper ``renderizar_resultado`` para preservar o contrato caracterizado da
Fase 1; o iterador público é sempre estrito.

O iterador público é atômico em relação a falhas de apresentação. Todas as
linhas são preparadas antes de o iterador ser devolvido; se qualquer etapa
falhar, o chamador recebe somente uma mensagem constante e nenhum prefixo da
saída parcialmente construída.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

from log_analyzer.core.explicabilidade import (
    MENSAGEM_SEM_REGRA_CORRESPONDENTE,
)
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ReferenciaRegra,
    ResultadoDeAnalise,
    VinculoIdentificadores,
)
from log_analyzer.core.visao_segura import (
    MENSAGEM_FALHA_VISAO_SEGURA,
    ScannerFinalDeResultado,
)


MENSAGEM_FALHA_APRESENTACAO = (
    "Falha ao exibir o resultado da análise. "
    "As entradas selecionadas foram preservadas e nenhum conteúdo foi exibido."
)


class _VisaoFase2NaoConcluida(Exception):
    """Sinal interno sem conteúdo de origem para recusar uma visão insegura."""


def _formatar_entrada_legada(entrada: EntradaDeLog) -> str:
    """Preserva a representação caracterizada de uma entrada da Fase 1."""

    marcador = "[ERRO] " if entrada.categoria == Categoria.ERRO else ""

    if entrada.interpretada:
        carimbo = (
            entrada.carimbo_de_tempo.strftime("%Y-%m-%d %H:%M:%S")
            if entrada.carimbo_de_tempo
            else "?"
        )
        return (
            f"  {marcador}{carimbo} "
            f"[{entrada.nivel_de_severidade}] "
            f"{entrada.mensagem} "
            f"({entrada.categoria.value})"
        )

    return (
        f"  {marcador}{entrada.texto_original} "
        f"({entrada.categoria.value})"
    )


def _entrada_tem_metadados_fase2(entrada: EntradaDeLog) -> bool:
    """Detecta somente campos aditivos, sem consultar conteúdo bruto."""

    return any(
        (
            entrada.entrada_id is not None,
            entrada.arquivo_origem is not None,
            entrada.arquivo_token is not None,
            entrada.posicao_inicial is not None,
            entrada.posicao_final is not None,
            entrada.timestamp_original is not None,
            entrada.timestamp_normalizado is not None,
            entrada.precisao_fracionaria is not None,
            entrada.origem_evento is not None,
            entrada.formato_origem is not None,
            bool(entrada.campos_estruturados),
            bool(entrada.identificadores),
            bool(entrada.falhas),
            entrada.representacao_sanitizada is not None,
        )
    )


def _resultado_tem_conteudo_fase2(resultado: ResultadoDeAnalise) -> bool:
    """Distingue a extensão Fase 2 do resultado puramente legado.

    ``ResultadoDeAnalise`` manteve defaults aditivos para consumidores antigos.
    Por isso os defaults isolados não transformam um objeto legado em Fase 2;
    metadados efetivamente preenchidos ou um estado de sanitização explícito
    fazem essa distinção.
    """

    if resultado.estado_sanitizacao is not EstadoSanitizacao.INTERNA_BRUTA:
        return True
    if any(
        (
            resultado.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA,
            bool(resultado.entradas_sem_ordenacao_temporal),
            bool(resultado.identificadores_extraidos),
            bool(resultado.vinculos),
            resultado.correlacao is not None,
            bool(resultado.evidencias),
            resultado.regra_aplicada is not None,
            resultado.versao_catalogo != "sem-catalogo-ativo",
            resultado.causa_raiz.estado is not EstadoCausaRaiz.NAO_DETERMINADA,
            resultado.causa_raiz.regra is not None,
            resultado.causa_raiz.descricao_sanitizada != "não determinada",
            bool(resultado.aplicacoes_analisadas),
            bool(resultado.aplicacoes_ausentes_ou_invalidas),
        )
    ):
        return True

    entradas = (
        entrada
        for grupo in resultado.entradas_por_aplicacao.values()
        for entrada in grupo
    )
    return any(
        _entrada_tem_metadados_fase2(entrada)
        for entrada in (
            *entradas,
            *resultado.linha_do_tempo,
        )
    )


def _iterar_entradas_fase2(
    resultado: ResultadoDeAnalise,
) -> Iterator[EntradaDeLog]:
    """Percorre todas as fronteiras que podem levar uma entrada à saída."""

    for entradas in resultado.entradas_por_aplicacao.values():
        yield from entradas
    yield from resultado.linha_do_tempo
    yield from resultado.entradas_sem_ordenacao_temporal


def _validar_visao_fase2(resultado: ResultadoDeAnalise) -> None:
    """Recusa antes da renderização qualquer visão Fase 2 não concluída."""

    if resultado.estado_sanitizacao is not EstadoSanitizacao.CONCLUIDA:
        raise _VisaoFase2NaoConcluida

    for entrada in _iterar_entradas_fase2(resultado):
        if not isinstance(entrada, EntradaDeLog):
            raise TypeError("coleção de entradas inválida")
        if entrada.arquivo_origem is not None:
            raise _VisaoFase2NaoConcluida
        if not isinstance(entrada.representacao_sanitizada, str):
            raise _VisaoFase2NaoConcluida
        if not entrada.representacao_sanitizada.strip():
            raise _VisaoFase2NaoConcluida


def _capturar_visao_fase2_validada(
    resultado: ResultadoDeAnalise,
) -> ResultadoDeAnalise:
    """Copia e revalida exatamente o snapshot que será apresentado.

    ``ResultadoDeAnalise`` mantém coleções mutáveis por compatibilidade. A cópia
    impede que uma mutação posterior ao scanner original altere o conteúdo em
    renderização. O scanner independente é repetido sobre essa cópia exata;
    assim, o enum ``CONCLUIDA`` isolado nunca autoriza valores acrescentados
    depois da sanitização.
    """

    if resultado.estado_sanitizacao is not EstadoSanitizacao.CONCLUIDA:
        raise _VisaoFase2NaoConcluida

    snapshot = ResultadoDeAnalise(
        identificador=resultado.identificador,
        entradas_por_aplicacao={
            aplicacao: list(entradas)
            for aplicacao, entradas in resultado.entradas_por_aplicacao.items()
        },
        linha_do_tempo=list(resultado.linha_do_tempo),
        contagem_por_categoria=dict(resultado.contagem_por_categoria),
        contagem_por_aplicacao=dict(resultado.contagem_por_aplicacao),
        correlacao_encontrada=resultado.correlacao_encontrada,
        erros=[
            MensagemDeErro(erro.arquivo_ou_app, erro.descricao)
            for erro in resultado.erros
        ],
        mensagens=list(resultado.mensagens),
        categoria_de_cenario=resultado.categoria_de_cenario,
        entradas_sem_ordenacao_temporal=list(
            resultado.entradas_sem_ordenacao_temporal
        ),
        identificadores_extraidos=list(resultado.identificadores_extraidos),
        vinculos=list(resultado.vinculos),
        correlacao=resultado.correlacao,
        evidencias=list(resultado.evidencias),
        regra_aplicada=resultado.regra_aplicada,
        versao_catalogo=resultado.versao_catalogo,
        estado_sanitizacao=resultado.estado_sanitizacao,
        causa_raiz=resultado.causa_raiz,
        aplicacoes_analisadas=list(resultado.aplicacoes_analisadas),
        aplicacoes_ausentes_ou_invalidas=list(
            resultado.aplicacoes_ausentes_ou_invalidas
        ),
        cobertura_rotulada=resultado.cobertura_rotulada,
    )
    _validar_visao_fase2(snapshot)
    try:
        ScannerFinalDeResultado().validar(snapshot)
    except Exception:
        raise _VisaoFase2NaoConcluida from None
    return snapshot


def _formatar_timestamp_utc(
    valor: datetime | None,
    precisao: int | None = None,
) -> str:
    """Formata UTC com offset explícito e, quando conhecida, mesma precisão."""

    if valor is None:
        return "sem UTC"
    if valor.tzinfo is None or valor.utcoffset() != timedelta(0):
        raise ValueError("timestamp da timeline não está em UTC")

    if precisao is None:
        return valor.isoformat()

    base = valor.strftime("%Y-%m-%dT%H:%M:%S")
    fracao = ""
    if precisao:
        fracao = f".{valor.microsecond:06d}"[: precisao + 1]
    return f"{base}{fracao}+00:00"


def _formatar_intervalo(
    arquivo_token: str | None,
    linha_inicial: int | None,
    linha_final: int | None,
) -> str:
    token = arquivo_token or "<ARQUIVO_NAO_INFORMADO>"
    if linha_inicial is None or linha_final is None:
        return f"{token}:posição não informada"
    if linha_inicial == linha_final:
        return f"{token}:linha {linha_inicial}"
    return f"{token}:linhas {linha_inicial}-{linha_final}"


def _formatar_proveniencia(proveniencia: Proveniencia) -> str:
    return _formatar_intervalo(
        proveniencia.arquivo_token,
        proveniencia.linha_inicial,
        proveniencia.linha_final,
    )


def _formatar_entrada_fase2(
    entrada: EntradaDeLog,
    *,
    usar_timestamp_utc: bool,
) -> str:
    """Formata uma entrada Fase 2 sem acessar ``texto_original`` ou mensagem."""

    representacao = entrada.representacao_sanitizada
    if not isinstance(representacao, str) or not representacao.strip():
        raise _VisaoFase2NaoConcluida

    if usar_timestamp_utc:
        carimbo = _formatar_timestamp_utc(
            entrada.timestamp_normalizado,
            entrada.precisao_fracionaria,
        )
    else:
        carimbo = entrada.timestamp_original or "sem timestamp de origem"

    severidade = entrada.nivel_de_severidade or "não informada"
    marcador = "[ERRO] " if entrada.categoria is Categoria.ERRO else ""
    posicao = _formatar_intervalo(
        entrada.arquivo_token,
        entrada.posicao_inicial,
        entrada.posicao_final,
    )
    return (
        f"  {marcador}{carimbo} "
        f"[Severidade de log: {severidade}] "
        f"{representacao} "
        f"(Categoria da entrada: {entrada.categoria.name}; {posicao})"
    )


def _renderizar_contagens(resultado: ResultadoDeAnalise) -> list[str]:
    """Preserva títulos e valores das contagens da Fase 1."""

    linhas: list[str] = []
    if resultado.contagem_por_categoria:
        linhas.append("Contagem por categoria:")
        for categoria, contagem in resultado.contagem_por_categoria.items():
            linhas.append(f"  {categoria.value}: {contagem}")

    if resultado.contagem_por_aplicacao:
        linhas.append("Contagem por aplicação:")
        for app, contagem in resultado.contagem_por_aplicacao.items():
            linhas.append(f"  {app}: {contagem}")
    return linhas


def _adicionar_bloco(linhas: list[str], bloco: list[str]) -> None:
    if not bloco:
        return
    if linhas and linhas[-1] != "":
        linhas.append("")
    linhas.extend(bloco)


def _adicionar_mensagens_e_erros(
    linhas: list[str],
    resultado: ResultadoDeAnalise,
) -> None:
    if resultado.mensagens:
        _adicionar_bloco(linhas, list(resultado.mensagens))

    if resultado.erros:
        bloco = ["Erros:"]
        bloco.extend(
            f"  [{erro.arquivo_ou_app}] {erro.descricao}"
            for erro in resultado.erros
        )
        _adicionar_bloco(linhas, bloco)


def _construir_linhas_legadas(resultado: ResultadoDeAnalise) -> list[str]:
    """Reproduz a ordem e as seções públicas da Fase 1."""

    linhas = [f"Resultado da análise para: {resultado.identificador}", ""]
    total_entradas = sum(
        len(entradas)
        for entradas in resultado.entradas_por_aplicacao.values()
    )
    if total_entradas == 0:
        linhas.append(
            "Nenhuma entrada encontrada para o identificador informado."
        )
        linhas.extend(resultado.mensagens)
        return linhas

    for app, entradas in resultado.entradas_por_aplicacao.items():
        linhas.append(f"[{app}] ({len(entradas)} entradas)")
        linhas.extend(_formatar_entrada_legada(entrada) for entrada in entradas)
        linhas.append("")

    linhas.extend(_renderizar_contagens(resultado))
    _adicionar_mensagens_e_erros(linhas, resultado)
    return linhas


def _formatar_regra(regra: ReferenciaRegra | None) -> str:
    if regra is None:
        return "nenhuma"
    return f"{regra.rule_id} v{regra.versao}"


def _formatar_identificador(identificador: IdentificadorTecnico) -> str:
    return (
        f"  {identificador.tipo.name} | campo={identificador.nome_campo} | "
        f"valor={identificador.valor_original} | "
        f"{_formatar_proveniencia(identificador.proveniencia)}"
    )


def _formatar_vinculo(vinculo: VinculoIdentificadores) -> str:
    estado = "ambíguo" if vinculo.ambiguo else "não ambíguo"
    correlacao = "permite correlação" if vinculo.permite_correlacao else (
        "não permite correlação"
    )
    return (
        f"  {vinculo.origem.valor_original} --[{vinculo.tipo_relacao}]--> "
        f"{vinculo.destino.valor_original} | esquema={vinculo.esquema_id} "
        f"v{vinculo.esquema_versao} | {estado}; {correlacao} | "
        f"evidência={_formatar_proveniencia(vinculo.evidencia)}"
    )


def _formatar_evidencia(evidencia: Evidencia) -> str:
    timestamp_original = evidencia.timestamp_original or "não informado"
    timestamp_utc = _formatar_timestamp_utc(evidencia.timestamp_normalizado)
    return (
        f"  [{evidencia.aplicacao}] "
        f"{_formatar_proveniencia(evidencia.proveniencia)} | "
        f"timestamp original={timestamp_original} | UTC={timestamp_utc} | "
        f"campo/condição={evidencia.campo_ou_condicao} | "
        f"{evidencia.representacao_sanitizada}"
    )


def _sem_repeticoes_por_identidade(valores: Iterator[object]) -> list[object]:
    resultado: list[object] = []
    identidades: set[int] = set()
    for valor in valores:
        identidade = id(valor)
        if identidade not in identidades:
            identidades.add(identidade)
            resultado.append(valor)
    return resultado


def _construir_linhas_fase2(resultado: ResultadoDeAnalise) -> list[str]:
    """Compõe seções legadas e aditivas usando apenas a visão concluída."""

    resultado = _capturar_visao_fase2_validada(resultado)
    linhas = [f"Resultado da análise para: {resultado.identificador}", ""]

    total_entradas = sum(
        len(entradas)
        for entradas in resultado.entradas_por_aplicacao.values()
    )
    if total_entradas == 0:
        linhas.append(
            "Nenhuma entrada encontrada para o identificador informado."
        )
    else:
        for app, entradas in resultado.entradas_por_aplicacao.items():
            linhas.append(f"[{app}] ({len(entradas)} entradas)")
            linhas.extend(
                _formatar_entrada_fase2(
                    entrada,
                    usar_timestamp_utc=entrada.timestamp_normalizado is not None,
                )
                for entrada in entradas
            )
            linhas.append("")

    linhas.extend(_renderizar_contagens(resultado))
    _adicionar_mensagens_e_erros(linhas, resultado)

    metadados = [
        f"Categoria do cenário: {resultado.categoria_de_cenario.name}",
        f"Versão do catálogo: {resultado.versao_catalogo}",
        f"Regra aplicada: {_formatar_regra(resultado.regra_aplicada)}",
        f"Cobertura rotulada: {resultado.cobertura_rotulada}",
        "Aplicações analisadas: "
        + (", ".join(resultado.aplicacoes_analisadas) or "nenhuma"),
        "Aplicações ausentes ou inválidas: "
        + (", ".join(resultado.aplicacoes_ausentes_ou_invalidas) or "nenhuma"),
    ]
    if resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA:
        metadados.append(MENSAGEM_SEM_REGRA_CORRESPONDENTE)
    _adicionar_bloco(linhas, metadados)

    identificadores = ["Identificadores extraídos:"]
    if resultado.identificadores_extraidos:
        identificadores.extend(
            _formatar_identificador(identificador)
            for identificador in resultado.identificadores_extraidos
        )
    else:
        identificadores.append("  nenhum")
    _adicionar_bloco(linhas, identificadores)

    vinculos_iter = iter(resultado.vinculos)
    if resultado.correlacao is not None:
        vinculos_iter = iter(
            (*resultado.vinculos, *resultado.correlacao.vinculos_percorridos)
        )
    vinculos = _sem_repeticoes_por_identidade(vinculos_iter)
    bloco_vinculos = ["Vínculos:"]
    if vinculos:
        bloco_vinculos.extend(
            _formatar_vinculo(vinculo)
            for vinculo in vinculos
            if isinstance(vinculo, VinculoIdentificadores)
        )
    else:
        bloco_vinculos.append("  nenhum")
    _adicionar_bloco(linhas, bloco_vinculos)

    correlacao = resultado.correlacao
    if correlacao is None:
        bloco_correlacao = [
            "Correlação: não encontrada",
            f"  Base primária: {BaseCorrelacao.NENHUMA.name}",
            "  Bases: NENHUMA",
        ]
    else:
        status = "encontrada" if correlacao.encontrada else "não encontrada"
        bases = ", ".join(base.name for base in correlacao.bases) or "NENHUMA"
        bloco_correlacao = [
            f"Correlação: {status}",
            f"  Base primária: {correlacao.base_primaria.name}",
            f"  Bases: {bases}",
        ]
        if correlacao.motivo_seguro is not None:
            bloco_correlacao.append(f"  Motivo: {correlacao.motivo_seguro}")
        bloco_correlacao.append(
            f"  Evidências da correlação: {len(correlacao.evidencias)}"
        )
        bloco_correlacao.append(
            "  Vínculos percorridos: "
            f"{len(correlacao.vinculos_percorridos)}"
        )
    _adicionar_bloco(linhas, bloco_correlacao)

    timeline = ["Linha do tempo UTC:"]
    if resultado.linha_do_tempo:
        timeline.extend(
            _formatar_entrada_fase2(entrada, usar_timestamp_utc=True)
            for entrada in resultado.linha_do_tempo
        )
    else:
        timeline.append("  nenhuma entrada")
    _adicionar_bloco(linhas, timeline)

    sem_utc = ["Entradas sem UTC:"]
    if resultado.entradas_sem_ordenacao_temporal:
        sem_utc.extend(
            _formatar_entrada_fase2(entrada, usar_timestamp_utc=False)
            for entrada in resultado.entradas_sem_ordenacao_temporal
        )
    else:
        sem_utc.append("  nenhuma entrada")
    _adicionar_bloco(linhas, sem_utc)

    evidencias_iter = iter(resultado.evidencias)
    if correlacao is not None:
        evidencias_iter = iter(
            (*resultado.evidencias, *correlacao.evidencias)
        )
    evidencias = _sem_repeticoes_por_identidade(evidencias_iter)
    bloco_evidencias = ["Evidências:"]
    if evidencias:
        bloco_evidencias.extend(
            _formatar_evidencia(evidencia)
            for evidencia in evidencias
            if isinstance(evidencia, Evidencia)
        )
    else:
        bloco_evidencias.append("  nenhuma")
    _adicionar_bloco(linhas, bloco_evidencias)

    causa = resultado.causa_raiz
    bloco_causa = [
        f"Causa-raiz: {causa.descricao_sanitizada}",
        f"  Estado: {causa.estado.name}",
        f"  Regra causal: {_formatar_regra(causa.regra)}",
    ]
    _adicionar_bloco(linhas, bloco_causa)
    return linhas


def iterar_linhas_resultado(resultado: ResultadoDeAnalise) -> Iterator[str]:
    """Retorna linhas da Fase 2 somente para uma visão segura concluída.

    O iterador é deliberadamente estrito: objetos ``INTERNA_BRUTA`` não são
    interpretados como legados por ausência de metadados. A compatibilidade da
    Fase 1 permanece isolada no wrapper ``renderizar_resultado``.
    """

    try:
        if not isinstance(resultado, ResultadoDeAnalise):
            raise TypeError("resultado inválido")
        if resultado.estado_sanitizacao is not EstadoSanitizacao.CONCLUIDA:
            raise _VisaoFase2NaoConcluida
        linhas = tuple(_construir_linhas_fase2(resultado))
    except _VisaoFase2NaoConcluida:
        return iter((MENSAGEM_FALHA_VISAO_SEGURA,))
    except Exception:
        return iter((MENSAGEM_FALHA_APRESENTACAO,))
    return iter(linhas)


def _iterar_linhas_compativeis(
    resultado: ResultadoDeAnalise,
) -> Iterator[str]:
    """Adapta somente a forma estritamente legada para o wrapper histórico."""

    try:
        if not isinstance(resultado, ResultadoDeAnalise):
            raise TypeError("resultado inválido")
        if _resultado_tem_conteudo_fase2(resultado):
            return iterar_linhas_resultado(resultado)
        linhas = tuple(_construir_linhas_legadas(resultado))
    except Exception:
        return iter((MENSAGEM_FALHA_APRESENTACAO,))
    return iter(linhas)


def renderizar_resultado(resultado: ResultadoDeAnalise) -> str:
    """Mantém o wrapper Fase 1 e junta o iterador seguro no fluxo Fase 2."""

    try:
        return "\n".join(_iterar_linhas_compativeis(resultado))
    except Exception:
        return MENSAGEM_FALHA_APRESENTACAO


__all__ = [
    "MENSAGEM_FALHA_APRESENTACAO",
    "iterar_linhas_resultado",
    "renderizar_resultado",
]
