"""Bootstrap do Registro_de_Aplicacoes — estado inicial do Analisador_de_Logs.

Registra exatamente VPL, ORK e VOCI, cada uma com seu parser e padrão,
com app_id único. Esta é a função de inicialização que monta o catálogo
antes da primeira análise (Req 6.1, 6.2, 6.3, 6.4, 6.5).
"""

from log_analyzer.core.registro import Registro_de_Aplicacoes


def criar_registro_padrao() -> Registro_de_Aplicacoes:
    """Creates and returns a Registro_de_Aplicacoes with VPL, ORK, and VOCI registered.

    This is the initial registry state when the Analisador_de_Logs starts.
    Each application has a unique app_id and its corresponding parser + padrao pair.

    Returns:
        Registro_de_Aplicacoes com exatamente 3 Aplicações registradas:
        VPL, ORK e VOCI.
    """
    # Lazy imports to avoid circular dependency:
    # core.__init__ -> bootstrap -> apps.vpl -> core.interfaces -> core.__init__ (cycle)
    from log_analyzer.apps.vpl import VplParser
    from log_analyzer.apps.ork import OrkParser
    from log_analyzer.apps.voci import VociParser
    from log_analyzer.apps.padroes import VplPadrao, OrkPadrao, VociPadrao

    registro = Registro_de_Aplicacoes()
    registro.registrar("VPL", VplParser(), VplPadrao())
    registro.registrar("ORK", OrkParser(), OrkPadrao())
    registro.registrar("VOCI", VociParser(), VociPadrao())
    return registro
