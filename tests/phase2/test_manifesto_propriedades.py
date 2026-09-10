"""Auditoria mecânica da cobertura única das 30 propriedades Hypothesis da Fase 2.

Este módulo inspeciona `tests/phase2/properties/test_property_*.py` e exige:
- Exatamente os números 1–30, sem lacunas nem duplicatas.
- Um arquivo e uma função Hypothesis por número.
- Comentário `Feature: log-analyzer-phase-2, Property N: <título>` correspondente.
- `max_examples >= 100` no decorator `@settings`.

Duplicata, lacuna ou tag divergente falham o teste.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


_PROPERTIES_DIR = Path(__file__).resolve().parent / "properties"
_FILE_PATTERN = re.compile(r"^test_property_(\d{2})_(.+)\.py$")
_FEATURE_COMMENT = re.compile(
    r"#\s*Feature:\s*log-analyzer-phase-2,\s*Property\s+(\d+):\s*(.+)"
)
_SETTINGS_MAX_EXAMPLES = re.compile(r"max_examples\s*=\s*(\d+)")


def _extrair_funcoes_hypothesis(tree: ast.Module) -> list[ast.FunctionDef]:
    """Retorna funções de nível superior decoradas com @given."""
    funcoes = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            nome_decorador = _nome_do_decorador(decorator)
            if nome_decorador == "given":
                funcoes.append(node)
                break
    return funcoes


def _nome_do_decorador(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return _nome_do_decorador(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _extrair_max_examples_de_settings(tree: ast.Module, conteudo: str) -> list[int]:
    """Encontra todos os valores de max_examples em decoradores @settings."""
    valores: list[int] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            nome = _nome_do_decorador(decorator)
            if nome != "settings":
                continue
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg == "max_examples":
                        if isinstance(keyword.value, ast.Constant):
                            valores.append(int(keyword.value.value))
    # Fallback: buscar no texto (caso haja composição indireta)
    if not valores:
        for match in _SETTINGS_MAX_EXAMPLES.finditer(conteudo):
            valores.append(int(match.group(1)))
    return valores


def _extrair_comentarios_feature(conteudo: str) -> list[tuple[int, str]]:
    """Retorna pares (número_da_propriedade, título) de comentários Feature."""
    resultados = []
    for match in _FEATURE_COMMENT.finditer(conteudo):
        numero = int(match.group(1))
        titulo = match.group(2).strip()
        resultados.append((numero, titulo))
    return resultados


class _InfoPropriedade:
    """Informações extraídas de um arquivo de propriedade."""

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self.nome = caminho.name
        self.conteudo = caminho.read_text(encoding="utf-8")
        self.tree = ast.parse(self.conteudo, filename=str(caminho))
        self.funcoes_hypothesis = _extrair_funcoes_hypothesis(self.tree)
        self.comentarios_feature = _extrair_comentarios_feature(self.conteudo)
        self.max_examples_values = _extrair_max_examples_de_settings(
            self.tree, self.conteudo
        )

        # Número extraído do nome do arquivo
        match_nome = _FILE_PATTERN.match(self.nome)
        self.numero_arquivo: int | None = (
            int(match_nome.group(1)) if match_nome else None
        )


def test_manifesto_exatamente_30_arquivos() -> None:
    """Deve existir exatamente 30 arquivos test_property_NN_*.py."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    nomes = [a.name for a in arquivos]
    assert len(nomes) == 30, (
        f"Esperados 30 arquivos de propriedade, encontrados {len(nomes)}: {nomes}"
    )


def test_manifesto_numeros_1_a_30_sem_lacuna_nem_duplicata() -> None:
    """Os números no nome dos arquivos devem ser exatamente 1..30."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    numeros: list[int] = []
    for arq in arquivos:
        match = _FILE_PATTERN.match(arq.name)
        assert match is not None, (
            f"Arquivo não segue padrão test_property_NN_*.py: {arq.name}"
        )
        numeros.append(int(match.group(1)))

    numeros_sorted = sorted(numeros)
    esperados = list(range(1, 31))
    duplicados = [n for n in numeros_sorted if numeros_sorted.count(n) > 1]
    lacunas = [n for n in esperados if n not in numeros_sorted]
    extras = [n for n in numeros_sorted if n not in esperados]

    assert not duplicados, f"Números duplicados: {set(duplicados)}"
    assert not lacunas, f"Números ausentes (lacunas): {lacunas}"
    assert not extras, f"Números fora de 1–30: {extras}"
    assert numeros_sorted == esperados


def test_manifesto_uma_funcao_hypothesis_por_arquivo() -> None:
    """Cada arquivo deve conter exatamente uma função decorada com @given."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    erros: list[str] = []
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        qtd = len(info.funcoes_hypothesis)
        if qtd != 1:
            erros.append(f"{arq.name}: {qtd} funções @given (esperada 1)")
    assert not erros, "\n".join(erros)


