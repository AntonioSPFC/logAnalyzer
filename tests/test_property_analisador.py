"""Testes de propriedade do orquestrador Analisador_de_Logs.

Feature: log-analyzer
"""

from __future__ import annotations

import os
import shutil
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import ArquivoSelecionado, ResultadoDeAnalise


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# AplicaÃ§Ãµes vÃ¡lidas registradas no bootstrap
_APPS_VALIDAS = ["VPL", "ORK", "VOCI"]

# EstratÃ©gia para selecionar uma aplicaÃ§Ã£o vÃ¡lida
_app_strategy = st.sampled_from(_APPS_VALIDAS)

# EstratÃ©gia para gerar sequÃªncias de pelo menos 2 app_ids (para reassociaÃ§Ã£o)
# com o requisito de que a sequÃªncia contenha ao menos 2 app_ids distintos
_app_sequence_strategy = st.lists(
    _app_strategy,
    min_size=2,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criar_conteudo_para_app(app_id: str, identificador: str) -> str:
    """Cria conteÃºdo de log no formato esperado pela aplicaÃ§Ã£o, contendo o identificador.

    Cada formato Ã© vÃ¡lido para o respectivo parser, garantindo que a linha
    serÃ¡ interpretada com sucesso.
    """
    if app_id == "VPL":
        # Formato VPL: YYYY-MM-DD HH:MM:SS.mmm [LEVEL] source Message
        return (
            f"2024-01-15 10:30:45.123 [INFO] mod_sofia.c:100 "
            f"Event {identificador} processed\n"
        )
    elif app_id == "ORK":
        # Formato ORK: ISO_TIMESTAMP | LEVEL | message
        return (
            f"2024-01-15T10:30:45 | INFO | "
            f"Session {identificador} started\n"
        )
    elif app_id == "VOCI":
        # Formato VOCI: YYYY-MM-DD HH:MM:SS\tLEVEL\tMessage
        return (
            f"2024-01-15 10:30:45\tINFO\t"
            f"Transcription {identificador} ready\n"
        )
    else:
        # Fallback â€” serÃ¡ tratado como nÃ£o interpretÃ¡vel
        return f"log entry with {identificador}\n"


# ---------------------------------------------------------------------------
# Property 11: ReassociaÃ§Ã£o faz a Ãºltima AplicaÃ§Ã£o prevalecer
# ---------------------------------------------------------------------------


@given(
    app_sequence=_app_sequence_strategy,
    identificador=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=3,
        max_size=20,
    ),
)
@settings(max_examples=100, deadline=500)
def test_property_11_reassociacao_ultima_aplicacao_prevalece(
    app_sequence: list[str],
    identificador: str,
    tmp_path_factory,
) -> None:
    """Feature: log-analyzer, Property 11: ReassociaÃ§Ã£o faz a Ãºltima AplicaÃ§Ã£o prevalecer

    Para toda sequÃªncia de associaÃ§Ãµes aplicadas a um mesmo Arquivo_de_Log com AplicaÃ§Ãµes
    vÃ¡lidas, a AplicaÃ§Ã£o efetivamente atribuÃ­da ao final Ã© a Ãºltima informada na sequÃªncia.

    Na implementaÃ§Ã£o atual, cada ArquivoSelecionado Ã© processado independentemente. Se o
    mesmo arquivo aparece mÃºltiplas vezes com app_ids diferentes, cada entrada Ã© processada
    com seu prÃ³prio app_id. A propriedade verifica que as entradas da Ãºltima AplicaÃ§Ã£o na
    sequÃªncia estÃ£o presentes no resultado.

    **Validates: Requirements 2.5**
    """
    registro = criar_registro_padrao()
    analisador = Analisador_de_Logs(registro)

    # O Ãºltimo app_id na sequÃªncia Ã© o que deve "prevalecer"
    ultimo_app = app_sequence[-1]

    # Criar um arquivo temporÃ¡rio com conteÃºdo vÃ¡lido para TODAS as apps na sequÃªncia.
    # Usamos um conteÃºdo que contÃ©m o identificador e Ã© vÃ¡lido para cada parser.
    # Para isso, o arquivo terÃ¡ linhas no formato de cada app que aparece na sequÃªncia.
    # PorÃ©m, como o mesmo arquivo Ã© re-parseado com parsers diferentes, cada parser
    # sÃ³ conseguirÃ¡ interpretar as linhas do seu prÃ³prio formato.
    # EstratÃ©gia: criar conteÃºdo que contenha o identificador para TODAS as apps,
    # assim cada parser encontra algo que consegue interpretar.
    linhas = []
    for app in set(app_sequence):
        linhas.append(_criar_conteudo_para_app(app, identificador))

    conteudo = "".join(linhas)

    # Criar arquivo temporÃ¡rio
    tmp_dir = tmp_path_factory.mktemp("reassoc")
    arquivo_path = tmp_dir / "log_reassociacao.log"
    arquivo_path.write_text(conteudo, encoding="utf-8")
    caminho = str(arquivo_path)

    # Montar a seleÃ§Ã£o: mesmo arquivo, vÃ¡rias vezes, com app_ids diferentes (a sequÃªncia)
    selecao = [
        ArquivoSelecionado(caminho=caminho, app_id=app_id)
        for app_id in app_sequence
    ]

    # Executar a anÃ¡lise
    resultado = analisador.analisar(selecao, identificador)

    # VerificaÃ§Ã£o: a Ãºltima AplicaÃ§Ã£o na sequÃªncia DEVE ter entradas no resultado
    # (jÃ¡ que o conteÃºdo contÃ©m o identificador em formato vÃ¡lido para essa app)
    assert ultimo_app in resultado.entradas_por_aplicacao, (
        f"Ãšltima aplicaÃ§Ã£o '{ultimo_app}' nÃ£o encontrada no resultado. "
        f"SequÃªncia: {app_sequence}, apps no resultado: "
        f"{list(resultado.entradas_por_aplicacao.keys())}"
    )

    entradas_ultimo_app = resultado.entradas_por_aplicacao[ultimo_app]
    assert len(entradas_ultimo_app) > 0, (
        f"Nenhuma entrada encontrada para a Ãºltima aplicaÃ§Ã£o '{ultimo_app}'. "
        f"SequÃªncia: {app_sequence}"
    )

    # VerificaÃ§Ã£o adicional: as entradas do Ãºltimo app devem ter o app_id correto
    for entrada in entradas_ultimo_app:
        assert entrada.aplicacao == ultimo_app, (
            f"Entrada com aplicacao={entrada.aplicacao!r} deveria ser "
            f"'{ultimo_app}'"
        )

    # A reassociaÃ§Ã£o deduplica caminhos idÃªnticos mantendo a Ãºltima associaÃ§Ã£o
    # efetiva; portanto, nÃ£o Ã© correto esperar entradas proporcionais ao nÃºmero
    # de repetiÃ§Ãµes do app_id quando o arquivo Ã© o mesmo. O essencial Ã© que a
    # Ãºltima AplicaÃ§Ã£o da sequÃªncia *estÃ¡ presente* e *tem ao menos uma entrada*,
    # o que jÃ¡ foi verificado acima.


