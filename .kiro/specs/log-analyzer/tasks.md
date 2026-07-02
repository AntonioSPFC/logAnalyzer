# Implementation Plan: log-analyzer (Fase 1 — Estrutura)

## Overview

Este plano implementa a arquitetura extensível (estilo *plugin*) do Analisador_de_Logs em
**Python 3.11+**, com testes baseados em propriedades usando **Hypothesis** (mínimo de 100
exemplos por propriedade). A construção é incremental: primeiro a fundação (modelos de dados,
exceções e interfaces comuns), depois o Registro_de_Aplicacoes e os plugins das Aplicações
iniciais (VPL, ORK, VOCI), em seguida as funções de núcleo (carregamento, filtragem, validação,
ordenação, agrupamento, correlação e contagens), o orquestrador que conecta tudo e, por fim, a
camada de apresentação CLI e o ponto de entrada.

Cada uma das 16 propriedades de corretude do design é implementada como um único teste baseado
em propriedade, anotado com a tag `Feature: log-analyzer, Property {n}` e configurado com
`@settings(max_examples=100)`.

## Tasks

- [x] 1. Configurar estrutura do projeto e ferramentas de teste
  - [x] 1.1 Criar estrutura de diretórios e configuração de testes
    - Criar pacote `log_analyzer/` (com submódulos `core/`, `apps/`, `cli/`) e diretório `tests/`
    - Configurar `pyproject.toml` com dependências `pytest` e `hypothesis`
    - Adicionar fixture/conftest com perfil Hypothesis de `max_examples=100`
    - _Requirements: 7.3, 7.4_

- [x] 2. Implementar modelos de dados e hierarquia de exceções
  - [x] 2.1 Implementar os modelos de dados do domínio
    - Definir `Categoria` (SUCESSO, ERRO, NAO_CLASSIFICADA)
    - Definir `EntradaDeLog` (frozen) com `texto_original`, `aplicacao`, `ordem_de_leitura`,
      `interpretada`, `carimbo_de_tempo`, `nivel_de_severidade`, `mensagem`, `categoria`,
      `correlacionada`
    - Definir `ArquivoSelecionado`, `MensagemDeErro` e `ResultadoDeAnalise`
    - Garantir invariante INV-1/INV-2 nas construções (campos obrigatórios quando interpretada;
      `texto_original` sempre preservado)
    - _Requirements: 4.1, 4.3, 5.4, 8.3, 3.3, 9.4_

  - [x] 2.2 Implementar a hierarquia de exceções
    - Definir `ErroDoAnalisador` (base), `ErroDeRegistro`, `ErroDeArquivo`, `ErroDeIdentificador`
    - _Requirements: 7.5, 7.6, 6.8, 2.2, 1.2, 1.4, 10.5, 3.5, 10.2, 10.3_

- [x] 3. Definir as interfaces comuns dos plugins
  - [x] 3.1 Implementar a interface abstrata `Parser_de_Aplicacao`
    - Usar `abc.ABC` + `@abstractmethod`: `niveis_de_severidade`, `interpretar_entrada`,
      `imprimir_entrada`, e `interpretar_arquivo` (default em streaming)
    - _Requirements: 7.3, 4.1, 4.2, 4.3, 4.4_

  - [x] 3.2 Implementar a interface abstrata `Padrao_de_Analise`
    - Usar `abc.ABC` + `@abstractmethod`: propriedade `categorias` (mínimo SUCESSO e ERRO) e
      método `classificar`
    - _Requirements: 7.4, 5.3, 5.4_

- [x] 4. Implementar o `Registro_de_Aplicacoes`
  - [x] 4.1 Implementar `registrar`, `obter`, `aplicacoes_suportadas`, `esta_registrada`
    - Validar `app_id` único (rejeitar duplicado preservando o existente)
    - Validar que `parser`/`padrao` implementam as interfaces comuns (senão `ErroDeRegistro`)
    - `obter` levanta `AplicacaoNaoSuportada`/`ErroDeRegistro` quando ausente
    - Em qualquer falha, não alterar o catálogo
    - _Requirements: 5.1, 1.5, 2.2, 6.8, 7.1, 7.2, 7.5, 7.6_

  - [x] 4.2 Escrever teste de propriedade para registro inválido
    - **Property 12: Registro/associação inválida não altera o estado**
    - **Validates: Requirements 2.2, 6.8, 7.5, 7.6**

  - [x] 4.3 Escrever teste de propriedade para extensibilidade
    - **Property 13: Extensibilidade preserva as Aplicações existentes**
    - **Validates: Requirements 7.1, 7.2**

