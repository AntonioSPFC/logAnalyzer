"""Plugins de Aplicação — parsers e padrões de análise (VPL, ORK, VOCI)."""

from log_analyzer.apps.vpl import VplParser
from log_analyzer.apps.ork import OrkParser
from log_analyzer.apps.voci import VociParser
from log_analyzer.apps.padroes import OrkPadrao, VociPadrao, VplPadrao

__all__ = ["VplParser", "OrkParser", "VociParser", "VplPadrao", "OrkPadrao", "VociPadrao"]
