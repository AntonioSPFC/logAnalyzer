"""Configuração global de testes — perfil Hypothesis com max_examples=100."""

from hypothesis import settings, HealthCheck

# Registrar perfil com 100 exemplos por teste de propriedade
settings.register_profile(
    "default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)

# Carregar o perfil por padrão
settings.load_profile("default")