- [x] 5. Implementar os parsers das Aplicações iniciais (VPL, ORK, VOCI)
  - [x] 5.1 Implementar `VplParser`
    - Implementar `niveis_de_severidade`, `interpretar_entrada` (marca como não interpretada
      quando faltar carimbo de tempo válido, severidade válida ou mensagem) e `imprimir_entrada`
    - _Requirements: 6.2, 6.7, 4.1, 4.2, 4.3, 4.4_

  - [x] 5.2 Implementar `OrkParser`
    - Mesmos contratos do `VplParser` para o formato do ORK
    - _Requirements: 6.3, 6.7, 4.1, 4.2, 4.3, 4.4_

  - [x] 5.3 Implementar `VociParser`
    - Mesmos contratos do `VplParser` para o formato do VOCI
    - _Requirements: 6.4, 6.7, 4.1, 4.2, 4.3, 4.4_

  - [x] 5.4 Escrever teste de propriedade de round-trip dos parsers
    - **Property 1: Round-trip de interpretação preserva os campos**
    - **Validates: Requirements 4.4, 4.5**

  - [x] 5.5 Escrever teste de propriedade de corretude da interpretação
    - **Property 2: Corretude da interpretação (campos completos ⇔ interpretada)**
    - **Validates: Requirements 4.1, 4.2, 6.7**

  - [x] 5.6 Escrever teste de propriedade de preservação do texto original
    - **Property 3: Preservação do texto original**
    - **Validates: Requirements 4.3, 5.4, 6.7, 8.4**

- [x] 6. Implementar os Padrões de Análise da Fase 1
  - [x] 6.1 Implementar `VplPadrao`, `OrkPadrao` e `VociPadrao`
    - `categorias` inclui no mínimo SUCESSO e ERRO; `classificar` sempre retorna
      `NAO_CLASSIFICADA` na Fase 1, preservando o conteúdo original
    - _Requirements: 5.3, 5.4, 6.6_

  - [x] 6.2 Escrever teste de propriedade de classificação da Fase 1
    - **Property 10: Classificação na Fase 1 é uma categoria válida e "não classificada"**
    - **Validates: Requirements 5.3, 5.4, 6.6**

- [x] 7. Implementar o bootstrap do Registro_de_Aplicacoes
  - [x] 7.1 Implementar a função de bootstrap
    - Registrar exatamente VPL, ORK e VOCI, cada uma com seu parser e padrão, com `app_id` único
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 7.2 Escrever teste de propriedade de roteamento parser/padrão
    - **Property 7: Roteamento parser/padrão pela Aplicação associada**
    - **Validates: Requirements 1.3, 5.2**

  - [x] 7.3 Escrever teste de exemplo (smoke) do bootstrap
    - Verificar que o registro inicial contém exatamente VPL, ORK e VOCI com ids únicos e um
      par parser+padrão cada
    - _Requirements: 6.1, 6.5_

- [x] 8. Implementar o carregador de arquivos
  - [x] 8.1 Implementar leitura em streaming com validações
    - Leitura linha a linha; rejeitar arquivo ilegível, vazio ou acima de 500 MB produzindo
      `MensagemDeErro` que identifica o arquivo; não abortar os demais
    - _Requirements: 1.1, 1.2, 1.4, 10.4, 10.5_

- [x] 9. Implementar filtragem por Identificador e validação
  - [x] 9.1 Implementar o filtro por Identificador (case-insensitive)
    - Selecionar exatamente as entradas cujo conteúdo corresponde ao Identificador
    - _Requirements: 3.1, 3.2_

  - [x] 9.2 Escrever teste de propriedade da filtragem
    - **Property 4: Filtragem por Identificador é correta e completa**
    - **Validates: Requirements 3.1, 3.2**

  - [x] 9.3 Implementar a validação do Identificador
    - Rejeitar vazio, somente espaços ou com mais de 256 caracteres; preservar o estado anterior
    - _Requirements: 3.5, 10.2, 10.3_

  - [x] 9.4 Escrever teste de propriedade da validação do Identificador
    - **Property 9: Validação do Identificador rejeita e preserva o estado**
    - **Validates: Requirements 3.5, 10.2, 10.3**

- [x] 10. Implementar ordenação determinística e agrupamento
  - [x] 10.1 Implementar a ordenação da linha do tempo
    - Ordenar pela chave total `(carimbo_de_tempo, nome_da_aplicacao, ordem_de_leitura)`
    - _Requirements: 3.4, 8.1, 8.2_

  - [x] 10.2 Escrever teste de propriedade da ordenação
    - **Property 5: Ordenação determinística da linha do tempo**
    - **Validates: Requirements 3.4, 8.1, 8.2**

  - [x] 10.3 Implementar o agrupamento por Aplicação
    - Particionar as entradas selecionadas em `entradas_por_aplicacao`
    - _Requirements: 3.3_

  - [x] 10.4 Escrever teste de propriedade do agrupamento
    - **Property 6: Agrupamento por Aplicação**
    - **Validates: Requirements 3.3**

