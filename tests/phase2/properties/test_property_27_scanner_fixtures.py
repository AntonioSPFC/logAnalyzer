"""Property 27: rejeição segura de dados brutos em fixtures candidatas."""

from __future__ import annotations

from hashlib import sha256
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.governanca import GovernancaDeFixtures
from tests.phase2.strategies.sensitive import (
    SensitiveDatum,
    SensitiveKind,
    sensitive_data,
)


_CAMPO_E_TIPO_POR_CLASSE = {
    SensitiveKind.CALL_ID: ("CallId", "CALL_ID"),
    SensitiveKind.UUID: ("uuid", "UUID"),
    SensitiveKind.PHONE: ("telefone", "TELEFONE"),
    SensitiveKind.DOCUMENT: ("documento", "DOCUMENTO"),
    SensitiveKind.IP: ("ip", "IP"),
    SensitiveKind.INTERNAL_HOST: ("host", "HOST_INTERNO"),
    SensitiveKind.INTERNAL_URL: ("url", "URL_INTERNA"),
    SensitiveKind.CREDENTIAL: ("token", "CREDENCIAL"),
    SensitiveKind.CUSTOMER_DATA: ("cliente", "DADO_CLIENTE"),
}
_DADOS_DE_TODAS_AS_CLASSES = st.tuples(
    *(sensitive_data((classe,)) for classe in SensitiveKind)
)
_COMPRIMENTO_FRAGMENTO = 8


# Feature: log-analyzer-phase-2, Property 27: Scanner de fixtures rejeita dados brutos sem eco
@given(dados_sensiveis=_DADOS_DE_TODAS_AS_CLASSES)
@settings(max_examples=100)
def test_property_27_scanner_de_fixtures_rejeita_dados_brutos_sem_eco(
    dados_sensiveis: tuple[SensitiveDatum, ...],
    tmp_path_factory,
) -> None:
    """Todo dado bruto é rejeitado com somente tipo e posição seguros.

    **Validates: Requirements 14.5, 14.6, 14.8**
    """

    raiz = tmp_path_factory.mktemp("property-27-scanner-fixtures")
    artefato = raiz / "candidate.log"
    linhas: list[str] = []
    diagnosticos_esperados: list[tuple[str, int, str]] = []

    for numero_linha, dado in enumerate(dados_sensiveis, start=1):
        campo, tipo = _CAMPO_E_TIPO_POR_CLASSE[dado.kind]
        linhas.append(f"{campo}={dado.synthetic_value}")
        diagnosticos_esperados.append((artefato.name, numero_linha, tipo))

    payload = ("\n".join(linhas) + "\n").encode("utf-8")
    artefato.write_bytes(payload)
    (raiz / "manifest.json").write_text(
        json.dumps(
            {
                "fixture_id": "synthetic_property_27",
                "origin": "synthetic",
                "sanitizer_version": "1.0",
                "label": "NAO_CLASSIFICADA",
                "validation_date": "2035-06-01",
                "approved_by": "<DOMAIN_OWNER_1>",
                "artifacts": [
                    {
                        "path": artefato.name,
                        "sha256": sha256(payload).hexdigest(),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    resultado = GovernancaDeFixtures(
        versoes_sanitizador={"1.0"}
    ).validar(raiz)

    assert resultado.rejeitada
    assert tuple(
        (diagnostico.arquivo, diagnostico.linha, diagnostico.tipo)
        for diagnostico in resultado.diagnosticos
    ) == tuple(diagnosticos_esperados)

    superficie_diagnostica = "\n".join(
        [repr(resultado)]
        + [str(diagnostico) for diagnostico in resultado.diagnosticos]
        + [repr(diagnostico) for diagnostico in resultado.diagnosticos]
    ).casefold()
    for dado in dados_sensiveis:
        valor = dado.synthetic_value.casefold()
        assert valor not in superficie_diagnostica
        fragmentos = {
            valor[inicio : inicio + _COMPRIMENTO_FRAGMENTO]
            for inicio in range(len(valor) - _COMPRIMENTO_FRAGMENTO + 1)
        }
        assert fragmentos
        assert all(
            fragmento not in superficie_diagnostica
            for fragmento in fragmentos
        )
