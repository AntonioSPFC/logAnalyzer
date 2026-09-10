"""Testes unitários e de segurança da sanitização e da governança.

Todos os valores sensíveis são sintetizados em memória durante cada teste. Os
únicos artefatos persistentes lidos são a fixture estrutural governada da Fase
2; candidatos adicionais vivem exclusivamente em ``tmp_path``.

Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from log_analyzer.core.excecoes import ErroDeSanitizacao
from log_analyzer.core.governanca import (
    GovernancaDeFixtures,
    ScannerDeFixtures,
)
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
from log_analyzer.core.sanitizacao import (
    CampoSensivel,
    SanitizationContext,
    TipoDadoSensivel,
    detectar_dados_sensiveis,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.visao_segura import (
    MENSAGEM_FALHA_VISAO_SEGURA,
    SanitizadorDeResultado,
    ScannerFinalDeResultado,
)


_INSTANTE_UTC = datetime(2035, 6, 1, 12, 30, 0, 123456, tzinfo=timezone.utc)
_TIMESTAMP_ORIGINAL = "2035-06-01T12:30:00.123456+00:00"
_FIXTURE_GOVERNADA = (
    Path(__file__).parents[1]
    / "fixtures"
    / "log_analyzer_phase2"
    / "golden_candidate"
)


@dataclass(frozen=True, slots=True)
class _DadosSensiveisSinteticos:
    """Conjunto efêmero cujo próprio ``repr`` nunca contém os valores."""

    call_id: str = field(repr=False)
    uuid: str = field(repr=False)
    uuid_canal: str = field(repr=False)
    uuid_sessao: str = field(repr=False)
    telefone: str = field(repr=False)
    documento: str = field(repr=False)
    ip: str = field(repr=False)
    host: str = field(repr=False)
    url: str = field(repr=False)
    credencial: str = field(repr=False)
    dado_cliente: str = field(repr=False)

    def valores(self) -> tuple[str, ...]:
        return (
            self.call_id,
            self.uuid,
            self.uuid_canal,
            self.uuid_sessao,
            self.telefone,
            self.documento,
            self.ip,
            self.host,
            self.url,
            self.credencial,
            self.dado_cliente,
        )


def _gerar_dados_sensiveis() -> _DadosSensiveisSinteticos:
    token = uuid4().hex
    digitos = str(uuid4().int).zfill(40)
    octetos = tuple((int(token[indice : indice + 2], 16) % 200) + 1 for indice in (0, 2, 4))
    host = f"node-{token[:10]}.internal"
    return _DadosSensiveisSinteticos(
        call_id=f"SYN_CALL_{token[:20]}",
        uuid=str(uuid4()),
        uuid_canal=str(uuid4()),
        uuid_sessao=str(uuid4()),
        telefone=f"+55 21 9{digitos[:4]}-{digitos[4:8]}",
        documento=f"{digitos[8:11]}.{digitos[11:14]}.{digitos[14:17]}-{digitos[17:19]}",
        ip=f"10.{octetos[0]}.{octetos[1]}.{octetos[2]}",
        host=host,
        url=f"https://{host}/synthetic/{token[10:22]}",
        credencial=f"cred_{token}{uuid4().hex[:12]}",
        dado_cliente=f"synthetic-{token[:12]}@tenant-{token[12:24]}.test",
    )


def _linhas_sensiveis(
    dados: _DadosSensiveisSinteticos,
) -> dict[str, tuple[str, TipoDadoSensivel, str]]:
    return {
        "call-id": (
            f"CallId={dados.call_id}",
            TipoDadoSensivel.CALL_ID,
            "CALL_ID",
        ),
        "uuid": (
            f"session_uuid={dados.uuid}",
            TipoDadoSensivel.UUID,
            "UUID",
        ),
        "telefone": (
            f"telefone={dados.telefone}",
            TipoDadoSensivel.TELEFONE,
            "TELEFONE",
        ),
        "documento": (
            f"documento={dados.documento}",
            TipoDadoSensivel.DOCUMENTO,
            "DOCUMENTO",
        ),
        "ip": (f"ip={dados.ip}", TipoDadoSensivel.IP, "IP"),
        "host": (
            f"host={dados.host}",
            TipoDadoSensivel.HOST_INTERNO,
            "HOST_INTERNO",
        ),
        "url": (
            f"url={dados.url}",
            TipoDadoSensivel.URL_INTERNA,
            "URL_INTERNA",
        ),
        "credencial": (
            f"token={dados.credencial}",
            TipoDadoSensivel.CREDENCIAL,
            "CREDENCIAL",
        ),
        "cliente": (
            f"email={dados.dado_cliente}",
            TipoDadoSensivel.DADO_CLIENTE,
            "DADO_CLIENTE",
        ),
    }


def _assert_ausentes(
    valores: tuple[str, ...],
    *superficies: str,
) -> None:
    agregado = "\n".join(superficies)
    for valor in valores:
        assert valor not in agregado


def _proveniencia(nome_campo: str) -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-sintetica-segura-1",
        linha_inicial=1,
        linha_final=12,
        nome_campo=nome_campo,
        regra_extracao="extrator-sintetico-v1",
    )


def _resultado_bruto(
    dados: _DadosSensiveisSinteticos,
) -> tuple[ResultadoDeAnalise, str]:
    descritores = (
        ("CallId", dados.call_id),
        ("uuid", dados.uuid),
        ("channel_uuid", dados.uuid_canal),
        ("session_uuid", dados.uuid_sessao),
        ("telefone", dados.telefone),
        ("documento", dados.documento),
        ("ip", dados.ip),
        ("host", dados.host),
        ("url", dados.url),
        ("token", dados.credencial),
        ("email", dados.dado_cliente),
    )
    campos = tuple(
        CampoEstruturado(nome, valor, _proveniencia(nome))
        for nome, valor in descritores
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
            tipo=TipoIdentificador.UUID_CANAL,
            namespace_comparacao="canal",
            nome_campo="channel_uuid",
            valor_original=dados.uuid_canal,
            valor_normalizado=dados.uuid_canal,
            proveniencia=_proveniencia("channel_uuid"),
        ),
        IdentificadorTecnico(
            tipo=TipoIdentificador.UUID_SESSAO,
            namespace_comparacao="sessao",
            nome_campo="session_uuid",
            valor_original=dados.uuid_sessao,
            valor_normalizado=dados.uuid_sessao,
            proveniencia=_proveniencia("session_uuid"),
        ),
    )
    texto = "\n".join(
        [linha for linha, _, _ in _linhas_sensiveis(dados).values()]
        + [
            f"channel_uuid={dados.uuid_canal}",
            f"explicit_session_uuid={dados.uuid_sessao}",
        ]
    )
    origem = f"C:/synthetic-input/{dados.call_id}.txt"
    entrada = EntradaDeLog(
        texto_original=texto,
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=_INSTANTE_UTC,
        nivel_de_severidade="INFO",
        mensagem=texto,
        categoria=Categoria.NAO_CLASSIFICADA,
        entrada_id="entrada-sintetica-segura-1",
        arquivo_origem=origem,
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=12,
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE_UTC,
        precisao_fracionaria=6,
        origem_evento="modulo.sintetico",
        formato_origem="perfil-sintetico",
        campos_estruturados=campos,
        identificadores=identificadores,
    )
    evidencia = Evidencia(
        tipo="campo_estruturado",
        aplicacao="VPL",
        proveniencia=_proveniencia("CallId"),
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE_UTC,
        campo_ou_condicao="CallId presente",
        representacao_sanitizada=f"CallId={dados.call_id}",
    )
    resultado = ResultadoDeAnalise(
        identificador=dados.call_id,
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
        contagem_por_aplicacao={"VPL": 1},
        erros=[
            MensagemDeErro(
                arquivo_ou_app=origem,
                descricao=f"falha sintética token={dados.credencial}",
            )
        ],
        mensagens=[f"resumo email={dados.dado_cliente}"],
        identificadores_extraidos=list(identificadores),
        evidencias=[evidencia],
        aplicacoes_analisadas=["VPL"],
    )
    return resultado, origem


def _texto_fixture_com_placeholders() -> str:
    return "\n".join(
        (
            "CallId=<CALL_ID_1>",
            "uuid=<UUID_1>",
            "channel_uuid=<UUID_CANAL_1>",
            "session_uuid=<UUID_SESSAO_1>",
            "telefone=<TELEFONE_1>",
            "documento=<DOCUMENTO_1>",
            "ip=<IP_1>",
            "host=<HOST_INTERNO_1>",
            "url=<URL_INTERNA_1>",
            "token=<CREDENCIAL_1>",
            "email=<DADO_CLIENTE_1>",
            "",
        )
    )


def _gravar_fixture_temporaria(
    raiz: Path,
    texto: str,
    *,
    digest_declarado: str | None = None,
) -> tuple[Path, Path]:
    raiz.mkdir(parents=True)
    artefato = raiz / "candidate.log"
    payload = texto.encode("utf-8")
    artefato.write_bytes(payload)
    manifesto = raiz / "manifest.json"
    manifesto.write_text(
        json.dumps(
            {
                "fixture_id": "synthetic_fixture_v1",
                "origin": "synthetic",
                "sanitizer_version": "1.0",
                "label": "NAO_CLASSIFICADA",
                "validation_date": "2035-06-01",
                "approved_by": "<DOMAIN_OWNER_1>",
                "artifacts": [
                    {
                        "path": artefato.name,
                        "sha256": digest_declarado or sha256(payload).hexdigest(),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifesto, artefato


class _FalhaInjetada(RuntimeError):
    pass


class _ContextoComFalhaEstruturada(SanitizationContext):
    __slots__ = ("_segredo",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo = segredo

    def placeholder_para(
        self,
        tipo: TipoDadoSensivel | TipoIdentificador | str,
        valor: str,
        *,
        valor_normalizado: str | None = None,
    ) -> str:
        raise _FalhaInjetada(self._segredo)


class _ContextoComFalhaTextual(SanitizationContext):
    __slots__ = ("_segredo",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo = segredo

    def sanitizar_texto(self, texto: str) -> str:
        raise _FalhaInjetada(self._segredo)


class _ContextoComFalhaNoDescarte(SanitizationContext):
    __slots__ = ("_segredo",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo = segredo

    def descartar_mapa_bruto(self) -> None:
        super().descartar_mapa_bruto()
        raise _FalhaInjetada(self._segredo)


class _ScannerFinalQueFalha:
    def __init__(self, segredo: str) -> None:
        self._segredo = segredo

    def validar(self, resultado: ResultadoDeAnalise) -> None:
        raise _FalhaInjetada(self._segredo)


class _ScannerTextualComAchado:
    def inspecionar_texto(
        self,
        texto: str,
        *,
        arquivo: str = "<ARQUIVO>",
        linha_inicial: int = 1,
    ) -> tuple[object, ...]:
        return (object(),)


class _ScannerFixturesQueFalha(ScannerDeFixtures):
    def __init__(self, segredo: str) -> None:
        self._segredo = segredo

    def inspecionar_texto(
        self,
        texto: str,
        *,
        arquivo: str = "<ARQUIVO>",
        linha_inicial: int = 1,
    ) -> tuple[object, ...]:
        raise _FalhaInjetada(self._segredo)


class _ColecaoQueFalha(list[str]):
    def __init__(self, segredo: str) -> None:
        super().__init__(["item sintético"])
        self._segredo = segredo

    def __iter__(self):
        raise _FalhaInjetada(self._segredo)

    def __repr__(self) -> str:
        return "<colecao-com-falha-injetada>"


def test_repeticao_consistente_e_namespaces_tipados_independentes() -> None:
    dados = _gerar_dados_sensiveis()
    contexto = SanitizationContext()

    primeiro = contexto.placeholder_para(TipoDadoSensivel.CALL_ID, dados.call_id)
    repetido = contexto.placeholder_para(
        TipoDadoSensivel.CALL_ID,
        dados.call_id.swapcase(),
    )
    uuid_generico = contexto.placeholder_para(TipoDadoSensivel.UUID, dados.uuid)
    uuid_canal = contexto.placeholder_para(TipoDadoSensivel.UUID_CANAL, dados.uuid)
    uuid_sessao = contexto.placeholder_para(TipoDadoSensivel.UUID_SESSAO, dados.uuid)
    cliente = contexto.placeholder_para(
        TipoDadoSensivel.DADO_CLIENTE,
        dados.call_id,
    )

    assert primeiro == repetido == "<CALL_ID_1>"
    assert uuid_generico == "<UUID_1>"
    assert uuid_canal == "<UUID_CANAL_1>"
    assert uuid_sessao == "<UUID_SESSAO_1>"
    assert cliente == "<DADO_CLIENTE_1>"
    assert len({primeiro, uuid_generico, uuid_canal, uuid_sessao, cliente}) == 5
    _assert_ausentes(
        dados.valores(),
        repr(contexto),
        repr(CampoSensivel("CallId", dados.call_id, TipoDadoSensivel.CALL_ID)),
        repr(dados),
    )


@pytest.mark.parametrize(
    "chave",
    (
        "call-id",
        "uuid",
        "telefone",
        "documento",
        "ip",
        "host",
        "url",
        "credencial",
        "cliente",
    ),
)
def test_detectores_defensivos_informam_somente_tipo_e_intervalo(chave: str) -> None:
    dados = _gerar_dados_sensiveis()
    linha, tipo_esperado, _ = _linhas_sensiveis(dados)[chave]

    deteccoes = detectar_dados_sensiveis(linha)

    assert tipo_esperado in {deteccao.tipo for deteccao in deteccoes}
    _assert_ausentes(dados.valores(), repr(deteccoes))


def test_longest_match_substitui_o_valor_mais_longo_sem_sufixo_bruto() -> None:
    token = uuid4().hex
    curto = f"SYN_CALL_{token[:12]}"
    longo = f"{curto}-credential-{token[12:24]}"
    contexto = SanitizationContext()
    contexto.placeholder_para(TipoDadoSensivel.CALL_ID, curto)
    contexto.placeholder_para(TipoDadoSensivel.CREDENCIAL, longo)

    sanitizado = contexto.sanitizar_texto(f"credential={longo}")

    assert sanitizado == "credential=<CREDENCIAL_1>"
    _assert_ausentes((curto, longo), sanitizado, repr(contexto))


def test_sobreposicao_inconclusiva_falha_fechada_e_descarta_o_mapa() -> None:
    token = uuid4().hex
    esquerdo = f"left-{token[:10]}-shared"
    direito = f"shared-right-{token[10:20]}"
    texto = f"left-{token[:10]}-shared-right-{token[10:20]}"
    contexto = SanitizationContext()
    contexto.placeholder_para(TipoDadoSensivel.CALL_ID, esquerdo)
    contexto.placeholder_para(TipoDadoSensivel.CREDENCIAL, direito)

    with pytest.raises(ErroDeSanitizacao) as exc_info:
        contexto.sanitizar_texto(texto)

    assert str(exc_info.value) == MENSAGEM_FALHA_VISAO_SEGURA
    assert contexto.falhou
    assert len(contexto) == 0
    _assert_ausentes(
        (esquerdo, direito, texto),
        str(exc_info.value),
        repr(exc_info.value),
        repr(contexto),
    )


def test_campos_estruturados_antecedem_texto_e_preservam_ordem() -> None:
    dados = _gerar_dados_sensiveis()
    campos = (
        CampoSensivel(
            "session_uuid",
            dados.uuid_sessao,
            TipoDadoSensivel.UUID_SESSAO,
        ),
        CampoSensivel("CallId", dados.call_id, TipoDadoSensivel.CALL_ID),
    )
    texto = f"session_uuid={dados.uuid_sessao} CallId={dados.call_id}"

    with SanitizationContext() as contexto:
        campos_seguros, texto_seguro = contexto.sanitizar_campos_e_texto(
            campos,
            texto,
        )

    assert tuple(campo.nome for campo in campos_seguros) == (
        "session_uuid",
        "CallId",
    )
    assert tuple(campo.valor for campo in campos_seguros) == (
        "<UUID_SESSAO_1>",
        "<CALL_ID_1>",
    )
    assert texto_seguro == (
        "session_uuid=<UUID_SESSAO_1> CallId=<CALL_ID_1>"
    )
    _assert_ausentes(dados.valores(), texto_seguro, repr(campos_seguros))

    fora_de_ordem = SanitizationContext()
    fora_de_ordem.sanitizar_texto("texto sintético neutro")
    with pytest.raises(ErroDeSanitizacao) as exc_info:
        fora_de_ordem.sanitizar_valor_estruturado(
            "CallId",
            dados.call_id,
            TipoDadoSensivel.CALL_ID,
        )
    assert fora_de_ordem.falhou
    assert len(fora_de_ordem) == 0
    _assert_ausentes(
        dados.valores(),
        str(exc_info.value),
        repr(exc_info.value),
        repr(fora_de_ordem),
    )


def test_descarte_e_repr_nao_expoem_estado_bruto(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dados = _gerar_dados_sensiveis()
    caplog.set_level(logging.DEBUG)
    contexto = SanitizationContext()
    contexto.placeholder_para(TipoDadoSensivel.CALL_ID, dados.call_id)
    representacao_ativa = repr(contexto)

    contexto.descartar_mapa_bruto()
    contexto.descartar_mapa_bruto()

    assert contexto.descartado
    assert not contexto.ativo
    assert len(contexto) == 0
    with pytest.raises(ErroDeSanitizacao) as exc_info:
        contexto.sanitizar_texto(dados.call_id)

    capturado = capsys.readouterr()
    _assert_ausentes(
        dados.valores(),
        representacao_ativa,
        repr(contexto),
        str(exc_info.value),
        repr(exc_info.value),
        capturado.out,
        capturado.err,
        caplog.text,
    )


def test_visao_segura_sanitiza_todos_os_tipos_sem_alterar_o_interno() -> None:
    dados = _gerar_dados_sensiveis()
    interno, origem = _resultado_bruto(dados)
    entrada_interna = interno.linha_do_tempo[0]
    snapshot = serializar_resultado_de_analise(interno)

    segura = SanitizadorDeResultado().criar_visao_segura(interno)

    serializada = json.dumps(
        serializar_resultado_de_analise(segura),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert segura is not interno
    assert segura.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert segura.identificador == "<CALL_ID_1>"
    assert segura.linha_do_tempo[0].arquivo_origem is None
    assert segura.linha_do_tempo[0].arquivo_token == "<ARQUIVO_1>"
    assert tuple(
        campo.nome for campo in segura.linha_do_tempo[0].campos_estruturados
    ) == tuple(campo.nome for campo in entrada_interna.campos_estruturados)
    for prefixo in (
        "CALL_ID",
        "UUID",
        "UUID_CANAL",
        "UUID_SESSAO",
        "TELEFONE",
        "DOCUMENTO",
        "IP",
        "HOST_INTERNO",
        "URL_INTERNA",
        "CREDENCIAL",
        "DADO_CLIENTE",
    ):
        assert f"<{prefixo}_" in serializada

    assert serializar_resultado_de_analise(interno) == snapshot
    assert interno.linha_do_tempo[0] is entrada_interna
    assert entrada_interna.arquivo_origem == origem
    _assert_ausentes(
        (*dados.valores(), origem),
        serializada,
        repr(segura),
    )


def test_scanner_final_independente_rejeita_resultado_bruto_sem_eco(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dados = _gerar_dados_sensiveis()
    resultado, origem = _resultado_bruto(dados)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ErroDeSanitizacao) as exc_info:
        ScannerFinalDeResultado().validar(resultado)

    capturado = capsys.readouterr()
    assert str(exc_info.value) == MENSAGEM_FALHA_VISAO_SEGURA
    _assert_ausentes(
        (*dados.valores(), origem),
        str(exc_info.value),
        repr(exc_info.value),
        capturado.out,
        capturado.err,
        caplog.text,
    )


def test_scanner_final_trata_achado_injetado_como_falha_total() -> None:
    resultado = ResultadoDeAnalise("<CALL_ID_1>")
    scanner = ScannerFinalDeResultado(scanner=_ScannerTextualComAchado())

    with pytest.raises(ErroDeSanitizacao) as exc_info:
        scanner.validar(resultado)

    assert str(exc_info.value) == MENSAGEM_FALHA_VISAO_SEGURA


@pytest.mark.parametrize(
    "fronteira",
    (
        "snapshot",
        "fabrica-contexto",
        "estrutura",
        "texto",
        "scanner-final",
        "descarte",
    ),
)
def test_falha_injetada_em_cada_fronteira_suprime_toda_visao(
    fronteira: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dados = _gerar_dados_sensiveis()
    resultado, origem = _resultado_bruto(dados)
    entrada_interna = resultado.linha_do_tempo[0]
    segredo_da_falha = f"failure-secret-{uuid4().hex}"
    caplog.set_level(logging.DEBUG)

    fabrica = SanitizationContext
    scanner_final = None
    if fronteira == "snapshot":
        resultado.mensagens = _ColecaoQueFalha(segredo_da_falha)  # type: ignore[assignment]
    elif fronteira == "fabrica-contexto":
        def fabrica():
            raise _FalhaInjetada(segredo_da_falha)
    elif fronteira == "estrutura":
        fabrica = lambda: _ContextoComFalhaEstruturada(segredo_da_falha)
    elif fronteira == "texto":
        fabrica = lambda: _ContextoComFalhaTextual(segredo_da_falha)
    elif fronteira == "scanner-final":
        scanner_final = _ScannerFinalQueFalha(segredo_da_falha)
    elif fronteira == "descarte":
        fabrica = lambda: _ContextoComFalhaNoDescarte(segredo_da_falha)

    sanitizador = SanitizadorDeResultado(
        fabrica_contexto=fabrica,
        scanner_final=scanner_final,
    )
    with pytest.raises(ErroDeSanitizacao) as exc_info:
        sanitizador.criar_visao_segura(resultado)

    capturado = capsys.readouterr()
    assert str(exc_info.value) == MENSAGEM_FALHA_VISAO_SEGURA
    assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert resultado.linha_do_tempo[0] is entrada_interna
    assert entrada_interna.texto_original.startswith("CallId=")
    _assert_ausentes(
        (*dados.valores(), origem, segredo_da_falha),
        str(exc_info.value),
        repr(exc_info.value),
        repr(sanitizador),
        capturado.out,
        capturado.err,
        caplog.text,
    )


def test_fixture_estrutural_versionada_passa_pela_governanca() -> None:
    resultado = GovernancaDeFixtures(
        versoes_sanitizador={"1.0"}
    ).validar(_FIXTURE_GOVERNADA)

    assert resultado.aprovada
    assert resultado.diagnosticos == ()


def test_fixture_temporaria_aprovada_contem_apenas_placeholders(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dados = _gerar_dados_sensiveis()
    caplog.set_level(logging.DEBUG)
    manifesto, artefato = _gravar_fixture_temporaria(
        tmp_path / "fixture-sintetica-aprovada",
        _texto_fixture_com_placeholders(),
    )

    resultado = GovernancaDeFixtures(
        versoes_sanitizador={"1.0"}
    ).validar(artefato.parent)

    assert resultado.aprovada
    assert resultado.diagnosticos == ()
    conteudo_aceito = manifesto.read_text(encoding="utf-8") + artefato.read_text(
        encoding="utf-8"
    )
    assert ScannerDeFixtures().inspecionar_texto(
        conteudo_aceito,
        arquivo="fixture.txt",
    ) == ()
    capturado = capsys.readouterr()
    _assert_ausentes(
        dados.valores(),
        conteudo_aceito,
        repr(resultado),
        capturado.out,
        capturado.err,
        caplog.text,
    )


@pytest.mark.parametrize(
    ("chave", "tipo_esperado"),
    (
        ("call-id", "CALL_ID"),
        ("uuid", "UUID"),
        ("telefone", "TELEFONE"),
        ("documento", "DOCUMENTO"),
        ("ip", "IP"),
        ("host", "HOST_INTERNO"),
        ("url", "URL_INTERNA"),
        ("credencial", "CREDENCIAL"),
        ("cliente", "DADO_CLIENTE"),
    ),
)
def test_governanca_rejeita_cada_classe_sensivel_sem_eco(
    chave: str,
    tipo_esperado: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dados = _gerar_dados_sensiveis()
    linha, _, _ = _linhas_sensiveis(dados)[chave]
    caplog.set_level(logging.DEBUG)
    _, artefato = _gravar_fixture_temporaria(
        tmp_path / f"fixture-rejeitada-{chave}",
        linha + "\n",
    )

    resultado = GovernancaDeFixtures().validar(artefato.parent)

    assert resultado.rejeitada
    assert tipo_esperado in {
        diagnostico.tipo for diagnostico in resultado.diagnosticos
    }
    superficie_diagnostica = "\n".join(
        [repr(resultado)]
        + [str(item) for item in resultado.diagnosticos]
        + [repr(item) for item in resultado.diagnosticos]
    )
    capturado = capsys.readouterr()
    _assert_ausentes(
        dados.valores(),
        superficie_diagnostica,
        capturado.out,
        capturado.err,
        caplog.text,
    )


def test_governanca_converte_falha_do_scanner_em_diagnostico_sem_eco(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    segredo_da_falha = f"scanner-secret-{uuid4().hex}"
    caplog.set_level(logging.DEBUG)
    _, artefato = _gravar_fixture_temporaria(
        tmp_path / "fixture-scanner-falho",
        _texto_fixture_com_placeholders(),
    )
    governanca = GovernancaDeFixtures(
        scanner=_ScannerFixturesQueFalha(segredo_da_falha)
    )

    resultado = governanca.validar(artefato.parent)

    assert resultado.rejeitada
    assert {item.tipo for item in resultado.diagnosticos} == {"SCANNER_FALHOU"}
    capturado = capsys.readouterr()
    _assert_ausentes(
        (segredo_da_falha,),
        repr(resultado),
        *(str(item) for item in resultado.diagnosticos),
        capturado.out,
        capturado.err,
        caplog.text,
    )


def test_governanca_rejeita_digest_divergente_e_utf8_invalido_sem_conteudo(
    tmp_path: Path,
) -> None:
    raiz_digest = tmp_path / "fixture-digest-divergente"
    _, artefato_digest = _gravar_fixture_temporaria(
        raiz_digest,
        _texto_fixture_com_placeholders(),
        digest_declarado="0" * 64,
    )
    resultado_digest = GovernancaDeFixtures().validar(artefato_digest.parent)
    assert resultado_digest.rejeitada
    assert "DIGEST_DIVERGENTE" in {
        item.tipo for item in resultado_digest.diagnosticos
    }

    segredo = f"decode-secret-{uuid4().hex}"
    raiz_utf8 = tmp_path / "fixture-utf8-invalida"
    manifesto, artefato_utf8 = _gravar_fixture_temporaria(
        raiz_utf8,
        _texto_fixture_com_placeholders(),
    )
    payload_invalido = b"\xff" + segredo.encode("ascii")
    artefato_utf8.write_bytes(payload_invalido)
    documento = json.loads(manifesto.read_text(encoding="utf-8"))
    documento["artifacts"][0]["sha256"] = sha256(payload_invalido).hexdigest()
    manifesto.write_text(
        json.dumps(documento, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    resultado_utf8 = GovernancaDeFixtures().validar(raiz_utf8)

    assert resultado_utf8.rejeitada
    assert "ARTEFATO_UTF8_INVALIDO" in {
        item.tipo for item in resultado_utf8.diagnosticos
    }
    _assert_ausentes(
        (segredo,),
        repr(resultado_utf8),
        *(str(item) for item in resultado_utf8.diagnosticos),
    )


@pytest.mark.parametrize(
    "marcador_neutro",
    ("", "[REDACTED]", "redacted", "null", "none", "N/A", "-", "undefined"),
)
def test_texto_com_rotulo_sensivel_neutro_nao_derruba_a_sanitizacao(
    marcador_neutro: str,
) -> None:
    """Rótulos sensíveis com valor vazio/neutro/redigido não são conteúdo.

    Um dicionário inline como ``'callid': '[REDACTED]'`` ou ``ani: null`` não
    tem dado sensível real a substituir. A sanitização deve concluir sem erro
    e sem alterar o marcador neutro. Validates: Requirements 14.1, 14.2.
    """

    if marcador_neutro:
        texto = f"evento processado 'callid': '{marcador_neutro}', 'ani': ''"
    else:
        texto = "evento processado 'callid': '', 'ani': ''"

    with SanitizationContext() as contexto:
        sanitizado = contexto.sanitizar_texto(texto)

    assert sanitizado == texto


def test_rotulo_neutro_ao_lado_de_valor_sensivel_real_ainda_substitui() -> None:
    """Um valor neutro descartado não pode mascarar um sensível REAL vizinho.

    Preserva o invariante fail-closed: o call-id vazio é ignorado, mas o
    documento real ao lado continua substituído por placeholder tipado.
    Validates: Requirements 14.1, 14.2, 14.3.
    """

    dados = _gerar_dados_sensiveis()
    texto = (
        f"'callid': '[REDACTED]', 'cpf': '', "
        f"documento={dados.documento}"
    )

    with SanitizationContext() as contexto:
        sanitizado = contexto.sanitizar_texto(texto)

    assert "<DOCUMENTO_1>" in sanitizado
    assert "'callid': '[REDACTED]'" in sanitizado
    assert "'cpf': ''" in sanitizado
    _assert_ausentes((dados.documento,), sanitizado, repr(contexto))