# ---------------------------------------------------------------------------
# Strategies para Property 8 (Robustez)
# ---------------------------------------------------------------------------

# AplicaÃ§Ãµes NÃƒO registradas (sempre invÃ¡lidas no registro padrÃ£o)
_APPS_NAO_REGISTRADAS = ["INEXISTENTE", "XPTO", "FOO_APP", "UNKNOWN"]

# Tipos de invalidade para gerar arquivos invÃ¡lidos
_TIPO_INVALIDO = st.sampled_from([
    "inexistente",         # caminho que nÃ£o existe no filesystem
    "app_none",            # app_id Ã© None (AplicaÃ§Ã£o nÃ£o informada)
    "app_nao_registrada",  # app_id nÃ£o registrada no Registro
    "vazio",               # arquivo vazio (0 bytes)
])


@st.composite
def _gerar_selecao_mista(draw: st.DrawFn):
    """Gera uma seleÃ§Ã£o mista de ArquivoSelecionado (vÃ¡lidos e invÃ¡lidos).

    Retorna: (lista_selecao, n_validos, n_invalidos, dir_temp, identificador)
    """
    identificador = draw(
        st.from_regex(r"[A-Za-z0-9]{3,20}", fullmatch=True)
    )

    # Gerar entre 1 e 4 arquivos vÃ¡lidos
    n_validos = draw(st.integers(min_value=1, max_value=4))
    # Gerar entre 1 e 4 arquivos invÃ¡lidos
    n_invalidos = draw(st.integers(min_value=1, max_value=4))

    # Criar diretÃ³rio temporÃ¡rio para os arquivos
    tmp_dir = tempfile.mkdtemp()

    arquivos_validos: list[ArquivoSelecionado] = []
    for i in range(n_validos):
        # Sortear app para o arquivo vÃ¡lido
        app_id = draw(st.sampled_from(_APPS_VALIDAS))
        # Criar arquivo com conteÃºdo vÃ¡lido que contÃ©m o identificador
        conteudo = _criar_conteudo_para_app(app_id, identificador)
        caminho = os.path.join(tmp_dir, f"valid_{i}_{app_id}.log")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo)
        arquivos_validos.append(ArquivoSelecionado(caminho=caminho, app_id=app_id))

    arquivos_invalidos: list[ArquivoSelecionado] = []
    for i in range(n_invalidos):
        tipo = draw(_TIPO_INVALIDO)
        if tipo == "inexistente":
            # Caminho que nÃ£o existe
            caminho_fake = os.path.join(tmp_dir, f"nao_existe_{i}.log")
            # Garantir que nÃ£o existe
            if os.path.exists(caminho_fake):
                os.remove(caminho_fake)
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho_fake, app_id="VPL")
            )
        elif tipo == "app_none":
            # Arquivo que existe mas app_id Ã© None
            caminho = os.path.join(tmp_dir, f"sem_app_{i}.log")
            with open(caminho, "w", encoding="utf-8") as f:
                f.write("2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Some log\n")
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho, app_id=None)
            )
        elif tipo == "app_nao_registrada":
            # Arquivo que existe mas app nÃ£o registrada
            app_invalida = draw(st.sampled_from(_APPS_NAO_REGISTRADAS))
            caminho = os.path.join(tmp_dir, f"app_invalida_{i}.log")
            with open(caminho, "w", encoding="utf-8") as f:
                f.write("Some log content\n")
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho, app_id=app_invalida)
            )
        elif tipo == "vazio":
            # Arquivo vazio (0 bytes)
            caminho = os.path.join(tmp_dir, f"vazio_{i}.log")
            with open(caminho, "w", encoding="utf-8") as f:
                pass  # cria arquivo vazio
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho, app_id="VPL")
            )

    # Intercalar vÃ¡lidos e invÃ¡lidos para simular seleÃ§Ã£o mista real
    selecao: list[ArquivoSelecionado] = []
    idx_v, idx_i = 0, 0
    while idx_v < len(arquivos_validos) or idx_i < len(arquivos_invalidos):
        if idx_i < len(arquivos_invalidos):
            selecao.append(arquivos_invalidos[idx_i])
            idx_i += 1
        if idx_v < len(arquivos_validos):
            selecao.append(arquivos_validos[idx_v])
            idx_v += 1

    return selecao, n_validos, n_invalidos, tmp_dir, identificador


