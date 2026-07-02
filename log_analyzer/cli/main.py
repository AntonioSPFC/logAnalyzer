"""CLI entry point for the Analisador de Logs.

Initializes the registry via bootstrap, instantiates the Analisador_de_Logs,
parses command-line arguments and renders the analysis result.

Requirements: 6.1
"""

import sys

from log_analyzer.cli.apresentacao import renderizar_resultado
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.modelos import ArquivoSelecionado


def main() -> None:
    """Main entry point: initialize registry, parse CLI args, run analysis, render output.

    Usage:
        python -m log_analyzer <identificador> <app_id>:<caminho> [<app_id>:<caminho> ...]

    Example:
        python -m log_analyzer "call-123" VPL:logs/vpl.log ORK:logs/ork.log
    """
    # Initialize registry via bootstrap
    registro = criar_registro_padrao()
    analisador = Analisador_de_Logs(registro)

    # Parse command line arguments
    if len(sys.argv) < 3:
        print(
            "Uso: python -m log_analyzer <identificador> <app_id>:<caminho> [...]"
        )
        print(
            "Exemplo: python -m log_analyzer 'call-123' VPL:logs/vpl.log ORK:logs/ork.log"
        )
        sys.exit(1)

    identificador = sys.argv[1]
    selecao: list[ArquivoSelecionado] = []
    for arg in sys.argv[2:]:
        if ":" in arg:
            app_id, caminho = arg.split(":", 1)
            selecao.append(ArquivoSelecionado(caminho=caminho, app_id=app_id))
        else:
            selecao.append(ArquivoSelecionado(caminho=arg, app_id=None))

    try:
        resultado = analisador.analisar(selecao, identificador)
        print(renderizar_resultado(resultado))
    except ErroDeIdentificador as e:
        print(f"Erro: {e.mensagem}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
