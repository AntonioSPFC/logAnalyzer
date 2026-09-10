"""Guarda automatizada contra uso de fontes brutas locais.

Varre código de fixtures, catálogos e testes da Fase 2 e falha diante de
referência, import ou cópia de ``logs/``, ``curation.db``, relatórios ou
dashboard como fonte de regra.

Permite somente os artefatos sintéticos/sanitizados em
``tests/fixtures/log_analyzer_phase2``.

Validates: Requirements 14.5, 14.6, 14.8.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Sequence

import pytest


# ─── Diretórios do projeto ──────────────────────────────────────────────────
_RAIZ_PROJETO = Path(__file__).resolve().parents[2]

# Diretórios que devem ser varridos
_DIRS_VARREDURA: list[Path] = [
    _RAIZ_PROJETO / "tests" / "phase2",
    _RAIZ_PROJETO / "tests" / "fixtures" / "log_analyzer_phase2",
    _RAIZ_PROJETO / "log_analyzer" / "catalogos",
]

# Diretório permitido como fonte legítima de dados de teste
_FIXTURE_PERMITIDA = _RAIZ_PROJETO / "tests" / "fixtures" / "log_analyzer_phase2"

# Extensões de arquivos de código/dados a serem inspecionados
_EXTENSOES_CODIGO = {".py", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt"}


# ─── Padrões proibidos ──────────────────────────────────────────────────────

# Regex para detectar referências a fontes brutas
_PADROES_PROIBIDOS: list[tuple[re.Pattern[str], str]] = [
    # Referências ao diretório logs/ (string literal ou path)
    (
        re.compile(
            r"""(?x)
            (?:^|[/"'\\(,\s])      # delimitador que antecede
            (?:\.\.?[/\\])*        # prefixos relativos opcionais
            logs[/\\]              # diretório logs/ (forward ou backslash)
            """,
        ),
        "REFERENCIA_LOGS_DIR",
    ),
    # Referências literais a "logs/" em strings
    (
        re.compile(
            r"""(?x)
            ["']                   # abertura de string
            [^"']*                 # conteúdo antes
            (?:\.\.?[/\\])*        # relativos
            logs[/\\]              # diretório logs
            [^"']*                 # conteúdo depois
            ["']                   # fechamento
            """,
        ),
        "STRING_LITERAL_LOGS",
    ),
    # Referência a curation.db
    (
        re.compile(
            r"""(?ix)
            curation\.db
            """,
        ),
        "REFERENCIA_CURATION_DB",
    ),
    # Referência ao diretório dashboard como fonte de dados
    (
        re.compile(
            r"""(?x)
            (?:^|[/"'\\(,\s])
            (?:\.\.?[/\\])*
            dashboard[/\\]
            """,
        ),
        "REFERENCIA_DASHBOARD_DIR",
    ),
    # Import do módulo dashboard
    (
        re.compile(
            r"""(?x)
            (?:^|\s)
            (?:from|import)\s+
            dashboard
            """,
        ),
        "IMPORT_DASHBOARD",
    ),
    # Referência a relatórios brutos como fonte
    (
        re.compile(
            r"""(?ix)
            (?:raw[_-]?reports?|reports?[_-]?raw|relatorios?[_-]?brutos?)
            """,
        ),
        "REFERENCIA_RELATORIO_BRUTO",
    ),
]

# Padrão para detectar open()/read() de fontes brutas em AST
_FONTES_BRUTAS_PATHS = re.compile(
    r"""(?ix)
    (?:logs[/\\]|curation\.db|dashboard[/\\]|
       raw[_-]?reports?|reports?[_-]?raw|relatorios?[_-]?brutos?)
    """,
)


# ─── Exclusões legítimas ────────────────────────────────────────────────────

def _e_exclusao_legitima(arquivo: Path, linha: str) -> bool:
    """Retorna True se a linha é parte de código de verificação/governança.

    Exclui:
    - Este próprio arquivo de higiene.
    - Módulos de estratégias que definem constantes de nomes proibidos para
      enforcement (não como fontes de dados).
    - Testes que validam a rejeição de fontes brutas (passam paths como input
      de asserção, não os leem como dados).
    - Testes de governança que verificam o scanner.
    """
    # Próprio teste de higiene pode mencionar os padrões em docstrings/comentários
    if arquivo.name == "test_higiene_fixtures.py":
        return True
    # O módulo de governança define os padrões e precisa referenciá-los
    if "governanca" in arquivo.name and arquivo.suffix == ".py":
        # Se é a definição de padrão em governanca.py (código de produção)
        if arquivo.parent.name == "core":
            return True
    # Testes de governança que validam o scanner contra fontes proibidas
    if "governanca" in arquivo.name and "test_" in arquivo.name:
        # Linhas que são asserts verificando rejeição ou docstrings explicativas
        stripped = linha.strip()
        if stripped.startswith(("#", '"""', "'''", "assert", "# ")):
            return True
        # Strings usadas para testar o scanner (passadas a ele como argumento)
        if "FONTE_PROIBIDA" in linha or "_tipo_fonte_proibida" in linha:
            return True
    # Módulos de estratégias que definem constantes de enforcement
    # (ex: _FORBIDDEN_FILE_NAMES, _FORBIDDEN_DIRECTORY_NAMES) — não leem dados
    if arquivo.parent.name == "strategies" and arquivo.suffix == ".py":
        stripped = linha.strip()
        if any(
            kw in linha
            for kw in ("_FORBIDDEN_", "FORBIDDEN_", "forbidden_")
        ):
            return True
    # Testes do suporte sintético que verificam a rejeição de fontes brutas
    # (passam strings como argumento para assert_no_raw_source_reference ou
    # write_lines e esperam exceção — não leem os arquivos reais)
    if arquivo.name == "test_synthetic_support.py":
        stripped = linha.strip()
        if any(
            kw in linha
            for kw in (
                "assert_no_raw_source_reference",
                "pytest.raises",
                "factory.write_lines",
            )
        ):
            return True
    return False


def _e_arquivo_do_proprio_teste(arquivo: Path) -> bool:
    """Verifica se é este próprio arquivo de teste."""
    return arquivo.resolve() == Path(__file__).resolve()


# ─── Varredura ──────────────────────────────────────────────────────────────

def _coletar_arquivos(diretorios: Sequence[Path]) -> list[Path]:
    """Coleta todos os arquivos de código/dados nos diretórios alvo."""
    arquivos: list[Path] = []
    for diretorio in diretorios:
        if not diretorio.exists():
            continue
        for arquivo in diretorio.rglob("*"):
            if arquivo.suffix not in _EXTENSOES_CODIGO:
                continue
            if "__pycache__" in arquivo.parts:
                continue
            if _e_arquivo_do_proprio_teste(arquivo):
                continue
            arquivos.append(arquivo)
    return sorted(arquivos)


def _varrer_arquivo(arquivo: Path) -> list[tuple[int, str, str]]:
    """Varre um arquivo por referências proibidas.

    Returns:
        Lista de (linha_num, tipo_violacao, conteudo_linha).
    """
    violacoes: list[tuple[int, str, str]] = []
    try:
        conteudo = arquivo.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return violacoes

    for num_linha, linha in enumerate(conteudo.splitlines(), start=1):
        # Pular comentários puros e docstrings em contexto de definição de padrão
        if _e_exclusao_legitima(arquivo, linha):
            continue

        for padrao, tipo in _PADROES_PROIBIDOS:
            if padrao.search(linha):
                violacoes.append((num_linha, tipo, linha.rstrip()))

    return violacoes


def _varrer_imports_ast(arquivo: Path) -> list[tuple[int, str, str]]:
    """Usa AST para detectar imports de módulos de fontes brutas."""
    violacoes: list[tuple[int, str, str]] = []
    if arquivo.suffix != ".py":
        return violacoes
    if _e_arquivo_do_proprio_teste(arquivo):
        return violacoes

    try:
        conteudo = arquivo.read_text(encoding="utf-8")
        tree = ast.parse(conteudo, filename=str(arquivo))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return violacoes

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _FONTES_BRUTAS_PATHS.search(alias.name or ""):
                    violacoes.append(
                        (node.lineno, "IMPORT_FONTE_BRUTA", f"import {alias.name}")
                    )
        elif isinstance(node, ast.ImportFrom):
            modulo = node.module or ""
            if _FONTES_BRUTAS_PATHS.search(modulo):
                violacoes.append(
                    (node.lineno, "IMPORT_FROM_FONTE_BRUTA", f"from {modulo} import ...")
                )

    return violacoes


def _varrer_strings_path_ast(arquivo: Path) -> list[tuple[int, str, str]]:
    """Detecta strings literais que referenciam fontes brutas via AST."""
    violacoes: list[tuple[int, str, str]] = []
    if arquivo.suffix != ".py":
        return violacoes
    if _e_arquivo_do_proprio_teste(arquivo):
        return violacoes

    # Exclusão para arquivos de governança que testam o scanner
    if "governanca" in arquivo.name and "test_" in arquivo.name:
        return violacoes
    # Exclusão para estratégias que definem constantes de enforcement
    if arquivo.parent.name == "strategies":
        return violacoes
    # Exclusão para testes que validam a rejeição de fontes (input para assert)
    if arquivo.name == "test_synthetic_support.py":
        return violacoes

    try:
        conteudo = arquivo.read_text(encoding="utf-8")
        tree = ast.parse(conteudo, filename=str(arquivo))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return violacoes

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            valor = node.value
            if _FONTES_BRUTAS_PATHS.search(valor):
                violacoes.append(
                    (node.lineno, "STRING_FONTE_BRUTA", repr(valor)[:120])
                )

    return violacoes


# ─── Testes ─────────────────────────────────────────────────────────────────

class TestHigieneFixturesFase2:
    """Garante que nenhum código/fixture da Fase 2 referencia fontes brutas."""

    def test_nenhuma_referencia_textual_a_fontes_brutas(self) -> None:
        """Varre código por referências textuais a logs/, curation.db, etc."""
        arquivos = _coletar_arquivos(_DIRS_VARREDURA)
        assert arquivos, "Nenhum arquivo encontrado para varredura"

        todas_violacoes: list[str] = []
        for arquivo in arquivos:
            violacoes = _varrer_arquivo(arquivo)
            for num, tipo, conteudo in violacoes:
                rel = arquivo.relative_to(_RAIZ_PROJETO)
                todas_violacoes.append(
                    f"  {rel}:{num} [{tipo}] {conteudo[:100]}"
                )

        assert not todas_violacoes, (
            f"Referências proibidas a fontes brutas encontradas "
            f"({len(todas_violacoes)} violação(ões)):\n"
            + "\n".join(todas_violacoes[:30])
        )

    def test_nenhum_import_de_fonte_bruta(self) -> None:
        """Varre imports Python por módulos de fontes brutas."""
        arquivos = _coletar_arquivos(_DIRS_VARREDURA)

        todas_violacoes: list[str] = []
        for arquivo in arquivos:
            violacoes = _varrer_imports_ast(arquivo)
            for num, tipo, conteudo in violacoes:
                rel = arquivo.relative_to(_RAIZ_PROJETO)
                todas_violacoes.append(
                    f"  {rel}:{num} [{tipo}] {conteudo}"
                )

        assert not todas_violacoes, (
            f"Imports de fontes brutas encontrados "
            f"({len(todas_violacoes)} violação(ões)):\n"
            + "\n".join(todas_violacoes[:30])
        )

    def test_nenhuma_string_literal_com_path_de_fonte_bruta(self) -> None:
        """Varre strings Python por paths apontando para fontes brutas."""
        arquivos = _coletar_arquivos(_DIRS_VARREDURA)

        todas_violacoes: list[str] = []
        for arquivo in arquivos:
            violacoes = _varrer_strings_path_ast(arquivo)
            for num, tipo, conteudo in violacoes:
                rel = arquivo.relative_to(_RAIZ_PROJETO)
                todas_violacoes.append(
                    f"  {rel}:{num} [{tipo}] {conteudo}"
                )

        assert not todas_violacoes, (
            f"Strings com paths de fontes brutas encontradas "
            f"({len(todas_violacoes)} violação(ões)):\n"
            + "\n".join(todas_violacoes[:30])
        )

    def test_fixtures_usam_somente_diretorio_permitido(self) -> None:
        """Verifica que referências a fixtures apontam para o diretório governado."""
        arquivos = _coletar_arquivos(
            [_RAIZ_PROJETO / "tests" / "phase2"]
        )

        # Padrão para detectar construção de Path para fixtures
        padrao_fixture = re.compile(
            r"""(?x)
            (?:fixtures?|FIXTURE|fixture_path|fixture_dir)
            \s*[=/]
            """,
        )
        # Padrão para o caminho permitido
        caminho_permitido = re.compile(
            r"""(?x)
            (?:log_analyzer_phase2|fixtures[/\\]log_analyzer_phase2)
            """,
        )
        # Padrão de fontes brutas
        padrao_fonte_bruta = re.compile(
            r"""(?ix)
            (?:["']|Path\()
            [^)"']*
            (?:logs[/\\]|curation\.db|dashboard[/\\])
            """,
        )

        violacoes: list[str] = []
        for arquivo in arquivos:
            if _e_arquivo_do_proprio_teste(arquivo):
                continue
            if arquivo.suffix != ".py":
                continue
            # Exclusão para estratégias que definem constantes de enforcement
            if arquivo.parent.name == "strategies":
                continue
            # Exclusão para testes que validam rejeição de fontes brutas
            if arquivo.name == "test_synthetic_support.py":
                continue

            try:
                conteudo = arquivo.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for num, linha in enumerate(conteudo.splitlines(), start=1):
                if padrao_fonte_bruta.search(linha):
                    # Excluir linhas que são testes do scanner de governança
                    if "governanca" in arquivo.name:
                        continue
                    rel = arquivo.relative_to(_RAIZ_PROJETO)
                    violacoes.append(
                        f"  {rel}:{num} [PATH_FONTE_BRUTA_FIXTURE] "
                        f"{linha.strip()[:100]}"
                    )

        assert not violacoes, (
            f"Referências a fontes brutas em contexto de fixture "
            f"({len(violacoes)} violação(ões)):\n"
            + "\n".join(violacoes[:30])
        )

    def test_catalogos_nao_referenciam_fontes_externas(self) -> None:
        """Catálogos JSON não devem apontar para logs/, curation.db ou dashboard."""
        dir_catalogos = _RAIZ_PROJETO / "log_analyzer" / "catalogos"
        if not dir_catalogos.exists():
            pytest.skip("Diretório de catálogos não encontrado")

        violacoes: list[str] = []
        for arquivo in dir_catalogos.rglob("*.json"):
            try:
                conteudo = arquivo.read_text(encoding="utf-8")
            except OSError:
                continue

            for num, linha in enumerate(conteudo.splitlines(), start=1):
                if _FONTES_BRUTAS_PATHS.search(linha):
                    rel = arquivo.relative_to(_RAIZ_PROJETO)
                    violacoes.append(
                        f"  {rel}:{num} [CATALOGO_FONTE_BRUTA] "
                        f"{linha.strip()[:100]}"
                    )

        assert not violacoes, (
            f"Catálogos referenciam fontes brutas "
            f"({len(violacoes)} violação(ões)):\n"
            + "\n".join(violacoes[:30])
        )

    def test_fixture_governada_existe_e_e_valida(self) -> None:
        """O diretório de fixtures permitido existe e contém artefatos."""
        assert _FIXTURE_PERMITIDA.exists(), (
            f"Diretório de fixtures governadas não encontrado: {_FIXTURE_PERMITIDA}"
        )
        arquivos = list(_FIXTURE_PERMITIDA.rglob("*"))
        arquivos_reais = [f for f in arquivos if f.is_file()]
        assert arquivos_reais, (
            f"Diretório de fixtures governadas está vazio: {_FIXTURE_PERMITIDA}"
        )
