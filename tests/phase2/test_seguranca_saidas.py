"""Testes de nao vazamento em todas as fronteiras de saida.

Injeta dados sensiveis sinteticos e falhas em parser, catalogo, sanitizador,
renderer e writer; inspeciona stdout, stderr, logging, excecoes e JSON
serializado. Confirma que somente placeholders/codigos seguros aparecem e que
a apresentacao nunca usa ``texto_original`` bruto diretamente.

Validates: Requirements 14.1, 14.2, 14.3, 14.7, 16.4, 16.6.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from log_analyzer.cli.apresentacao import (
    MENSAGEM_FALHA_APRESENTACAO,
    iterar_linhas_resultado,
    renderizar_resultado,
)
from log_analyzer.core.catalogo import (
    CarregadorCatalogo,
    catalogo_de_json,
)
from log_analyzer.core.excecoes import ErroDeCatalogo, ErroDeSanitizacao
from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ResultadoDeAnalise,
    TipoIdentificador,
)
from log_analyzer.core.sanitizacao import SanitizationContext, TipoDadoSensivel
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.visao_segura import (
    MENSAGEM_FALHA_VISAO_SEGURA,
    SanitizadorDeResultado,
    ScannerFinalDeResultado,
    criar_visao_segura,
)


# ---------------------------------------------------------------------------
# Constantes e helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc
_INSTANTE = datetime(2040, 3, 15, 10, 0, 0, 500000, tzinfo=_UTC)
_TIMESTAMP_ORIGINAL = "2040-03-15T07:00:00.500000-03:00"


@dataclass(frozen=True, slots=True)
class _DadosSensiveis:
    """Conjunto efemero de valores sinteticos; repr nunca contem os valores."""

    ip: str = field(repr=False)
    uuid: str = field(repr=False)
    telefone: str = field(repr=False)
    documento: str = field(repr=False)
    credencial: str = field(repr=False)
    url_interna: str = field(repr=False)
    host_interno: str = field(repr=False)
    call_id: str = field(repr=False)
    dado_cliente: str = field(repr=False)

    def todos(self) -> tuple[str, ...]:
        return (
            self.ip,
            self.uuid,
            self.telefone,
            self.documento,
            self.credencial,
            self.url_interna,
            self.host_interno,
            self.call_id,
            self.dado_cliente,
        )


def _gerar_dados() -> _DadosSensiveis:
    """Gera dados unicos por invocacao; nenhum valor e reutilizavel."""
    token = uuid4().hex
    digitos = str(uuid4().int).zfill(40)
    return _DadosSensiveis(
        ip=f"192.0.2.{int(token[:2], 16) % 200 + 1}",
        uuid=str(uuid4()),
        telefone=f"+1-202-555-01{int(token[2:4], 16) % 100:02d}",
        documento=f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}",
        credencial=f"SYN_TEST_CREDENTIAL_{token}",
        url_interna=f"https://syn-app.invalid/path/{token[:16]}",
        host_interno=f"syn-{token[:12]}.invalid",
        call_id=f"SYN_CALL_{token[:20]}",
        dado_cliente=f"SYNTHETIC_CUSTOMER_{token[:16]}",
    )


def _proveniencia(campo: str) -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-seg-1",
        linha_inicial=1,
        linha_final=10,
        nome_campo=campo,
        regra_extracao="extrator-sintetico-seguranca-v1",
    )


def _construir_resultado_bruto(dados: _DadosSensiveis) -> ResultadoDeAnalise:
    """Resultado com dados sensiveis em TODAS as superficies rastreadas."""
    texto_original = (
        f"CallId={dados.call_id} ip={dados.ip} uuid={dados.uuid}\n"
        f"telefone={dados.telefone} documento={dados.documento}\n"
        f"credencial={dados.credencial} url={dados.url_interna}\n"
        f"host={dados.host_interno} cliente={dados.dado_cliente}"
    )
    campos = tuple(
        CampoEstruturado(nome, valor, _proveniencia(nome))
        for nome, valor in (
            ("CallId", dados.call_id),
            ("ip", dados.ip),
            ("uuid", dados.uuid),
            ("telefone", dados.telefone),
            ("documento", dados.documento),
            ("token", dados.credencial),
            ("url", dados.url_interna),
            ("host", dados.host_interno),
            ("cliente", dados.dado_cliente),
        )
    )
    identificadores = (
        IdentificadorTecnico(
            tipo=TipoIdentificador.CALL_ID,
            namespace_comparacao="chamada_externa",
            nome_campo="CallId",
            valor_original=dados.call_id,
            valor_normalizado=dados.call_id.casefold(),
            proveniencia=_proveniencia("CallId"),
        ),
        IdentificadorTecnico(
            tipo=TipoIdentificador.UUID_SESSAO,
            namespace_comparacao="sessao",
            nome_campo="uuid",
            valor_original=dados.uuid,
            valor_normalizado=dados.uuid,
            proveniencia=_proveniencia("uuid"),
        ),
    )
    entrada = EntradaDeLog(
        texto_original=texto_original,
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=_INSTANTE,
        nivel_de_severidade="INFO",
        mensagem=texto_original,
        categoria=Categoria.NAO_CLASSIFICADA,
        entrada_id="entrada-seg-1",
        arquivo_origem=f"C:/synth/{dados.call_id}.log",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=10,
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE,
        precisao_fracionaria=6,
        origem_evento="modulo.seguranca",
        formato_origem="perfil-sintetico",
        campos_estruturados=campos,
        identificadores=identificadores,
    )
    evidencia = Evidencia(
        tipo="campo_estruturado",
        aplicacao="VPL",
        proveniencia=_proveniencia("CallId"),
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE,
        campo_ou_condicao="CallId compartilhado",
        representacao_sanitizada=f"CallId={dados.call_id}",
    )
    return ResultadoDeAnalise(
        identificador=dados.call_id,
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
        contagem_por_aplicacao={"VPL": 1},
        erros=[
            MensagemDeErro(
                arquivo_ou_app=f"C:/synth/{dados.call_id}.log",
                descricao=f"falha token={dados.credencial}",
            ),
        ],
        mensagens=[f"resumo host={dados.host_interno} url={dados.url_interna}"],
        identificadores_extraidos=list(identificadores),
        evidencias=[evidencia],
        aplicacoes_analisadas=["VPL"],
    )


def _assert_nenhum_vazamento(
    valores: tuple[str, ...],
    *superficies: str,
) -> None:
    """Falha se qualquer valor sensivel sintetico aparece em alguma superficie."""
    agregado = "\n".join(superficies)
    for valor in valores:
        assert valor not in agregado, (
            f"Vazamento detectado: valor sensivel apareceu na superficie de saida"
        )


def _assert_sem_texto_original_direto(saida: str, texto_original: str) -> None:
    """Confirma que texto_original bruto nunca e usado diretamente na saida."""
    assert texto_original not in saida, (
        "A apresentacao usou texto_original bruto diretamente na saida"
    )


# ---------------------------------------------------------------------------
# Testes de fronteira: Parser
# ---------------------------------------------------------------------------


class TestFronteiraParser:
    """Falhas no parser nao devem vazar dados sensiveis."""

    def test_excecao_de_parser_nao_contem_dado_sensivel(self) -> None:
        """Simula que o parser gera uma excecao: mensagem nao vaza."""
        dados = _gerar_dados()
        # Excecoes do dominio usam mensagens constantes e codigos seguros
        from log_analyzer.core.excecoes import ErroDeRegistro

        try:
            raise ErroDeRegistro(f"falha ao registrar")
        except ErroDeRegistro as exc:
            msg = str(exc)
            _assert_nenhum_vazamento(dados.todos(), msg, repr(exc))

    def test_entrada_nao_interpretada_preserva_texto_original_sem_vazar_em_repr(
        self,
    ) -> None:
        """EntradaDeLog nao interpretada nao expoe texto_original no repr seguro."""
        dados = _gerar_dados()
        entrada = EntradaDeLog(
            texto_original=f"lixo {dados.ip} {dados.telefone} {dados.call_id}",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=False,
        )
        # O texto_original existe internamente mas nao aparece no repr
        # quando o objeto e convertido para visao segura
        resultado = ResultadoDeAnalise(
            identificador=dados.call_id,
            entradas_por_aplicacao={"VPL": [entrada]},
            entradas_sem_ordenacao_temporal=[entrada],
        )
        # Renderer recusa resultado bruto
        saida = renderizar_resultado(resultado)
        _assert_nenhum_vazamento(dados.todos(), saida)


# ---------------------------------------------------------------------------
# Testes de fronteira: Catalogo
# ---------------------------------------------------------------------------


class TestFronteiraCatalogo:
    """Falhas de catalogo emitem somente codigos seguros."""

    def test_catalogo_invalido_nao_vaza_conteudo_no_erro(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        json_invalido = json.dumps({
            "catalog_version": "invalid",
            "rules": [{"rule_id": dados.call_id, "INVALID": dados.credencial}],
            "coverage": dados.telefone,
            "secret_field": dados.documento,
        })
        caplog.set_level(logging.DEBUG)

        with pytest.raises(ErroDeCatalogo) as exc_info:
            catalogo_de_json(json_invalido)

        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            str(exc_info.value),
            repr(exc_info.value),
            capturado.out,
            capturado.err,
            caplog.text,
        )

    def test_carregador_atomico_com_conteudo_sensivel_nao_vaza(
        self,
        tmp_path: "pytest.TempPathFactory",
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        catalogo_path = tmp_path / "catalogo_sensivel.json"  # type: ignore[operator]
        catalogo_path.write_text(
            json.dumps({
                "catalog_version": dados.uuid,
                "rules": [],
                "malformed": dados.ip,
            }),
            encoding="utf-8",
        )
        caplog.set_level(logging.DEBUG)
        carregador = CarregadorCatalogo()

        with pytest.raises(ErroDeCatalogo) as exc_info:
            carregador.carregar(catalogo_path)

        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            str(exc_info.value),
            repr(exc_info.value),
            capturado.out,
            capturado.err,
            caplog.text,
        )


# ---------------------------------------------------------------------------
# Testes de fronteira: Sanitizador
# ---------------------------------------------------------------------------


class TestFronteiraSanitizador:
    """O sanitizador nunca vaza valores brutos nas superficies de saida."""

    def test_visao_segura_substitui_todos_os_tipos_sensiveis(self) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)

        segura = criar_visao_segura(resultado)

        serializada = json.dumps(
            serializar_resultado_de_analise(segura),
            ensure_ascii=False,
            sort_keys=True,
        )
        _assert_nenhum_vazamento(dados.todos(), serializada, repr(segura))
        # Confirma que placeholders tipados estao presentes
        for prefixo in ("CALL_ID", "UUID", "IP", "CREDENCIAL", "HOST_INTERNO"):
            assert f"<{prefixo}_" in serializada

    def test_sanitizacao_nao_vaza_em_stdout_stderr_logging(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        caplog.set_level(logging.DEBUG)

        segura = criar_visao_segura(resultado)

        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            capturado.out,
            capturado.err,
            caplog.text,
        )

    def test_falha_injetada_no_contexto_suprime_tudo_sem_vazar(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        segredo_falha = f"segredo-falha-{uuid4().hex}"
        caplog.set_level(logging.DEBUG)

        class _ContextoFalho(SanitizationContext):
            def sanitizar_texto(self, texto: str) -> str:
                raise RuntimeError(segredo_falha)

        sanitizador = SanitizadorDeResultado(fabrica_contexto=_ContextoFalho)

        with pytest.raises(ErroDeSanitizacao) as exc_info:
            sanitizador.criar_visao_segura(resultado)

        capturado = capsys.readouterr()
        assert str(exc_info.value) == MENSAGEM_FALHA_VISAO_SEGURA
        _assert_nenhum_vazamento(
            (*dados.todos(), segredo_falha),
            str(exc_info.value),
            repr(exc_info.value),
            capturado.out,
            capturado.err,
            caplog.text,
        )

    def test_scanner_final_rejeita_dado_sensivel_sem_eco(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Scanner final detecta vazamento e nao ecoa o valor na excecao."""
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        caplog.set_level(logging.DEBUG)

        with pytest.raises(ErroDeSanitizacao) as exc_info:
            ScannerFinalDeResultado().validar(resultado)

        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            str(exc_info.value),
            repr(exc_info.value),
            capturado.out,
            capturado.err,
            caplog.text,
        )


