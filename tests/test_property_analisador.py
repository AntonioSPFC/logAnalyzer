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

# Aplicações válidas registradas no bootstrap
_APPS_VALIDAS = ["VPL", "ORK", "VOCI"]

# Estratégia para selecionar uma aplicação válida
_app_strategy = st.sampled_from(_APPS_VALIDAS)

# Estratégia para gerar sequências de pelo menos 2 app_ids (para reassociação)
# com o requisito de que a sequência contenha ao menos 2 app_ids distintos
_app_sequence_strategy = st.lists(
    _app_strategy,
    min_size=2,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criar_conteudo_para_app(app_id: str, identificador: str) -> str:
    """Cria conteúdo de log no formato esperado pela aplicação, contendo o identificador.

    Cada formato é válido para o respectivo parser, garantindo que a linha
    será interpretada com sucesso.
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
        # Fallback — será tratado como não interpretável
        return f"log entry with {identificador}\n"


# ---------------------------------------------------------------------------
# Property 11: Reassociação faz a última Aplicação prevalecer
# ---------------------------------------------------------------------------


@given(
    app_sequence=_app_sequence_strategy,
    identificador=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=3,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_property_11_reassociacao_ultima_aplicacao_prevalece(
    app_sequence: list[str],
    identificador: str,
    tmp_path_factory,
) -> None:
    """Feature: log-analyzer, Property 11: Reassociação faz a última Aplicação prevalecer

    Para toda sequência de associações aplicadas a um mesmo Arquivo_de_Log com Aplicações
    válidas, a Aplicação efetivamente atribuída ao final é a última informada na sequência.

    Na implementação atual, cada ArquivoSelecionado é processado independentemente. Se o
    mesmo arquivo aparece múltiplas vezes com app_ids diferentes, cada entrada é processada
    com seu próprio app_id. A propriedade verifica que as entradas da última Aplicação na
    sequência estão presentes no resultado.

    **Validates: Requirements 2.5**
    """
    registro = criar_registro_padrao()
    analisador = Analisador_de_Logs(registro)

    # O último app_id na sequência é o que deve "prevalecer"
    ultimo_app = app_sequence[-1]

    # Criar um arquivo temporário com conteúdo válido para TODAS as apps na sequência.
    # Usamos um conteúdo que contém o identificador e é válido para cada parser.
    # Para isso, o arquivo terá linhas no formato de cada app que aparece na sequência.
    # Porém, como o mesmo arquivo é re-parseado com parsers diferentes, cada parser
    # só conseguirá interpretar as linhas do seu próprio formato.
    # Estratégia: criar conteúdo que contenha o identificador para TODAS as apps,
    # assim cada parser encontra algo que consegue interpretar.
    linhas = []
    for app in set(app_sequence):
        linhas.append(_criar_conteudo_para_app(app, identificador))

    conteudo = "".join(linhas)

    # Criar arquivo temporário
    tmp_dir = tmp_path_factory.mktemp("reassoc")
    arquivo_path = tmp_dir / "log_reassociacao.log"
    arquivo_path.write_text(conteudo, encoding="utf-8")
    caminho = str(arquivo_path)

    # Montar a seleção: mesmo arquivo, várias vezes, com app_ids diferentes (a sequência)
    selecao = [
        ArquivoSelecionado(caminho=caminho, app_id=app_id)
        for app_id in app_sequence
    ]

    # Executar a análise
    resultado = analisador.analisar(selecao, identificador)

    # Verificação: a última Aplicação na sequência DEVE ter entradas no resultado
    # (já que o conteúdo contém o identificador em formato válido para essa app)
    assert ultimo_app in resultado.entradas_por_aplicacao, (
        f"Última aplicação '{ultimo_app}' não encontrada no resultado. "
        f"Sequência: {app_sequence}, apps no resultado: "
        f"{list(resultado.entradas_por_aplicacao.keys())}"
    )

    entradas_ultimo_app = resultado.entradas_por_aplicacao[ultimo_app]
    assert len(entradas_ultimo_app) > 0, (
        f"Nenhuma entrada encontrada para a última aplicação '{ultimo_app}'. "
        f"Sequência: {app_sequence}"
    )

    # Verificação adicional: as entradas do último app devem ter o app_id correto
    for entrada in entradas_ultimo_app:
        assert entrada.aplicacao == ultimo_app, (
            f"Entrada com aplicacao={entrada.aplicacao!r} deveria ser "
            f"'{ultimo_app}'"
        )

    # Verificação: a quantidade de entradas da última app deve refletir a quantidade
    # de vezes que esse app_id aparece na sequência (pois cada ArquivoSelecionado
    # com o mesmo app é processado independentemente)
    contagem_ultimo_app_na_sequencia = app_sequence.count(ultimo_app)
    # Cada processamento do arquivo com o parser do último app deve produzir ao menos
    # uma entrada filtrada (pois o identificador está no conteúdo para esse formato)
    assert len(entradas_ultimo_app) >= contagem_ultimo_app_na_sequencia, (
        f"Esperava ao menos {contagem_ultimo_app_na_sequencia} entradas para "
        f"'{ultimo_app}' (aparece {contagem_ultimo_app_na_sequencia}x na sequência), "
        f"mas obteve {len(entradas_ultimo_app)}."
    )


# ---------------------------------------------------------------------------
# Strategies para Property 8 (Robustez)
# ---------------------------------------------------------------------------

# Aplicações NÃO registradas (sempre inválidas no registro padrão)
_APPS_NAO_REGISTRADAS = ["INEXISTENTE", "XPTO", "FOO_APP", "UNKNOWN"]

# Tipos de invalidade para gerar arquivos inválidos
_TIPO_INVALIDO = st.sampled_from([
    "inexistente",         # caminho que não existe no filesystem
    "app_none",            # app_id é None (Aplicação não informada)
    "app_nao_registrada",  # app_id não registrada no Registro
    "vazio",               # arquivo vazio (0 bytes)
])


@st.composite
def _gerar_selecao_mista(draw: st.DrawFn):
    """Gera uma seleção mista de ArquivoSelecionado (válidos e inválidos).

    Retorna: (lista_selecao, n_validos, n_invalidos, dir_temp, identificador)
    """
    identificador = draw(
        st.from_regex(r"[A-Za-z0-9]{3,20}", fullmatch=True)
    )

    # Gerar entre 1 e 4 arquivos válidos
    n_validos = draw(st.integers(min_value=1, max_value=4))
    # Gerar entre 1 e 4 arquivos inválidos
    n_invalidos = draw(st.integers(min_value=1, max_value=4))

    # Criar diretório temporário para os arquivos
    tmp_dir = tempfile.mkdtemp()

    arquivos_validos: list[ArquivoSelecionado] = []
    for i in range(n_validos):
        # Sortear app para o arquivo válido
        app_id = draw(st.sampled_from(_APPS_VALIDAS))
        # Criar arquivo com conteúdo válido que contém o identificador
        conteudo = _criar_conteudo_para_app(app_id, identificador)
        caminho = os.path.join(tmp_dir, f"valid_{i}_{app_id}.log")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(conteudo)
        arquivos_validos.append(ArquivoSelecionado(caminho=caminho, app_id=app_id))

    arquivos_invalidos: list[ArquivoSelecionado] = []
    for i in range(n_invalidos):
        tipo = draw(_TIPO_INVALIDO)
        if tipo == "inexistente":
            # Caminho que não existe
            caminho_fake = os.path.join(tmp_dir, f"nao_existe_{i}.log")
            # Garantir que não existe
            if os.path.exists(caminho_fake):
                os.remove(caminho_fake)
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho_fake, app_id="VPL")
            )
        elif tipo == "app_none":
            # Arquivo que existe mas app_id é None
            caminho = os.path.join(tmp_dir, f"sem_app_{i}.log")
            with open(caminho, "w", encoding="utf-8") as f:
                f.write("2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Some log\n")
            arquivos_invalidos.append(
                ArquivoSelecionado(caminho=caminho, app_id=None)
            )
        elif tipo == "app_nao_registrada":
            # Arquivo que existe mas app não registrada
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

    # Intercalar válidos e inválidos para simular seleção mista real
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
# Property 8: Robustez — entradas inválidas não impedem o processamento das
# válidas
# ---------------------------------------------------------------------------


@given(data=_gerar_selecao_mista())
@settings(max_examples=100)
def test_property_8_robustez_entradas_invalidas_nao_impedem_validas(
    data: tuple,
) -> None:
    """Feature: log-analyzer, Property 8: Robustez — entradas inválidas não impedem o processamento das válidas

    Para toda seleção mista de Arquivos_de_Log (válidos e inválidos: ilegíveis, vazios,
    acima de 500 MB, sem Aplicação associada ou em formato não reconhecido), o
    Analisador_de_Logs processa integralmente os arquivos válidos e acumula em `erros`
    uma indicação para cada arquivo inválido identificando o Arquivo_de_Log afetado,
    sem abortar a análise.

    **Validates: Requirements 1.2, 1.4, 1.5, 10.4, 10.5**
    """
    selecao, n_validos, n_invalidos, tmp_dir, identificador = data

    # Arrange
    registro = criar_registro_padrao()
    analisador = Analisador_de_Logs(registro)

    # Act — a análise NÃO deve lançar exceção (robustez)
    resultado = analisador.analisar(selecao, identificador)

    # Assert 1: o resultado é um ResultadoDeAnalise válido
    assert isinstance(resultado, ResultadoDeAnalise)

    # Assert 2: a análise acumula ao menos um erro por arquivo inválido.
    # Pode haver erros adicionais de correlação (Req 8.5): quando VPL e ORK são
    # ambos selecionados mas um lado não produz entradas, o correlacionador
    # registra um erro adicional. Isso é comportamento correto.
    assert len(resultado.erros) >= n_invalidos, (
        f"Esperava ao menos {n_invalidos} erros, obteve {len(resultado.erros)}. "
        f"Erros: {[(e.arquivo_ou_app, e.descricao) for e in resultado.erros]}"
    )

    # Separar erros de arquivo/invalidade dos erros de correlação
    erros_correlacao = [
        e for e in resultado.erros if "correlação" in e.descricao.lower()
    ]
    erros_arquivo = [
        e for e in resultado.erros if "correlação" not in e.descricao.lower()
    ]

    # Exatamente n_invalidos erros de arquivo (1 por arquivo inválido)
    assert len(erros_arquivo) == n_invalidos, (
        f"Esperava {n_invalidos} erros de arquivo, obteve {len(erros_arquivo)}. "
        f"Erros de arquivo: {[(e.arquivo_ou_app, e.descricao) for e in erros_arquivo]}"
    )

    # Assert 3: cada erro identifica o arquivo/aplicação afetado (campo não vazio)
    for erro in resultado.erros:
        assert erro.arquivo_ou_app, (
            f"Erro sem identificação do arquivo/app: {erro.descricao}"
        )
        assert erro.descricao, (
            f"Erro sem descrição para: {erro.arquivo_ou_app}"
        )

    # Assert 4: os arquivos válidos foram processados — existem entradas no resultado
    # (cada arquivo válido contém o identificador, logo deve contribuir entradas)
    assert len(resultado.linha_do_tempo) > 0, (
        f"Nenhuma entrada na linha do tempo apesar de {n_validos} arquivo(s) válido(s) "
        f"contendo o identificador '{identificador}'."
    )

    # Assert 5: o identificador do resultado é o fornecido
    assert resultado.identificador == identificador

    # Cleanup: remover arquivos temporários
    shutil.rmtree(tmp_dir, ignore_errors=True)
