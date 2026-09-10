"""Testes slow de lote, spill SQLite e seletividade do segundo passe.

Cenários cobertos:
- 100 arquivos sintéticos válidos no lote (limite aceito).
- Rejeição do 101º com código BATCH_LIMIT_EXCEEDED.
- Spill SQLite forçado com limiar_memoria=0.
- ~1000 identificadores únicos indexados.
- Match raro e frequente com busca estruturada.
- Segundo passe materializa somente os intervalos selecionados.

Todos os arquivos e valores são gerados em tempo de teste, nunca versionados.
Nenhuma fonte bruta local é usada.

Validates: Requirements 7.4, 15.6, 15.8.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from log_analyzer.core.excecoes import ErroDeArquivo
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.materializacao import (
    EntradaMaterializada,
    FonteMaterializacao,
    MaterializadorSeletivo,
    ResultadoMaterializacao,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaIndexada,
    Proveniencia,
    ReferenciaTextoOriginal,
)
from log_analyzer.core.streaming import (
    FingerprintArquivo,
    LeitorStreaming,
    validar_lote,
)

pytestmark = pytest.mark.slow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criar_arquivo_sintetico(diretorio: Path, numero: int) -> Path:
    """Cria um arquivo VPL sintético mínimo com linhas distintas."""
    conteudo = (
        f"2035-06-01 10:00:{numero % 60:02d}.{numero:06d} 99.00% "
        f"[INFO] modulo_{numero}.c:1 "
        f"CallId=SYNTH-LOTE-{numero:04d} evento lote {numero}\n"
    )
    caminho = diretorio / f"lote_{numero:04d}.log"
    caminho.write_text(conteudo, encoding="utf-8", newline="")
    return caminho


def _fingerprint_de(caminho: Path) -> FingerprintArquivo:
    """Calcula fingerprint de um arquivo existente."""
    st = os.stat(caminho)
    conteudo = caminho.read_bytes()
    sha = hashlib.sha256(conteudo).hexdigest()
    return FingerprintArquivo(
        dispositivo=st.st_dev,
        inode=st.st_ino,
        tamanho_bytes=st.st_size,
        mtime_ns=st.st_mtime_ns,
        sha256=sha,
    )


def _entrada_indexada_de_arquivo(
    caminho: Path,
    arquivo_token: str,
    entrada_id: str,
    ordem: int,
) -> EntradaIndexada:
    """Cria uma EntradaIndexada que referencia o conteúdo completo do arquivo."""
    conteudo = caminho.read_bytes()
    sha = hashlib.sha256(conteudo).hexdigest()
    proveniencia = Proveniencia(
        arquivo_token=arquivo_token,
        entrada_id=entrada_id,
        linha_inicial=1,
        linha_final=1,
    )
    return EntradaIndexada(
        entrada_id=entrada_id,
        aplicacao="VPL",
        ordem_de_leitura=ordem,
        texto_ref=ReferenciaTextoOriginal(
            arquivo_token=arquivo_token,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
            sha256=sha,
        ),
        cabecalho=(
            CampoEstruturado(
                nome="severidade",
                valor_original="INFO",
                proveniencia=proveniencia,
            ),
        ),
        identificadores_digest=("digest_placeholder",),
        timestamp_original="2035-06-01T10:00:00",
        timestamp_normalizado=datetime(2035, 6, 1, 13, 0, 0, tzinfo=timezone.utc),
        falhas=(),
        interpretada=True,
    )


# ---------------------------------------------------------------------------
# Teste: 100 arquivos no lote
# ---------------------------------------------------------------------------


class TestLote100Arquivos:
    """Valida que o lote aceita exatamente 100 arquivos e rejeita o 101º."""

    def test_lote_100_aceito(self, tmp_path: Path) -> None:
        """100 arquivos produzem 100 leitores e nenhuma falha de lote."""
        caminhos = [
            _criar_arquivo_sintetico(tmp_path, i) for i in range(1, 101)
        ]
        resultado = validar_lote(caminhos)

        assert len(resultado.leitores) == 100
        assert all(
            isinstance(leitor, LeitorStreaming)
            for leitor in resultado.leitores
        )
        # Nenhuma falha de limite
        falhas_lote = [
            f
            for f in resultado.falhas
            if f.contexto.get("codigo") == "BATCH_LIMIT_EXCEEDED"
        ]
        assert falhas_lote == []

    def test_lote_101_rejeita_excedente(self, tmp_path: Path) -> None:
        """O 101º arquivo é rejeitado com BATCH_LIMIT_EXCEEDED."""
        caminhos = [
            _criar_arquivo_sintetico(tmp_path, i) for i in range(1, 102)
        ]
        resultado = validar_lote(caminhos)

        assert len(resultado.leitores) == 100
        falhas_lote = [
            f
            for f in resultado.falhas
            if f.contexto.get("codigo") == "BATCH_LIMIT_EXCEEDED"
        ]
        assert len(falhas_lote) == 1
        assert falhas_lote[0].contexto["arquivo_token"] == "<ARQUIVO_101>"


# ---------------------------------------------------------------------------
# Teste: Spill SQLite com limiar_memoria=0
# ---------------------------------------------------------------------------


class TestSpillSQLite:
    """Força spill imediato e valida que o índice opera sobre disco."""

    def test_spill_imediato_com_limiar_zero(self, tmp_path: Path) -> None:
        """limiar_memoria=0 faz o primeiro registro já causar spill."""
        with IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        ) as indice:
            # Antes de qualquer adição, deve estar em memória
            assert not indice.em_disco

            indice.adicionar_entrada(
                entrada_id="<ENTRADA_SPILL_1>",
                arquivo_token="<ARQUIVO_1>",
                aplicacao_codigo="VPL",
                ordem_de_leitura=0,
                inicio_byte=0,
                fim_byte=100,
                linha_inicial=1,
                linha_final=1,
            )

            # Após adicionar, deve ter spill para SQLite
            assert indice.em_disco
            assert indice.caminho_temporario is not None
            assert indice.caminho_temporario.exists()

    def test_spill_persiste_dados_corretamente(self, tmp_path: Path) -> None:
        """Dados são recuperáveis após spill com limiar=0."""
        with IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        ) as indice:
            # Adicionar várias entradas
            for i in range(50):
                indice.adicionar_entrada(
                    entrada_id=f"<ENTRADA_SP_{i:03d}>",
                    arquivo_token=f"<ARQUIVO_{(i % 10) + 1}>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=i,
                    inicio_byte=i * 100,
                    fim_byte=(i + 1) * 100,
                    linha_inicial=i + 1,
                    linha_final=i + 1,
                )

            assert indice.em_disco
            assert indice.quantidade_registros >= 50

            # Verificar recuperação de entradas
            registro = indice.obter_entrada("<ENTRADA_SP_025>")
            assert registro is not None
            assert registro.arquivo_token == "<ARQUIVO_6>"
            assert registro.ordem_de_leitura == 25

    def test_spill_remove_temporarios_ao_fechar(self, tmp_path: Path) -> None:
        """Arquivo SQLite temporário é removido ao fechar o índice."""
        indice = IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        )
        indice.adicionar_entrada(
            entrada_id="<ENTRADA_CLEANUP_1>",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=50,
            linha_inicial=1,
            linha_final=1,
        )

        caminho_sqlite = indice.caminho_temporario
        assert caminho_sqlite is not None
        assert caminho_sqlite.exists()

        indice.close()
        assert not caminho_sqlite.exists()


# ---------------------------------------------------------------------------
# Teste: Muitos identificadores únicos (~1000)
# ---------------------------------------------------------------------------


class TestMuitosIdentificadores:
    """Indexa ~1000 identificadores únicos e verifica busca correta."""

    def test_1000_identificadores_unicos_em_disco(
        self, tmp_path: Path
    ) -> None:
        """O índice suporta ~1000 identificadores com busca por digest."""
        with IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        ) as indice:
            # Criar 100 entradas com 10 identificadores cada = 1000 IDs
            for i in range(100):
                indice.adicionar_entrada(
                    entrada_id=f"<ENTRADA_IDS_{i:03d}>",
                    arquivo_token=f"<ARQUIVO_{(i % 10) + 1}>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=i,
                    inicio_byte=i * 200,
                    fim_byte=(i + 1) * 200,
                    linha_inicial=i + 1,
                    linha_final=i + 1,
                )
                for j in range(10):
                    indice.indexar_identificador(
                        entrada_id=f"<ENTRADA_IDS_{i:03d}>",
                        namespace="call_id",
                        valor_normalizado=f"SYNTH-ID-{i:03d}-{j:02d}",
                    )

            assert indice.em_disco
            assert indice.quantidade_registros >= 1100  # 100 entradas + 1000 IDs

            # Buscar um identificador específico
            resultados = indice.buscar_identificador(
                "call_id", "SYNTH-ID-050-05"
            )
            assert resultados == ("<ENTRADA_IDS_050>",)

            # Buscar identificador que não existe
            resultados_vazio = indice.buscar_identificador(
                "call_id", "INEXISTENTE"
            )
            assert resultados_vazio == ()


# ---------------------------------------------------------------------------
# Teste: Match raro e frequente
# ---------------------------------------------------------------------------


class TestMatchRaroFrequente:
    """Verifica que busca retorna corretamente com matches raros e frequentes."""

    def test_match_raro_um_entre_mil(self, tmp_path: Path) -> None:
        """Identificador raro aparece em 1 de 1000 entradas indexadas."""
        with IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        ) as indice:
            # 100 entradas, cada uma com ID "COMUM" no namespace "call_id"
            for i in range(100):
                indice.adicionar_entrada(
                    entrada_id=f"<ENTRADA_RARO_{i:03d}>",
                    arquivo_token=f"<ARQUIVO_{(i % 10) + 1}>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=i,
                    inicio_byte=i * 100,
                    fim_byte=(i + 1) * 100,
                    linha_inicial=i + 1,
                    linha_final=i + 1,
                )
                # Todas recebem ID "COMUM"
                indice.indexar_identificador(
                    entrada_id=f"<ENTRADA_RARO_{i:03d}>",
                    namespace="call_id",
                    valor_normalizado="SYNTH-COMUM-000",
                )

            # Apenas a entrada 42 recebe o ID raro
            indice.indexar_identificador(
                entrada_id="<ENTRADA_RARO_042>",
                namespace="call_id",
                valor_normalizado="SYNTH-RARO-UNICO",
            )

            # Busca pelo raro retorna apenas 1
            resultados_raro = indice.buscar_identificador(
                "call_id", "SYNTH-RARO-UNICO"
            )
            assert resultados_raro == ("<ENTRADA_RARO_042>",)

            # Busca pelo frequente retorna todas as 100
            resultados_frequente = indice.buscar_identificador(
                "call_id", "SYNTH-COMUM-000"
            )
            assert len(resultados_frequente) == 100

    def test_match_frequente_multiplos_namespaces(
        self, tmp_path: Path
    ) -> None:
        """Identificador frequente em namespace correto não contamina outro."""
        with IndiceTemporario(
            limiar_memoria=0, diretorio_temporario=str(tmp_path)
        ) as indice:
            for i in range(50):
                indice.adicionar_entrada(
                    entrada_id=f"<ENTRADA_NS_{i:03d}>",
                    arquivo_token=f"<ARQUIVO_{(i % 5) + 1}>",
                    aplicacao_codigo="ORK",
                    ordem_de_leitura=i,
                    inicio_byte=i * 80,
                    fim_byte=(i + 1) * 80,
                    linha_inicial=i + 1,
                    linha_final=i + 1,
                )
                # Mesmo valor em namespaces diferentes
                indice.indexar_identificador(
                    entrada_id=f"<ENTRADA_NS_{i:03d}>",
                    namespace="telecom_call_id",
                    valor_normalizado="SYNTH-SHARED-VALUE",
                )
                if i < 5:
                    indice.indexar_identificador(
                        entrada_id=f"<ENTRADA_NS_{i:03d}>",
                        namespace="session_id",
                        valor_normalizado="SYNTH-SHARED-VALUE",
                    )

            # namespace telecom retorna 50
            resultados_telecom = indice.buscar_identificador(
                "telecom_call_id", "SYNTH-SHARED-VALUE"
            )
            assert len(resultados_telecom) == 50

            # namespace session retorna apenas 5
            resultados_session = indice.buscar_identificador(
                "session_id", "SYNTH-SHARED-VALUE"
            )
            assert len(resultados_session) == 5


# ---------------------------------------------------------------------------
# Teste: Segundo passe seletivo (não materializa o lote inteiro)
# ---------------------------------------------------------------------------


class TestSegundoPasseSeletivo:
    """Valida que a materialização relê somente os intervalos selecionados."""

    def test_materializa_subconjunto_de_100_arquivos(
        self, tmp_path: Path
    ) -> None:
        """Dado 100 arquivos, a materialização lê somente os selecionados."""
        # Criar 100 arquivos
        caminhos = [
            _criar_arquivo_sintetico(tmp_path, i) for i in range(1, 101)
        ]

        # Preparar fontes com fingerprint
        fontes: list[FonteMaterializacao] = []
        for i, caminho in enumerate(caminhos, start=1):
            token = f"<ARQUIVO_{i}>"
            fp = _fingerprint_de(caminho)
            fontes.append(FonteMaterializacao(
                arquivo_token=token,
                caminho=caminho,
                fingerprint=fp,
            ))

        # Criar entradas indexadas para TODOS os 100 arquivos
        todas_entradas: list[EntradaIndexada] = []
        for i, caminho in enumerate(caminhos, start=1):
            token = f"<ARQUIVO_{i}>"
            entrada = _entrada_indexada_de_arquivo(
                caminho, token, f"<ENTRADA_SEL_{i:03d}>", i - 1
            )
            todas_entradas.append(entrada)

        # Selecionar apenas 3 entradas (arquivos 10, 50 e 90)
        selecionadas = [
            todas_entradas[9],   # ARQUIVO_10
            todas_entradas[49],  # ARQUIVO_50
            todas_entradas[89],  # ARQUIVO_90
        ]

        # Materializar somente as selecionadas
        materializador = MaterializadorSeletivo(fontes)
        resultado = materializador.materializar(selecionadas)

        # Devem aparecer exatamente 3 entradas materializadas
        assert len(resultado.entradas) == 3
        ids_materializados = {e.entrada_id for e in resultado.entradas}
        assert ids_materializados == {
            "<ENTRADA_SEL_010>",
            "<ENTRADA_SEL_050>",
            "<ENTRADA_SEL_090>",
        }

        # Cada texto reconstruído corresponde ao conteúdo do arquivo
        for entrada_mat in resultado.entradas:
            idx = int(entrada_mat.entrada_id.split("_")[-1].rstrip(">"))
            conteudo_esperado = caminhos[idx - 1].read_bytes().decode("utf-8")
            assert entrada_mat.texto_original == conteudo_esperado

    def test_segundo_passe_nao_le_arquivos_nao_selecionados(
        self, tmp_path: Path
    ) -> None:
        """Arquivos fora da seleção não são abertos no segundo passe."""
        # Criar 10 arquivos e depois tornar 7 deles ilegíveis
        caminhos = [
            _criar_arquivo_sintetico(tmp_path, i) for i in range(1, 11)
        ]

        # Capturar fingerprints ANTES de modificar permissões
        fontes: list[FonteMaterializacao] = []
        for i, caminho in enumerate(caminhos, start=1):
            token = f"<ARQUIVO_{i}>"
            fp = _fingerprint_de(caminho)
            fontes.append(FonteMaterializacao(
                arquivo_token=token,
                caminho=caminho,
                fingerprint=fp,
            ))

        # Entradas para TODOS os 10 arquivos
        todas_entradas: list[EntradaIndexada] = []
        for i, caminho in enumerate(caminhos, start=1):
            token = f"<ARQUIVO_{i}>"
            entrada = _entrada_indexada_de_arquivo(
                caminho, token, f"<ENTRADA_NL_{i:03d}>", i - 1
            )
            todas_entradas.append(entrada)

        # Selecionar apenas arquivos 2, 5 e 8
        selecionadas = [
            todas_entradas[1],  # ARQUIVO_2
            todas_entradas[4],  # ARQUIVO_5
            todas_entradas[7],  # ARQUIVO_8
        ]

        # Tornar os NÃO selecionados (1, 3, 4, 6, 7, 9, 10) ilegíveis
        nao_selecionados_idx = [0, 2, 3, 5, 6, 8, 9]
        for idx in nao_selecionados_idx:
            caminhos[idx].chmod(0o000)

        try:
            # Materialização deve funcionar pois só lê os selecionados
            materializador = MaterializadorSeletivo(fontes)
            resultado = materializador.materializar(selecionadas)

            assert len(resultado.entradas) == 3
            ids = {e.entrada_id for e in resultado.entradas}
            assert ids == {
                "<ENTRADA_NL_002>",
                "<ENTRADA_NL_005>",
                "<ENTRADA_NL_008>",
            }
        finally:
            # Restaurar permissões para limpeza
            for idx in nao_selecionados_idx:
                caminhos[idx].chmod(0o644)

    def test_segundo_passe_le_apenas_intervalo_parcial(
        self, tmp_path: Path
    ) -> None:
        """Materialização lê somente o intervalo [inicio_byte, fim_byte)."""
        # Criar arquivo com múltiplas linhas
        linhas = [
            f"2035-06-01 10:00:{i:02d}.000000 99.00% "
            f"[INFO] mod.c:1 CallId=SYNTH-PARCIAL-{i:03d} linha {i}\n"
            for i in range(20)
        ]
        conteudo = "".join(linhas)
        caminho = tmp_path / "multi_linhas.log"
        caminho.write_text(conteudo, encoding="utf-8", newline="")

        conteudo_bytes = caminho.read_bytes()
        fp = _fingerprint_de(caminho)
        token = "<ARQUIVO_1>"

        fonte = FonteMaterializacao(
            arquivo_token=token, caminho=caminho, fingerprint=fp
        )

        # Calcular offsets das linhas 5 e 15 (intervalo parcial)
        offsets: list[tuple[int, int]] = []
        pos = 0
        for linha in linhas:
            tamanho = len(linha.encode("utf-8"))
            offsets.append((pos, pos + tamanho))
            pos += tamanho

        # Selecionar apenas linhas 5 e 15
        entradas_parciais: list[EntradaIndexada] = []
        for idx in (5, 15):
            inicio, fim = offsets[idx]
            sha_parcial = hashlib.sha256(conteudo_bytes[inicio:fim]).hexdigest()
            prov = Proveniencia(
                arquivo_token=token,
                entrada_id=f"<ENTRADA_PARCIAL_{idx:03d}>",
                linha_inicial=idx + 1,
                linha_final=idx + 1,
            )
            entrada = EntradaIndexada(
                entrada_id=f"<ENTRADA_PARCIAL_{idx:03d}>",
                aplicacao="VPL",
                ordem_de_leitura=idx,
                texto_ref=ReferenciaTextoOriginal(
                    arquivo_token=token,
                    inicio_byte=inicio,
                    fim_byte=fim,
                    linha_inicial=idx + 1,
                    linha_final=idx + 1,
                    sha256=sha_parcial,
                ),
                cabecalho=(
                    CampoEstruturado(
                        nome="severidade",
                        valor_original="INFO",
                        proveniencia=prov,
                    ),
                ),
                identificadores_digest=("d",),
                timestamp_original="2035-06-01T10:00:00",
                timestamp_normalizado=datetime(
                    2035, 6, 1, 13, 0, 0, tzinfo=timezone.utc
                ),
                falhas=(),
                interpretada=True,
            )
            entradas_parciais.append(entrada)

        materializador = MaterializadorSeletivo([fonte])
        resultado = materializador.materializar(entradas_parciais)

        assert len(resultado.entradas) == 2
        # Cada texto corresponde exatamente à sua linha
        for entrada_mat in resultado.entradas:
            idx = int(
                entrada_mat.entrada_id.split("_")[-1].rstrip(">")
            )
            assert entrada_mat.texto_original == linhas[idx]