def test_manifesto_comentario_feature_correspondente() -> None:
    """Cada arquivo deve ter comentário Feature com número igual ao do arquivo."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    erros: list[str] = []
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        if info.numero_arquivo is None:
            erros.append(f"{arq.name}: não segue padrão de nome")
            continue

        if not info.comentarios_feature:
            erros.append(
                f"{arq.name}: sem comentário "
                "'# Feature: log-analyzer-phase-2, Property N: <título>'"
            )
            continue

        numeros_no_comentario = [n for n, _ in info.comentarios_feature]
        if info.numero_arquivo not in numeros_no_comentario:
            erros.append(
                f"{arq.name}: comentário Feature menciona "
                f"{numeros_no_comentario}, esperado {info.numero_arquivo}"
            )

        # Verificar unicidade do número no comentário
        if len(numeros_no_comentario) > 1:
            erros.append(
                f"{arq.name}: múltiplos comentários Feature "
                f"({numeros_no_comentario}), esperado único"
            )

    assert not erros, "\n".join(erros)


def test_manifesto_max_examples_pelo_menos_100() -> None:
    """Cada arquivo deve usar @settings(max_examples=N) com N >= 100."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    erros: list[str] = []
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        if not info.max_examples_values:
            erros.append(f"{arq.name}: sem @settings(max_examples=...) encontrado")
            continue

        for valor in info.max_examples_values:
            if valor < 100:
                erros.append(
                    f"{arq.name}: max_examples={valor} (mínimo exigido: 100)"
                )

    assert not erros, "\n".join(erros)


def test_manifesto_sem_numero_duplicado_entre_comentarios() -> None:
    """Nenhum número de propriedade pode aparecer em mais de um arquivo."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    numero_para_arquivos: dict[int, list[str]] = {}
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        for numero, _ in info.comentarios_feature:
            numero_para_arquivos.setdefault(numero, []).append(arq.name)

    duplicados = {
        n: arqs for n, arqs in numero_para_arquivos.items() if len(arqs) > 1
    }
    assert not duplicados, (
        f"Propriedades declaradas em múltiplos arquivos: {duplicados}"
    )


def test_manifesto_cobertura_completa_comentarios_1_a_30() -> None:
    """Comentários Feature devem cobrir exatamente números 1–30."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    numeros_declarados: set[int] = set()
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        for numero, _ in info.comentarios_feature:
            numeros_declarados.add(numero)

    esperados = set(range(1, 31))
    ausentes = esperados - numeros_declarados
    extras = numeros_declarados - esperados

    assert not ausentes, f"Propriedades sem comentário Feature: {sorted(ausentes)}"
    assert not extras, (
        f"Comentários Feature com números fora de 1–30: {sorted(extras)}"
    )


def test_manifesto_nome_funcao_contem_numero_da_propriedade() -> None:
    """A função Hypothesis de cada arquivo deve conter o número da propriedade."""
    arquivos = sorted(_PROPERTIES_DIR.glob("test_property_*.py"))
    erros: list[str] = []
    for arq in arquivos:
        info = _InfoPropriedade(arq)
        if info.numero_arquivo is None:
            continue
        if not info.funcoes_hypothesis:
            continue

        func = info.funcoes_hypothesis[0]
        numero_str = f"_{info.numero_arquivo:02d}_" if info.numero_arquivo < 10 else f"_{info.numero_arquivo}_"
        # Aceitar tanto formato com zero à esquerda quanto sem
        numero_sem_zero = f"_{info.numero_arquivo}_"
        if numero_str not in func.name and numero_sem_zero not in func.name:
            erros.append(
                f"{arq.name}: função '{func.name}' não contém "
                f"número da propriedade ({info.numero_arquivo})"
            )

    assert not erros, "\n".join(erros)