- [x] 11. Implementar o Correlacionador VPL ↔ ORK
  - [x] 11.1 Implementar a correlação e a linha do tempo unificada
    - Marcar `correlacionada=True` nas entradas que compartilham o Identificador; definir
      `correlacao_encontrada`; preservar entradas e registrar erro se um lado estiver indisponível
    - _Requirements: 8.1, 8.3, 8.4, 8.5_

  - [x] 11.2 Escrever teste de propriedade da correlação
    - **Property 14: Correlação VPL ↔ ORK marca exatamente os Identificadores compartilhados**
    - **Validates: Requirements 8.3, 8.4**

- [x] 12. Implementar a composição das contagens do Resultado_de_Analise
  - [x] 12.1 Implementar contagens por categoria e por Aplicação
    - Preencher `contagem_por_categoria` e `contagem_por_aplicacao` consistentes com as entradas
    - _Requirements: 9.4_

  - [x] 12.2 Escrever teste de propriedade da integridade das contagens
    - **Property 15: Integridade das contagens do Resultado_de_Analise**
    - **Validates: Requirements 9.4**

- [x] 13. Implementar o orquestrador `Analisador_de_Logs`
  - [x] 13.1 Implementar `analisar()` conectando todo o pipeline
    - Validar entradas; resolver parser/padrão via Registro; carregar, interpretar, filtrar,
      classificar, correlacionar e compor o resultado; aplicar reassociação (última Aplicação
      prevalece); acumular erros sem abortar; tratar "nenhum arquivo" e "Aplicação não informada"
    - _Requirements: 2.3, 2.4, 2.5, 3.6, 10.1, 1.2, 5.6_

  - [x] 13.2 Escrever teste de propriedade de robustez
    - **Property 8: Robustez — entradas inválidas não impedem o processamento das válidas**
    - **Validates: Requirements 1.2, 1.4, 1.5, 10.4, 10.5**

  - [x] 13.3 Escrever teste de propriedade de reassociação
    - **Property 11: Reassociação faz a última Aplicação prevalecer**
    - **Validates: Requirements 2.5**

  - [x] 13.4 Escrever testes de exemplo/edge do orquestrador
    - Nenhuma correspondência (resultado vazio + mensagem); nenhum arquivo carregado
      (Identificador preservado); Aplicação não informada e expiração de 60 s
    - _Requirements: 3.2, 9.2, 3.6, 10.1, 2.3, 2.4_

- [x] 14. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Implementar a camada de apresentação CLI
  - [x] 15.1 Implementar a renderização do Resultado_de_Analise
    - Agrupar por Aplicação e renderizar a linha do tempo; marcação visual distinta para a
      categoria de erro; exibir contagens; mensagem de falha de exibição preservando as entradas
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 15.2 Escrever teste de propriedade da completude dos atributos apresentados
    - **Property 16: Completude dos atributos apresentados por entrada**
    - **Validates: Requirements 9.1**

  - [x] 15.3 Escrever testes de exemplo da apresentação
    - Marcação visual distinta de erro (9.3) e mensagem de falha de exibição (9.5)
    - _Requirements: 9.3, 9.5_

- [x] 16. Conectar o ponto de entrada da aplicação
  - [x] 16.1 Implementar o entrypoint da CLI
    - Inicializar o registro via bootstrap, instanciar o `Analisador_de_Logs` e ligar a entrada
      do usuário à renderização do resultado
    - _Requirements: 6.1_

- [x] 17. Checkpoint final
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- As tarefas marcadas com `*` são opcionais (testes) e podem ser puladas para um MVP mais rápido.
- Cada tarefa referencia requisitos específicos para rastreabilidade.
- Cada uma das 16 propriedades de corretude é implementada por um único teste baseado em
  propriedade, com `@settings(max_examples=100)` e a tag `Feature: log-analyzer, Property {n}`.
- Os checkpoints garantem validação incremental.
- Metas de desempenho/UX (confirmação em ≤ 2 s, exibição de erro em ≤ 2 s) não são cobertas por
  testes automatizados de correção, conforme a estratégia de testes do design.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1", "5.1", "5.2", "5.3", "6.1", "8.1", "9.1", "9.3", "10.1", "10.3", "11.1", "12.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.4", "5.5", "5.6", "6.2", "7.1", "9.2", "9.4", "10.2", "10.4", "11.2", "12.2"] },
    { "id": 5, "tasks": ["7.2", "7.3", "13.1", "15.1"] },
    { "id": 6, "tasks": ["13.2", "13.3", "13.4", "15.2", "15.3", "16.1"] }
  ]
}
```