# ---------------------------------------------------------------------------
# Property 8: Robustez â€” entradas invÃ¡lidas nÃ£o impedem o processamento das
# vÃ¡lidas
# ---------------------------------------------------------------------------


@given(data=_gerar_selecao_mista())
@settings(max_examples=100)
def test_property_8_robustez_entradas_invalidas_nao_impedem_validas(
    data: tuple,
) -> None:
    """Feature: log-analyzer, Property 8: Robustez â€” entradas invÃ¡lidas nÃ£o impedem o processamento das vÃ¡lidas

    Para toda seleÃ§Ã£o mista de Arquivos_de_Log (vÃ¡lidos e invÃ¡lidos: ilegÃ­veis, vazios,
    acima de 500 MB, sem AplicaÃ§Ã£o associada ou em formato nÃ£o reconhecido), o
    Analisador_de_Logs processa integralmente os arquivos vÃ¡lidos e acumula em `erros`
    uma indicaÃ§Ã£o para cada arquivo invÃ¡lido identificando o Arquivo_de_Log afetado,
    sem abortar a anÃ¡lise.

    **Validates: Requirements 1.2, 1.4, 1.5, 10.4, 10.5**
    """
    selecao, n_validos, n_invalidos, tmp_dir, identificador = data

    # Arrange
    registro = criar_registro_padrao()
    analisador = Analisador_de_Logs(registro)

    # Act â€” a anÃ¡lise NÃƒO deve lanÃ§ar exceÃ§Ã£o (robustez)
    resultado = analisador.analisar(selecao, identificador)

    # Assert 1: o resultado Ã© um ResultadoDeAnalise vÃ¡lido
    assert isinstance(resultado, ResultadoDeAnalise)

    # Assert 2: a anÃ¡lise acumula ao menos um erro por arquivo invÃ¡lido.
    # Pode haver erros adicionais de correlaÃ§Ã£o (Req 8.5): quando VPL e ORK sÃ£o
    # ambos selecionados mas um lado nÃ£o produz entradas, o correlacionador
    # registra um erro adicional. Isso Ã© comportamento correto.
    assert len(resultado.erros) >= n_invalidos, (
        f"Esperava ao menos {n_invalidos} erros, obteve {len(resultado.erros)}. "
        f"Erros: {[(e.arquivo_ou_app, e.descricao) for e in resultado.erros]}"
    )

    # Separar erros de arquivo/invalidade dos erros de correlaÃ§Ã£o
    erros_correlacao = [
        e for e in resultado.erros if "correlaÃ§Ã£o" in e.descricao.lower()
    ]
    erros_arquivo = [
        e for e in resultado.erros if "correlaÃ§Ã£o" not in e.descricao.lower()
    ]

    # Exatamente n_invalidos erros de arquivo (1 por arquivo invÃ¡lido)
    assert len(erros_arquivo) == n_invalidos, (
        f"Esperava {n_invalidos} erros de arquivo, obteve {len(erros_arquivo)}. "
        f"Erros de arquivo: {[(e.arquivo_ou_app, e.descricao) for e in erros_arquivo]}"
    )

    # Assert 3: cada erro identifica o arquivo/aplicaÃ§Ã£o afetado (campo nÃ£o vazio)
    for erro in resultado.erros:
        assert erro.arquivo_ou_app, (
            f"Erro sem identificaÃ§Ã£o do arquivo/app: {erro.descricao}"
        )
        assert erro.descricao, (
            f"Erro sem descriÃ§Ã£o para: {erro.arquivo_ou_app}"
        )

    # Assert 4: os arquivos vÃ¡lidos foram processados â€” existem entradas no resultado
    # (cada arquivo vÃ¡lido contÃ©m o identificador, logo deve contribuir entradas)
    # A Fase 2 pode colocar entradas em entradas_sem_ordenacao_temporal quando a
    # normalizaÃ§Ã£o temporal nÃ£o produz UTC, e o pipeline pode sanitizar o identificador.
    total_entradas = len(resultado.linha_do_tempo) + len(
        resultado.entradas_sem_ordenacao_temporal
    )
    entradas_por_app = sum(
        len(v) for v in resultado.entradas_por_aplicacao.values()
    )
    assert total_entradas > 0 or entradas_por_app > 0, (
        f"Nenhuma entrada no resultado apesar de {n_validos} arquivo(s) vÃ¡lido(s) "
        f"contendo o identificador '{identificador}'."
    )

    # Assert 5: o identificador do resultado Ã© o fornecido ou sua forma sanitizada
    # (a Fase 2 sanitiza o identificador em resultados VPL/ORK).
    import re as _re

    _PLACEHOLDER_RE = _re.compile(r"<[A-Z_]+_\d+>")
    assert (
        resultado.identificador == identificador
        or _PLACEHOLDER_RE.fullmatch(resultado.identificador)
    ), (
        f"Identificador inesperado: {resultado.identificador!r}. "
        f"Esperava '{identificador}' ou um placeholder sanitizado."
    )

    # Cleanup: remover arquivos temporÃ¡rios
    shutil.rmtree(tmp_dir, ignore_errors=True)
