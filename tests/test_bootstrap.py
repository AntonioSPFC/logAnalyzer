"""Testes de bootstrap do Registro_de_Aplicacoes.

Smoke test para verificar que o registro inicial contém exatamente VPL, ORK e VOCI
com ids únicos e um par parser+padrão cada (Req 6.1, 6.2, 6.3, 6.4, 6.5).
"""

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.apps.vpl import VplParser
from log_analyzer.apps.ork import OrkParser
from log_analyzer.apps.voci import VociParser
from log_analyzer.apps.padroes import VplPadrao, OrkPadrao, VociPadrao


class TestBootstrapRegistroPadrao:
    """Smoke tests para criar_registro_padrao (Req 6.1–6.5)."""

    def test_registro_contem_exatamente_3_aplicacoes(self) -> None:
        """O registro inicial contém exatamente 3 Aplicações."""
        registro = criar_registro_padrao()
        assert len(registro.aplicacoes_suportadas()) == 3

    def test_registro_contem_vpl_ork_voci(self) -> None:
        """O registro contém exatamente VPL, ORK e VOCI."""
        registro = criar_registro_padrao()
        apps = set(registro.aplicacoes_suportadas())
        assert apps == {"VPL", "ORK", "VOCI"}

    def test_app_ids_sao_unicos(self) -> None:
        """Cada app_id no registro é único."""
        registro = criar_registro_padrao()
        ids = registro.aplicacoes_suportadas()
        assert len(ids) == len(set(ids))

    def test_vpl_tem_parser_e_padrao(self) -> None:
        """VPL está registrada com seu parser e padrão."""
        registro = criar_registro_padrao()
        parser, padrao = registro.obter("VPL")
        assert isinstance(parser, Parser_de_Aplicacao)
        assert isinstance(padrao, Padrao_de_Analise)
        assert isinstance(parser, VplParser)
        assert isinstance(padrao, VplPadrao)

    def test_ork_tem_parser_e_padrao(self) -> None:
        """ORK está registrada com seu parser e padrão."""
        registro = criar_registro_padrao()
        parser, padrao = registro.obter("ORK")
        assert isinstance(parser, Parser_de_Aplicacao)
        assert isinstance(padrao, Padrao_de_Analise)
        assert isinstance(parser, OrkParser)
        assert isinstance(padrao, OrkPadrao)

    def test_voci_tem_parser_e_padrao(self) -> None:
        """VOCI está registrada com seu parser e padrão."""
        registro = criar_registro_padrao()
        parser, padrao = registro.obter("VOCI")
        assert isinstance(parser, Parser_de_Aplicacao)
        assert isinstance(padrao, Padrao_de_Analise)
        assert isinstance(parser, VociParser)
        assert isinstance(padrao, VociPadrao)

    def test_cada_app_esta_registrada(self) -> None:
        """Verifica esta_registrada para cada Aplicação."""
        registro = criar_registro_padrao()
        assert registro.esta_registrada("VPL")
        assert registro.esta_registrada("ORK")
        assert registro.esta_registrada("VOCI")

    def test_app_nao_existente_nao_esta_registrada(self) -> None:
        """Uma Aplicação não registrada não está no catálogo."""
        registro = criar_registro_padrao()
        assert not registro.esta_registrada("INEXISTENTE")
