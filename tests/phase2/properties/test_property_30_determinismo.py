"""Property 30: determinismo observável de análises repetidas da Fase 2.

Cada exemplo cria apenas entradas, configuração e catálogo sintéticos em memória
ou em diretório temporário. Recursos internos efêmeros, como a chave HMAC do
índice, não pertencem ao contrato e não integram o snapshot comparado.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from hashlib import sha256
import json
import re

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.catalogo import CatalogoDeRegras, catalogo_de_json
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EstadoSanitizacao,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.serializacao import (
    serializar_modelo,
    serializar_resultado_de_analise,
)


_PLACEHOLDER_CANONICO = re.compile(r"<[A-Z][A-Z_]*_[1-9][0-9]*>")


def _catalogo_sintetico(sal: int, versao_regra: int) -> CatalogoDeRegras:
    token = f"{sal:016X}"
    rule_id = f"SYN_P30_RULE_{token}"
    condition_id = f"SYN_P30_APPLICATION_{token}"
    fixture_id = f"SYN_P30_FIXTURE_{token}"
    catalog_version = f"SYN_P30_CATALOG_{token}_V{versao_regra}"
    fixture_digest = sha256(
        f"property-30:{token}:{versao_regra}".encode("ascii")
    ).hexdigest()
    documento = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "coverage": {"labeled_successes": 1, "labeled_errors": 0},
        "rules": [
            {
                "rule_id": rule_id,
                "version": versao_regra,
                "category": "SUCESSO",
                "applications": ["VPL", "ORK"],
                "conditions": [
                    {
                        "condition_id": condition_id,
                        "operator": "APPLICATION_PRESENT",
                        "application": "VPL",
                    }
                ],
                "evidence_selectors": [condition_id],
                "fixture_ids": [fixture_id],
                "fixture_digests": [fixture_digest],
                "state": "ACTIVE",
                "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
                "approved_at": "2035-01-02T03:04:05+00:00",
                "approval_reference": f"SYN_P30_APPROVAL_{token}",
                "precedence": 0,
            }
        ],
        "precedence": [
            {
                "rule_id": rule_id,
                "version": versao_regra,
                "precedence": 0,
            }
        ],
    }
    carregado = catalogo_de_json(
        json.dumps(documento, separators=(",", ":"))
    )
    return replace(
        carregado,
        regras_autorizadas=((rule_id, versao_regra),),
    )


def _vpl_sintetico(
    call_id: str,
    call_id_secundario: str,
    segundo: int,
    microssegundo: int,
) -> str:
    return (
        "2035-06-07 08:09:"
        f"{segundo:02d}.{microssegundo:06d} 99.50% [NOTICE] "
        "mod_property_30.c:30 "
        f"canal sofia/external/{call_id}@sip.synthetic.invalid "
        f"CallId={call_id_secundario}\n"
        "continuação multiline sintética e estável Ω\n"
    )


def _ork_sintetico(
    call_id: str,
    call_id_secundario: str,
    segundo: int,
    microssegundo: int,
) -> str:
    return (
        "2035-06-07T11:09:"
        f"{segundo:02d}.{microssegundo:06d}+00:00 "
        "ork-node.synthetic.invalid ork-worker[3030]: "
        "INFO - property.30.synthetic - "
        f"TelecomCallId={call_id} CallId={call_id_secundario}\n"
    )


# Feature: log-analyzer-phase-2, Property 30: Análise repetida é determinística
@given(
    sal=st.integers(min_value=0, max_value=2**64 - 1),
    versao_regra=st.integers(min_value=1, max_value=10_000),
    segundo_vpl=st.integers(min_value=0, max_value=59),
    microssegundo_vpl=st.integers(min_value=0, max_value=999_999),
    segundo_ork=st.integers(min_value=0, max_value=59),
    microssegundo_ork=st.integers(min_value=0, max_value=999_999),
    ordem_invertida=st.booleans(),
    limiar_memoria=st.integers(min_value=128, max_value=512),
    tamanho_lote=st.integers(min_value=1, max_value=16),
)
@settings(max_examples=100)
def test_property_30_analise_repetida_e_deterministica(
    sal: int,
    versao_regra: int,
    segundo_vpl: int,
    microssegundo_vpl: int,
    segundo_ork: int,
    microssegundo_ork: int,
    ordem_invertida: bool,
    limiar_memoria: int,
    tamanho_lote: int,
    tmp_path_factory,
) -> None:
    """Execuções idênticas preservam toda a superfície contratual.

    **Validates: Requirements 16.5, 17.2**
    """

    token = f"{sal:016X}"
    call_id = f"SYN-P30-CALL-{token}-PRIMARY"
    call_id_secundario = f"SYN-P30-CALL-{token}-SECONDARY"
    raiz = tmp_path_factory.mktemp("property-30-determinismo")
    caminho_vpl = raiz / "vpl-sintetico.log"
    caminho_ork = raiz / "ork-sintetico.log"
    caminho_vpl.write_text(
        _vpl_sintetico(
            call_id,
            call_id_secundario,
            segundo_vpl,
            microssegundo_vpl,
        ),
        encoding="utf-8",
        newline="",
    )
    caminho_ork.write_text(
        _ork_sintetico(
            call_id,
            call_id_secundario,
            segundo_ork,
            microssegundo_ork,
        ),
        encoding="utf-8",
        newline="",
    )

    selecao_base = (
        ArquivoSelecionado(str(caminho_vpl), "VPL"),
        ArquivoSelecionado(str(caminho_ork), "ORK"),
    )
    selecao = tuple(reversed(selecao_base)) if ordem_invertida else selecao_base
    catalogo = _catalogo_sintetico(sal, versao_regra)
    pipeline = PipelineFase2(
        criar_registro_padrao(),
        catalogo=catalogo,
        fabrica_indice=partial(
            IndiceTemporario,
            limiar_memoria=limiar_memoria,
            tamanho_lote=tamanho_lote,
        ),
    )

    resultado_a = pipeline.executar(selecao, call_id)
    resultado_b = pipeline.executar(selecao, call_id)

    assert resultado_a.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado_a.categoria_de_cenario is Categoria.SUCESSO
    assert resultado_a.correlacao_encontrada
    assert resultado_a.correlacao is not None
    assert resultado_a.correlacao.base_primaria is (
        BaseCorrelacao.VALOR_COMPARTILHADO
    )
    assert resultado_a.regra_aplicada is not None
    assert resultado_a.evidencias
    assert resultado_a.versao_catalogo == (
        f"SYN_P30_CATALOG_{token}_V{versao_regra}"
    )

    assert resultado_a.categoria_de_cenario == resultado_b.categoria_de_cenario
    assert tuple(
        (
            entrada.timestamp_normalizado,
            entrada.aplicacao,
            entrada.ordem_de_leitura,
            entrada.entrada_id,
        )
        for entrada in resultado_a.linha_do_tempo
    ) == tuple(
        (
            entrada.timestamp_normalizado,
            entrada.aplicacao,
            entrada.ordem_de_leitura,
            entrada.entrada_id,
        )
        for entrada in resultado_b.linha_do_tempo
    )
    assert serializar_modelo(resultado_a.correlacao) == serializar_modelo(
        resultado_b.correlacao
    )
    assert serializar_modelo(resultado_a.regra_aplicada) == serializar_modelo(
        resultado_b.regra_aplicada
    )
    assert serializar_modelo(resultado_a.evidencias) == serializar_modelo(
        resultado_b.evidencias
    )
    assert resultado_a.versao_catalogo == resultado_b.versao_catalogo

    contrato_a = serializar_resultado_de_analise(resultado_a)
    contrato_b = serializar_resultado_de_analise(resultado_b)
    superficie_a = json.dumps(
        contrato_a,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    superficie_b = json.dumps(
        contrato_b,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    placeholders_a = tuple(_PLACEHOLDER_CANONICO.findall(superficie_a))
    placeholders_b = tuple(_PLACEHOLDER_CANONICO.findall(superficie_b))

    assert resultado_a.identificador == "<CALL_ID_1>"
    assert "<CALL_ID_1>" in placeholders_a
    assert "<CALL_ID_2>" in placeholders_a
    assert placeholders_a == placeholders_b
    assert call_id not in superficie_a
    assert call_id_secundario not in superficie_a
    assert contrato_a == contrato_b

    event(
        "ordem_selecao=" + ("ORK_VPL" if ordem_invertida else "VPL_ORK")
    )
    event(
        "timestamps="
        + (
            "empate"
            if (segundo_vpl, microssegundo_vpl)
            == (segundo_ork, microssegundo_ork)
            else "distintos"
        )
    )
    event("categoria=SUCESSO")
    event("correlacao=VALOR_COMPARTILHADO")