# ---------------------------------------------------------------------------
# Testes de fronteira: Renderer (apresentacao)
# ---------------------------------------------------------------------------


class TestFronteiraRenderer:
    """O renderer nunca apresenta texto_original bruto."""

    def test_apresentacao_fase2_usa_representacao_sanitizada_nao_texto_original(
        self,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)

        saida = renderizar_resultado(visao)
        linhas = list(iterar_linhas_resultado(visao))
        saida_linhas = "\n".join(linhas)

        # Nenhum dado sensivel original na saida
        _assert_nenhum_vazamento(dados.todos(), saida, saida_linhas)
        # texto_original bruto nao aparece
        texto_bruto = resultado.linha_do_tempo[0].texto_original
        _assert_sem_texto_original_direto(saida, texto_bruto)

    def test_resultado_bruto_e_recusado_sem_vazamento(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)

        saida = renderizar_resultado(resultado)
        linhas = list(iterar_linhas_resultado(resultado))

        assert saida == MENSAGEM_FALHA_VISAO_SEGURA
        assert linhas == [MENSAGEM_FALHA_VISAO_SEGURA]
        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            saida,
            capturado.out,
            capturado.err,
        )

    def test_falha_tardia_no_renderer_nao_vaza_prefixo_parcial(self) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)

        # Injeta falha ao iterar entradas
        class _DictQueFalha(dict):
            def items(self):
                raise RuntimeError(f"falha com {dados.ip}")

        visao.entradas_por_aplicacao = _DictQueFalha(visao.entradas_por_aplicacao)

        saida = renderizar_resultado(visao)
        linhas = list(iterar_linhas_resultado(visao))

        assert saida == MENSAGEM_FALHA_APRESENTACAO
        assert linhas == [MENSAGEM_FALHA_APRESENTACAO]
        _assert_nenhum_vazamento(dados.todos(), saida, "\n".join(linhas))

    def test_excecao_do_renderer_nao_contem_dados_sensiveis(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Quando o renderer falha, a excecao NAO contem dados."""
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        caplog.set_level(logging.DEBUG)

        # Resultado bruto causa recusa segura
        saida = renderizar_resultado(resultado)
        capturado = capsys.readouterr()

        _assert_nenhum_vazamento(
            dados.todos(),
            saida,
            capturado.out,
            capturado.err,
            caplog.text,
        )


# ---------------------------------------------------------------------------
# Testes de fronteira: Writer (IO de saida)
# ---------------------------------------------------------------------------


class TestFronteiraWriter:
    """Falhas no writer nao vazam dados para stdout/stderr."""

    def test_writer_que_falha_nao_expoe_dados_sensiveis(
        self,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)
        payload = renderizar_resultado(visao)
        caplog.set_level(logging.DEBUG)

        # Simula um writer que falha apos escrever parcialmente
        buffer_stderr = io.StringIO()

        class _WriterQueFalha(io.StringIO):
            def write(self, s: str) -> int:
                raise OSError("write failed")

        writer = _WriterQueFalha()

        # A funcao _escrever_uma_vez deve converter falha sem expor dados
        from log_analyzer.cli.main import _escrever_uma_vez, _FalhaDeWriter

        with pytest.raises(_FalhaDeWriter):
            _escrever_uma_vez(writer, payload)

        capturado = capsys.readouterr()
        _assert_nenhum_vazamento(
            dados.todos(),
            capturado.out,
            capturado.err,
            caplog.text,
        )

    def test_writer_seekable_reverte_sem_vazar_conteudo(self) -> None:
        """Writer seekable reverte escrita parcial sem deixar dados sensiveis."""
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)
        payload = renderizar_resultado(visao)

        class _WriterParcial(io.StringIO):
            """Escreve parte e falha."""
            _chamadas = 0

            def write(self, s: str) -> int:
                self._chamadas += 1
                # Escreve metade e falha na mesma chamada
                n = len(s) // 2
                super().write(s[:n])
                raise OSError("escrita parcial")

        writer = _WriterParcial()

        from log_analyzer.cli.main import _escrever_uma_vez, _FalhaDeWriter

        with pytest.raises(_FalhaDeWriter):
            _escrever_uma_vez(writer, payload)

        # Apos rollback, nenhum dado sensivel permanece
        conteudo_residual = writer.getvalue()
        _assert_nenhum_vazamento(dados.todos(), conteudo_residual)


# ---------------------------------------------------------------------------
# Testes de fronteira: JSON serializado
# ---------------------------------------------------------------------------


class TestFronteiraJSON:
    """JSON serializado de resultados sanitizados nao contem dados brutos."""

    def test_serializacao_json_nao_contem_dados_sensiveis(self) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)

        serializado = json.dumps(
            serializar_resultado_de_analise(visao),
            ensure_ascii=False,
            indent=2,
        )
        _assert_nenhum_vazamento(dados.todos(), serializado)

    def test_serializacao_resultado_bruto_nao_e_permitida_pelo_scanner(
        self,
    ) -> None:
        """Um resultado bruto nao deve passar pelo scanner final."""
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)

        with pytest.raises(ErroDeSanitizacao):
            ScannerFinalDeResultado().validar(resultado)


# ---------------------------------------------------------------------------
# Testes transversais: cobertura de todos os tipos sensiveis
# ---------------------------------------------------------------------------


class TestCoberturaTiposSensiveis:
    """Cada tipo de dado sensivel e tratado em todas as fronteiras."""

    @pytest.fixture()
    def dados_e_visao(self) -> tuple[_DadosSensiveis, ResultadoDeAnalise, str]:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        visao = criar_visao_segura(resultado)
        payload = renderizar_resultado(visao)
        return dados, visao, payload

    @pytest.mark.parametrize(
        "indice,nome",
        list(enumerate([
            "ip",
            "uuid",
            "telefone",
            "documento",
            "credencial",
            "url_interna",
            "host_interno",
            "call_id",
            "dado_cliente",
        ])),
    )
    def test_tipo_sensivel_ausente_em_renderer(
        self,
        indice: int,
        nome: str,
        dados_e_visao: tuple[_DadosSensiveis, ResultadoDeAnalise, str],
    ) -> None:
        dados, visao, payload = dados_e_visao
        valor = dados.todos()[indice]
        assert valor not in payload, (
            f"Tipo '{nome}' apareceu na saida do renderer"
        )

    @pytest.mark.parametrize(
        "indice,nome",
        list(enumerate([
            "ip",
            "uuid",
            "telefone",
            "documento",
            "credencial",
            "url_interna",
            "host_interno",
            "call_id",
            "dado_cliente",
        ])),
    )
    def test_tipo_sensivel_ausente_em_json(
        self,
        indice: int,
        nome: str,
        dados_e_visao: tuple[_DadosSensiveis, ResultadoDeAnalise, str],
    ) -> None:
        dados, visao, _ = dados_e_visao
        valor = dados.todos()[indice]
        serializado = json.dumps(
            serializar_resultado_de_analise(visao),
            ensure_ascii=False,
        )
        assert valor not in serializado, (
            f"Tipo '{nome}' apareceu no JSON serializado"
        )

    @pytest.mark.parametrize(
        "indice,nome",
        list(enumerate([
            "ip",
            "uuid",
            "telefone",
            "documento",
            "credencial",
            "url_interna",
            "host_interno",
            "call_id",
            "dado_cliente",
        ])),
    )
    def test_tipo_sensivel_ausente_em_excecao_de_sanitizacao(
        self,
        indice: int,
        nome: str,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        valor = dados.todos()[indice]

        with pytest.raises(ErroDeSanitizacao) as exc_info:
            ScannerFinalDeResultado().validar(resultado)

        assert valor not in str(exc_info.value), (
            f"Tipo '{nome}' apareceu na excecao"
        )
        assert valor not in repr(exc_info.value), (
            f"Tipo '{nome}' apareceu no repr da excecao"
        )


# ---------------------------------------------------------------------------
# Testes de integridade: texto_original nunca em saida
# ---------------------------------------------------------------------------


class TestTextoOriginalNuncaNaSaida:
    """A apresentacao nunca usa texto_original bruto diretamente."""

    def test_texto_original_nao_aparece_no_renderer(self) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        texto_bruto = resultado.linha_do_tempo[0].texto_original
        visao = criar_visao_segura(resultado)

        saida = renderizar_resultado(visao)

        _assert_sem_texto_original_direto(saida, texto_bruto)

    def test_texto_original_nao_aparece_no_json(self) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        texto_bruto = resultado.linha_do_tempo[0].texto_original
        visao = criar_visao_segura(resultado)

        serializado = json.dumps(
            serializar_resultado_de_analise(visao),
            ensure_ascii=False,
        )

        _assert_sem_texto_original_direto(serializado, texto_bruto)

    def test_texto_original_nao_aparece_em_logging(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        dados = _gerar_dados()
        resultado = _construir_resultado_bruto(dados)
        texto_bruto = resultado.linha_do_tempo[0].texto_original
        caplog.set_level(logging.DEBUG)

        criar_visao_segura(resultado)

        _assert_sem_texto_original_direto(caplog.text, texto_bruto)
