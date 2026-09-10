# Implementation Plan: log-analyzer-phase-2

## Overview

Este plano implementa a Fase 2 sobre o projeto existente em **Python 3.11+**, preservando os
contratos públicos da Fase 1 em `log_analyzer/core`, os plugins em `log_analyzer/apps`, a CLI em
`log_analyzer/cli` e a suíte atual em `tests/`. A sequência começa por testes de caracterização,
acrescenta modelos e serviços puros, habilita o pipeline streaming somente para VPL/ORK e termina
com integração, segurança, regressão e desempenho. VOCI e plugins que implementam apenas os ABCs
atuais permanecem no fluxo legado.

Todos os dados de teste devem ser sintéticos ou usar placeholders tipados. Nenhuma tarefa pode
copiar, ler como fixture, versionar ou derivar constantes dos arquivos em `logs/`, de
`curation.db`, de relatórios locais ou de qualquer amostra bruta. Os 30 testes baseados em
propriedades ficam em arquivos próprios sob `tests/phase2/properties/`: cada propriedade do design
corresponde a exatamente uma função Hypothesis, contém o comentário
`Feature: log-analyzer-phase-2, Property N: <título>` e usa explicitamente
`@settings(max_examples=100)` ou valor maior.

## Tasks

- [x] 1. Congelar a compatibilidade da Fase 1 e preparar dados de teste seguros
  - [x] 1.1 Criar testes de caracterização dos contratos públicos existentes
    - Adicionar `tests/phase2/test_caracterizacao_contratos_fase1.py` cobrindo assinaturas e
      comportamento observável de `EntradaDeLog`, `ResultadoDeAnalise`, `Categoria`, exports de
      `log_analyzer.core` e wrappers `carregar_arquivo`, `filtrar_por_identificador`,
      `correlacionar_vpl_ork` e `ordenar_linha_do_tempo`.
    - Fixar construção posicional/por palavras-chave, defaults, nomes, tipos e semântica atuais
      antes de acrescentar campos; não alterar código de produção nesta folha.
    - _Requirements: 1.3, 1.4, 1.5, 16.1, 16.5_

  - [x] 1.2 Criar testes de caracterização dos plugins, formatos legados e CLI
    - Adicionar `tests/phase2/test_caracterizacao_fluxos_legados.py` para os formatos atuais de
      `VplParser`, `OrkParser` e `VociParser`, os ABCs, `Registro_de_Aplicacoes`, bootstrap com
      VPL/ORK/VOCI e sintaxe `python -m log_analyzer <id> <app>:<caminho>`.
    - Usar exclusivamente textos sintéticos e verificar que VOCI não recebe regra, parsing ou
      categoria de cenário específicos da Fase 2.
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 17.5_

  - [x] 1.3 Criar suporte comum para testes sintéticos da Fase 2
    - Criar `tests/phase2/strategies/` com builders Hypothesis para campos opacos, timestamps,
      blocos, grafos, catálogos e dados sensíveis gerados em tempo de teste, além de factories de
      arquivos temporários com LF/CRLF.
    - Fazer os builders emitirem somente placeholders tipados ou valores aleatórios sintéticos;
      impedir imports, cópias ou referências aos arquivos brutos locais.
    - Manter cada PBT futuro em arquivo próprio para assegurar um único teste por propriedade.
    - _Requirements: 4.3, 5.1, 14.5, 14.8, 15.4_

  - [x] 1.4 Executar e registrar a linha de base automatizada da Fase 1
    - Executar `python -m pytest -q tests` antes das mudanças de produção e corrigir somente os
      novos testes de caracterização caso representem incorretamente o comportamento existente.
    - Confirmar que a linha de base não consome `logs/`, `curation.db` nem serviços externos.
    - _Requirements: 1.2, 1.3, 1.4, 1.6_

- [x] 2. Acrescentar modelos, erros e contratos opcionais sem quebrar consumidores
  - [x] 2.1 Estender os modelos de domínio de forma estritamente aditiva
    - Acrescentar ao final de `EntradaDeLog` e `ResultadoDeAnalise`, com defaults compatíveis, os
      campos definidos no design; implementar em `log_analyzer/core/modelos.py` os enums e
      dataclasses de proveniência, campos, identificadores, falhas, vínculos, evidências,
      correlação, regra, causa-raiz, referência de texto e entrada indexada.
    - Preservar `Categoria`, a ordem dos campos existentes, `EntradaDeLog(frozen=True)` e todas as
      construções válidas da Fase 1; validar INV-1 a INV-12 sem exigir metadados novos de objetos
      legados.
    - _Requirements: 1.4, 1.5, 5.1, 5.2, 5.3, 6.8, 7.1, 8.1, 13.1, 16.1, 16.2_

  - [x] 2.2 Estender a hierarquia de erros com detalhes seguros
    - Adicionar em `log_analyzer/core/excecoes.py` erros de decodificação, tempo, catálogo,
      sanitização e integridade da fonte, mantendo `ErroDoAnalisador`, `ErroDeRegistro`,
      `ErroDeArquivo` e `ErroDeIdentificador` compatíveis.
    - Estruturar contexto por código, token de arquivo e posição; proibir interpolação de caminho,
      bytes, identificador ou texto bruto nas mensagens seguras.
    - _Requirements: 6.7, 14.7, 15.1, 15.4, 16.6_

  - [x] 2.3 Adicionar o protocolo opcional de parsing por bloco
    - Manter exatamente os três membros abstratos atuais de `Parser_de_Aplicacao` em
      `log_analyzer/core/interfaces.py` e adicionar `TipoInicio` e o protocolo runtime-checkable
      `Parser_de_Bloco` sem torná-lo requisito do registro.
    - Garantir que `interpretar_arquivo` continue disponível e que plugins line-based não precisem
      implementar nenhum método novo.
    - _Requirements: 1.2, 1.6, 4.1, 4.2, 4.4_

  - [x] 2.4 Atualizar exports e serialização compatível dos contratos aditivos
    - Atualizar `log_analyzer/core/__init__.py` somente com exports aditivos e criar helpers de
      serialização que aceitem objetos antigos e novos sem reinterpretar campos existentes.
    - Verificar que valores do enum `Categoria`, IDs de aplicação e imports públicos da Fase 1 não
      mudam.
    - _Requirements: 1.3, 1.4, 1.5, 16.1, 16.2, 16.3_

  - [x] 2.5 Escrever testes unitários dos modelos, erros e protocolo opcional
    - Criar `tests/phase2/test_modelos_contratos_aditivos.py` para defaults independentes,
      imutabilidade, invariantes, datetime UTC aware, serialização e construção legada.
    - Testar mensagens de erro sem dados brutos e registro/resolução de um plugin mínimo que não
      implementa `Parser_de_Bloco`.
    - _Requirements: 1.4, 1.5, 1.6, 5.1, 6.8, 14.7, 16.2_

  - [x] 2.6 Escrever o único PBT da Property 29 — Plugins legados permanecem válidos
    - Criar `tests/phase2/properties/test_property_29_plugins_legados.py` com uma única função
      Hypothesis que gere plugins implementando somente os ABCs da Fase 1 e verifique registro,
      resolução e seleção do fluxo line-based sem alterar registros existentes.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 29: Plugins legados permanecem válidos`
      e `@settings(max_examples=100)`.
    - _Requirements: 1.2, 1.6_

- [x] 3. Implementar leitura streaming, índice temporário seguro e segundo passe
  - [x] 3.1 Implementar preflight e leitura binária incremental
    - Criar `log_analyzer/core/streaming.py` com `LeitorStreaming` e `LinhaFisica`, preservando
      offsets, linhas 1-based, LF/CRLF/EOF, fingerprint e UTF-8 estrito sem substituição silenciosa.
    - Validar arquivo regular, legível, não vazio, limite de 500 MB e lote de até 100; representar
      fontes por tokens locais nas falhas.
    - Manter `carregar_arquivo` em `log_analyzer/core/carregador.py` como adapter legado com o tipo
      de retorno atual, sem usá-lo no caminho principal VPL/ORK.
    - _Requirements: 1.3, 4.3, 5.3, 15.4, 15.6, 15.8_

  - [x] 3.2 Implementar o índice temporário sem conteúdo reversível
    - Criar `log_analyzer/core/indice.py` com backend em memória e spill para SQLite temporário,
      armazenando apenas tokens, posições, timestamps, códigos, arestas e HMAC-SHA-256 por
      namespace com chave aleatória da análise.
    - Aplicar permissões restritas, transações em lote, limiar configurável e remoção em `finally`;
      impedir armazenamento de texto, caminhos e valores originais.
    - _Requirements: 5.1, 7.1, 7.6, 14.1, 15.8_

  - [x] 3.3 Implementar materialização seletiva e verificação de integridade da fonte
    - Criar `log_analyzer/core/materializacao.py` para reler somente intervalos selecionados,
      validar identidade, tamanho, `mtime_ns` e SHA-256 do bloco e reconstruir exatamente bytes
      UTF-8 e terminadores.
    - Produzir falha `SOURCE_CHANGED` por arquivo alterado sem combinar versões ou expor conteúdo;
      preservar as demais fontes e garantir limpeza do índice em sucesso e exceção.
    - _Requirements: 5.1, 5.2, 5.3, 14.7, 15.1, 15.4, 15.6_

  - [x] 3.4 Escrever testes unitários de streaming, índice e materialização
    - Criar `tests/phase2/test_streaming_indice_materializacao.py` cobrindo limites 0/1/100/101
      arquivos, 500 MB/500 MB+1 por doubles seguros, offsets multibyte, LF/CRLF, UTF-8 inválido,
      spill, permissões, limpeza e alteração entre passes.
    - Inspecionar o SQLite temporário nos testes e comprovar ausência de texto, caminho e valores
      originais gerados.
    - _Requirements: 4.3, 5.3, 14.7, 15.4, 15.6, 15.8_

- [x] 4. Implementar agrupamento multiline determinístico e preservação lossless
  - [x] 4.1 Implementar a máquina de estados de blocos
    - Criar `log_analyzer/core/multiline.py` com estados `SEM_BLOCO`/`BLOCO_ABERTO` e tratamento
      distinto de `CABECALHO_VALIDO`, `CABECALHO_APARENTE_INVALIDO` e `CONTINUACAO`.
    - Emitir intervalos contíguos, disjuntos e completos; fazer continuação órfã virar entrada não
      interpretada, fechar o bloco anterior em novo cabeçalho e finalizar uma vez no EOF.
    - Integrar o protocolo opcional sem alterar `agrupar_por_aplicacao` da Fase 1.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.2 Escrever testes unitários de todas as transições multiline
    - Criar `tests/phase2/test_multiline.py` com detectores sintéticos para cada transição,
      cabeçalho aparente inválido, continuação inicial, bloco sem newline final, linha
      indecodificável, repetições e EOF vazio.
    - Verificar posições, hashes, terminadores, ordem e que nenhuma linha seja anexada por tempo ou
      conteúdo semântico.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 15.7_

  - [x] 4.3 Escrever o único PBT da Property 5 — Partição determinística de linhas em blocos
    - Criar `tests/phase2/properties/test_property_05_particao_multiline.py` com uma única função
      que gere sequências trivalentes e compare a máquina com um modelo simples de partição.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 5: Partição determinística de linhas em blocos`
      e `@settings(max_examples=100)`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.4 Escrever o único PBT da Property 6 — Preservação integral e multiplicidade
    - Criar `tests/phase2/properties/test_property_06_preservacao_integral.py` com uma única função
      que gere blocos Unicode, terminadores e duplicatas, percorra parsing/metadados/materialização
      e compare a concatenação e as posições à fonte original.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 6: Preservação integral e multiplicidade`
      e `@settings(max_examples=100)`.
    - _Requirements: 4.3, 5.1, 5.2, 5.3, 7.6, 15.7_

- [x] 5. Implementar normalização temporal e identificadores tipados
  - [x] 5.1 Implementar normalização temporal por perfil
    - Criar `log_analyzer/core/temporal.py` com `NormalizadorTemporal`: VPL usa
      `ZoneInfo("America/Sao_Paulo")`, valida round-trip dos folds e rejeita horários inexistentes
      ou ambíguos; ORK respeita offset explícito e converte para UTC.
    - Preservar timestamp original e precisão de 0 a 6 dígitos; registrar falha em vez de truncar
      ou escolher silenciosamente.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.7, 6.8_

  - [x] 5.2 Estender a composição da linha do tempo sem quebrar o wrapper legado
    - Atualizar `log_analyzer/core/ordenacao.py` com uma partição Fase 2: UTC válido em ordem
      `(timestamp_normalizado, aplicacao, ordem_de_leitura)` e entradas sem UTC em coleção
      separada e estável.
    - Preservar `ordenar_linha_do_tempo` para listas legadas e o comportamento caracterizado da
      Fase 1.
    - _Requirements: 1.4, 6.5, 6.6, 6.7, 15.5, 16.1_

  - [x] 5.3 Implementar normalização, namespace e proveniência de identificadores
    - Criar `log_analyzer/core/identificadores.py` com `NormalizadorDeIdentificador`, validação de
      UUID apenas em contexto tipado, `casefold`, remoção exclusiva de delimitadores externos
      aprovados e associação de namespace de comparação.
    - Preservar tipo, nome do campo, valor original, valor normalizado, span, entrada, arquivo e
      versão da regra; não aproximar, concatenar ou inferir identificadores.
    - _Requirements: 2.2, 2.3, 2.4, 3.2, 3.3, 7.1, 7.6, 8.2_

  - [x] 5.4 Escrever testes unitários de tempo e identificadores
    - Criar `tests/phase2/test_temporal_identificadores.py` para offsets, UTC, precisão, datas de
      transição da zona, timestamps legados sem offset, delimitadores, casing, UUID contextual e
      colisões entre namespaces.
    - Usar somente identificadores e UUIDs gerados em tempo de teste.
    - _Requirements: 6.1, 6.2, 6.3, 6.7, 6.8, 7.1, 7.6, 8.2_

  - [x] 5.5 Escrever o único PBT da Property 9 — Normalização temporal preserva instante e precisão
    - Criar `tests/phase2/properties/test_property_09_normalizacao_temporal.py` com uma única função
      para datetimes locais resolvíveis e datetimes aware com offsets, comparando o instante UTC e
      a precisão à referência da biblioteca padrão.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 9: Normalização temporal preserva o instante e a precisão`
      e `@settings(max_examples=100)`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.8_

  - [x] 5.6 Escrever o único PBT da Property 10 — Linha do tempo é partição total e determinística
    - Criar `tests/phase2/properties/test_property_10_linha_do_tempo.py` com uma única função que
      gere entradas com/sem UTC, verifique união disjunta, multiplicidade e chave total de ordem.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 10: Linha do tempo é uma partição total e determinística`
      e `@settings(max_examples=100)`.
    - _Requirements: 6.5, 6.6, 6.7, 15.5_

  - [x] 5.7 Escrever o único PBT da Property 11 — Normalização de identificador é auditável e não colide semanticamente
    - Criar `tests/phase2/properties/test_property_11_normalizacao_identificador.py` com uma única
      função que gere campos conhecidos e confirme transformação permitida, preservação do valor e
      separação de nós por tipo/namespace.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 11: Normalização de identificador é auditável e não colide semanticamente`
      e `@settings(max_examples=100)`.
    - _Requirements: 7.1, 7.6, 8.2_

- [x] 6. Evoluir os parsers VPL e ORK com perfis reais e legados
  - [x] 6.1 Implementar o perfil real de VPL antes do perfil legado
    - Evoluir `log_analyzer/apps/vpl.py` com detecção trivalente e parsing staged do UUID opcional,
      timestamp local, percentual, severidade delimitada, origem e mensagem, sem regex monolítica.
    - Implementar `Parser_de_Bloco`, extração apenas de posições/campos VPL aprovados, Unicode,
      conteúdo multiline e pretty-printer canônico; manter o formato sintético atual como fallback
      e registrar `formato_origem`.
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 5.4_

  - [x] 6.2 Implementar o perfil real de ORK antes do perfil legado
    - Evoluir `log_analyzer/apps/ork.py` com parsing staged de timestamp ISO com offset, host,
      processo/PID, severidade, logger e mensagem; linha com prefixo aparente inválido inicia bloco
      não interpretado próprio.
    - Implementar `Parser_de_Bloco`, extração somente de `TelecomCallId`, `CallId` e UUID de sessão
      rotulado, Unicode, multiline e pretty-printer; manter pipe-delimited atual como perfil legado.
    - _Requirements: 1.1, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 5.5_

  - [x] 6.3 Escrever testes unitários dos perfis VPL reais e legados
    - Criar `tests/phase2/test_vpl_parser_real.py` para todos os campos, precisão, Unicode,
      multiline, campos/posições de identificador, UUID incidental ignorado, mutações inválidas e
      compatibilidade com `tests/test_vpl_parser.py`.
    - Usar somente builders sintéticos da Fase 2.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.4_

  - [x] 6.4 Escrever testes unitários dos perfis ORK reais e legados
    - Criar `tests/phase2/test_ork_parser_real.py` para offset obrigatório no perfil real, host,
      processo/PID, logger, Unicode, multiline, campos conhecidos, UUID incidental ignorado,
      mutações inválidas e compatibilidade com `tests/test_ork_parser.py`.
    - Usar somente builders sintéticos da Fase 2.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 5.5_

  - [x] 6.5 Escrever o único PBT da Property 1 — Parsing VPL completo e tipado
    - Criar `tests/phase2/properties/test_property_01_parsing_vpl.py` com uma única função que gere
      a gramática VPL real e compare todos os campos, Unicode e identificadores contextuais ao
      modelo gerado.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 1: Parsing VPL completo e tipado`
      e `@settings(max_examples=100)`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 7.1_

  - [x] 6.6 Escrever o único PBT da Property 2 — Parsing VPL inválido falha sem perda
    - Criar `tests/phase2/properties/test_property_02_vpl_invalido.py` com uma única função que
      invalide um campo obrigatório por vez, preserve bloco/posições e comprove que entradas
      sintéticas subsequentes VPL/ORK ainda são processadas.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 2: Parsing VPL inválido falha sem perda`
      e `@settings(max_examples=100)`.
    - _Requirements: 2.5, 5.1, 5.2, 5.3, 15.1, 15.2_

  - [x] 6.7 Escrever o único PBT da Property 3 — Parsing ORK completo e tipado
    - Criar `tests/phase2/properties/test_property_03_parsing_ork.py` com uma única função que gere
      a gramática ORK real e compare timestamp/offset, host, processo, severidade, logger, mensagem
      e somente os identificadores explicitamente rotulados.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 3: Parsing ORK completo e tipado`
      e `@settings(max_examples=100)`.
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 7.1_

  - [x] 6.8 Escrever o único PBT da Property 4 — Parsing ORK inválido falha sem perda
    - Criar `tests/phase2/properties/test_property_04_ork_invalido.py` com uma única função que
      invalide um campo obrigatório por vez, preserve bloco/posições e comprove continuação das
      demais entradas ORK/VPL.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 4: Parsing ORK inválido falha sem perda`
      e `@settings(max_examples=100)`.
    - _Requirements: 3.4, 5.1, 5.2, 5.3, 15.1, 15.3_

  - [x] 6.9 Escrever o único PBT da Property 7 — Round-trip VPL
    - Criar `tests/phase2/properties/test_property_07_roundtrip_vpl.py` com uma única função
      `parse(print(parse(x)))` para entradas reais/legadas interpretadas, comparando todos os
      campos e identificadores estruturados.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 7: Round-trip VPL` e
      `@settings(max_examples=100)`.
    - _Requirements: 5.4_

  - [x] 6.10 Escrever o único PBT da Property 8 — Round-trip ORK
    - Criar `tests/phase2/properties/test_property_08_roundtrip_ork.py` com uma única função
      `parse(print(parse(x)))` para entradas reais/legadas interpretadas, comparando todos os
      campos e identificadores estruturados.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 8: Round-trip ORK` e
      `@settings(max_examples=100)`.
    - _Requirements: 5.5_

- [x] 7. Implementar esquemas explícitos e grafo de vínculos
  - [x] 7.1 Implementar registro de esquemas e grafo determinístico
    - Criar `log_analyzer/core/vinculos.py` com `EsquemaDeVinculo`, registro versionado,
      cardinalidades, `GrafoDeVinculos`, BFS determinística, caminhos evidenciados e marcação de
      componente ambíguo.
    - Criar arestas somente quando um esquema aprovado reconhece uma declaração semântica; não
      codificar esquemas concretos a partir das amostras nem usar coexistência, tempo, ordem ou
      similaridade.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 7.2 Escrever testes unitários do grafo e dos esquemas
    - Criar `tests/phase2/test_vinculos.py` com esquemas exclusivamente sintéticos para arestas,
      ciclos, componentes desconectados, cardinalidade, ambiguidade, ordem da BFS e evidência por
      passo.
    - Verificar explicitamente que mera coexistência, proximidade, adjacência e similaridade não
      criam vínculo.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 13.4_

  - [x] 7.3 Escrever o único PBT da Property 14 — Ausência de declaração semântica implica ausência de vínculo
    - Criar `tests/phase2/properties/test_property_14_sem_vinculo_implicito.py` com uma única função
      que varie tempo, ordem e semelhança em entradas sem esquema correspondente e confirme grafo
      vazio/invariante.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 14: Ausência de declaração semântica implica ausência de vínculo`
      e `@settings(max_examples=100)`.
    - _Requirements: 8.4, 8.5_

  - [x] 7.4 Escrever o único PBT da Property 15 — Fechamento por vínculos equivale à alcançabilidade evidenciada
    - Criar `tests/phase2/properties/test_property_15_fechamento_vinculos.py` com uma única função
      que gere grafos sintéticos e compare BFS, nós, arestas e evidências a um modelo de referência.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 15: Fechamento por vínculos equivale à alcançabilidade evidenciada`
      e `@settings(max_examples=100)`.
    - _Requirements: 8.1, 8.2, 8.3, 13.4_

  - [x] 7.5 Escrever o único PBT da Property 16 — Ambiguidade é isolada e não classifica
    - Criar `tests/phase2/properties/test_property_16_ambiguidade.py` com uma única função que gere
      violações de cardinalidade e confirme isolamento da expansão/classificação e explicação
      segura.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 16: Ambiguidade é isolada e não classifica`
      e `@settings(max_examples=100)`.
    - _Requirements: 8.6_

- [x] 8. Implementar busca estruturada, fallback literal e preservação de estado
  - [x] 8.1 Implementar o buscador de cenário e manter o filtro legado
    - Criar `log_analyzer/core/busca.py` com igualdade por HMAC/namespace em campos conhecidos,
      fallback literal case-insensitive somente quando a entrada não teve igualdade estruturada,
      deduplicação por `entrada_id` e expansão por vínculos autorizados não ambíguos.
    - Validar consulta antes de alterar seleção/índice; registrar motivo e caminho de inclusão.
    - Manter `filtrar_por_identificador` em `log_analyzer/core/filtro.py` com o comportamento da
      Fase 1 para entradas sem metadados novos.
    - _Requirements: 1.4, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.3_

  - [x] 8.2 Escrever testes unitários de busca e compatibilidade do filtro
    - Criar `tests/phase2/test_busca.py` para match estruturado, fallback em continuação, match
      duplo sem duplicata, casing, substring parcial, expansão evidenciada e rejeição atômica de
      consultas vazias/whitespace/>256.
    - Reexecutar os casos legados de `tests/test_filtro.py` contra o wrapper público.
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.3_

  - [x] 8.3 Escrever o único PBT da Property 12 — Busca estruturada e fallback são corretos, completos e sem duplicatas
    - Criar `tests/phase2/properties/test_property_12_busca.py` com uma única função que gere
      entradas e consultas e compare exatamente o conjunto ordenado de sementes a um modelo
      ingênuo da semântica aprovada.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 12: Busca estruturada e fallback são corretos, completos e sem duplicatas`
      e `@settings(max_examples=100)`.
    - _Requirements: 7.2, 7.3, 7.4, 7.5_

  - [x] 8.4 Escrever o único PBT da Property 13 — Consulta inválida preserva o estado
    - Criar `tests/phase2/properties/test_property_13_consulta_invalida.py` com uma única função que
      gere consultas inválidas e compare snapshots equivalentes de resultado, seleção e índice
      antes/depois.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 13: Consulta inválida preserva o estado`
      e `@settings(max_examples=100)`.
    - _Requirements: 7.7_

- [x] 9. Implementar correlação evidenciada e explicabilidade
  - [x] 9.1 Implementar o correlacionador VPL–ORK com adapter legado
    - Evoluir `log_analyzer/core/correlacao.py` com `CorrelacionadorVplOrk`, bases
      `VALOR_COMPARTILHADO`, `CADEIA_DE_VINCULOS`, `NENHUMA` e `AMBIGUA`, evidências e marcação
      somente das entradas cobertas.
    - Aceitar apenas namespaces compatíveis ou caminho explícito não ambíguo; preservar lados
      separados e lacuna quando não houver evidência.
    - Manter `correlacionar_vpl_ork` compatível para entradas legadas que compartilham literalmente
      a consulta, sem aplicar essa presunção ao pipeline novo.
    - _Requirements: 1.4, 9.1, 9.2, 9.4, 9.5, 9.6, 9.7_

  - [x] 9.2 Implementar composição rastreável de evidências e explicações
    - Criar `log_analyzer/core/explicabilidade.py` para construir evidências com aplicação,
      posição, timestamps, campo/condição, regra de extração/vínculo e representação destinada à
      sanitização.
    - Representar separadamente severidade, categoria por entrada, categoria de cenário e
      causa-raiz; produzir mensagens estruturadas para não correspondência e causa não determinada.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 17.4_

  - [x] 9.3 Escrever testes unitários de correlação e explicabilidade
    - Criar `tests/phase2/test_correlacao_explicabilidade.py` para valor compartilhado, cadeia,
      ambas as bases, nenhuma base, ambiguidade, lado ausente, caminhos e campos obrigatórios das
      evidências.
    - Comparar também o wrapper com os casos caracterizados da Fase 1.
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.6, 9.7, 13.3, 13.4_

  - [x] 9.4 Escrever o único PBT da Property 17 — Correlação VPL–ORK existe se e somente se há evidência válida
    - Criar `tests/phase2/properties/test_property_17_correlacao.py` com uma única função que gere
      coleções e grafos e compare entradas marcadas, base e evidências à relação formal esperada.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 17: Correlação VPL–ORK existe se e somente se há evidência válida`
      e `@settings(max_examples=100)`.
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.6_

  - [x] 9.5 Escrever o único PBT da Property 24 — Explicação é completa e vinculada à decisão
    - Criar `tests/phase2/properties/test_property_24_explicacao.py` com uma única função que gere
      resultados classificados/não classificados e verifique completude, rastreabilidade e
      separação semântica sem campos causais inventados.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 24: Explicação é completa e vinculada à decisão`
      e `@settings(max_examples=100)`.
    - _Requirements: 13.1, 13.2, 13.3, 13.5, 13.6, 13.7_

- [x] 10. Implementar sanitização fail-closed e governança automatizada de fixtures
  - [x] 10.1 Implementar contexto, placeholders e detectores de sanitização
    - Criar `log_analyzer/core/sanitizacao.py` com `SanitizationContext`, mapeamento determinístico
      por `(tipo, valor_normalizado)`, placeholders tipados, substituição longest-match e detectores
      defensivos para as classes sensíveis do design.
    - Sanitizar campos estruturados antes do texto livre e preservar nomes, cardinalidade, ordem e
      relações; descartar o mapa bruto ao fim da análise.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 16.4_

  - [x] 10.2 Implementar visão segura e supressão atômica em falhas
    - Criar `log_analyzer/core/visao_segura.py` para copiar/sanitizar `ResultadoDeAnalise`, executar
      scanner final independente e somente então marcar `EstadoSanitizacao.CONCLUIDA`.
    - Em qualquer falha, retornar exclusivamente código/mensagem constante, preservar o objeto
      interno e impedir resultado parcialmente sanitizado em CLI, exportação ou diagnóstico.
    - _Requirements: 14.1, 14.7, 16.4, 16.6_

  - [x] 10.3 Implementar scanner e política executável de fixtures
    - Criar `log_analyzer/core/governanca.py` para validar placeholders, manifesto, digest,
      sanitizador, rótulo/data/aprovador declarativos e ausência de classes sensíveis; diagnósticos
      informam somente arquivo/linha e tipo.
    - Restringir a varredura aos artefatos versionáveis e rejeitar referência/cópia de `logs/`,
      `curation.db`, dashboard ou relatórios brutos.
    - _Requirements: 14.5, 14.6, 14.8_

  - [x] 10.4 Criar a fixture sanitizada de estrutura do candidato dourado
    - Criar `tests/fixtures/log_analyzer_phase2/golden_candidate/` com VPL/ORK mínimos formados
      manualmente por placeholders como `<CALL_ID_1>` e identificadores tipados, mais manifesto e
      digests; não transportar texto, formato incidental ou valor de amostra real.
    - Marcar o artefato como candidato estrutural sem predicados de classificação e sem regra ativa;
      fazê-lo passar pelo scanner de governança.
    - _Requirements: 9.3, 11.6, 14.4, 14.5, 14.8_

  - [x] 10.5 Escrever testes unitários e de segurança da sanitização/governança
    - Criar `tests/phase2/test_sanitizacao_governanca.py` para repetição consistente, tipos
      distintos, sobreposição longest-match, scanner final, falhas injetadas e rejeição sem eco.
    - Gerar padrões sensíveis somente em memória e confirmar ausência em stdout, stderr, exceções,
      logs capturados e artefatos aceitos.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8_

  - [x] 10.6 Escrever o único PBT da Property 25 — Sanitização é consistente, tipada e preserva estrutura
    - Criar `tests/phase2/properties/test_property_25_sanitizacao.py` com uma única função que gere
      resultados sensíveis sintéticos e compare ausência dos originais, consistência por tipo e
      invariantes estruturais.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 25: Sanitização é consistente, tipada e preserva estrutura`
      e `@settings(max_examples=100)`.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 16.4_

  - [x] 10.7 Escrever o único PBT da Property 26 — Falha de sanitização não vaza conteúdo
    - Criar `tests/phase2/properties/test_property_26_falha_sanitizacao.py` com uma única função que
      injete falha em cada etapa e verifique mensagem constante, ausência de fragmentos e
      preservação do resultado interno.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 26: Falha de sanitização não vaza conteúdo`
      e `@settings(max_examples=100)`.
    - _Requirements: 14.7, 16.6_

  - [x] 10.8 Escrever o único PBT da Property 27 — Scanner de fixtures rejeita dados brutos sem eco
    - Criar `tests/phase2/properties/test_property_27_scanner_fixtures.py` com uma única função que
      insira valores sensíveis gerados em fixtures temporárias e confirme rejeição, tipo/local
      seguro e ausência do valor no diagnóstico.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 27: Scanner de fixtures rejeita dados brutos sem eco`
      e `@settings(max_examples=100)`.
    - _Requirements: 14.5, 14.6, 14.8_

- [x] 11. Implementar catálogo JSON, DSL restrita e classificador fail-closed
  - [x] 11.1 Implementar modelos e carregamento atômico do catálogo
    - Criar `log_analyzer/core/catalogo.py` para ler JSON versionado e construir modelos imutáveis
      de regras, fixtures, cobertura, aprovação declarativa, precedência e estados.
    - Validar schema, tipos, IDs, versões, digests e referências sem `eval`, import, templates,
      SQL ou execução de conteúdo; erro mantém o catálogo anterior ou nenhum catálogo ativo.
    - _Requirements: 10.1, 10.2, 12.1, 12.4, 12.5, 17.2, 17.3_

  - [x] 11.2 Implementar a DSL totalizada de predicados tipados
    - Criar `log_analyzer/core/dsl_regras.py` com operadores fechados para presença de aplicação,
      campo, vínculo, fato, cardinalidade e ordem temporal, retornando resultado total sem regex
      arbitrária nem código fornecido pelo catálogo.
    - Avaliar fatos estruturados, nunca texto livre, e produzir referências às condições/evidências
      satisfeitas.
    - _Requirements: 10.1, 10.2, 10.3, 13.2, 17.6_

  - [x] 11.3 Implementar gates, precedência e histórico append-only
    - Criar `log_analyzer/core/validacao_catalogo.py` para exigir cobertura de todas as condições,
      fixture sanitizada, política de amostras/diversidade, avaliação dos exemplos, aprovação
      declarativa completa e precedência sem conflito antes de `ACTIVE`.
    - Rejeitar atualização parcial atomicamente, criar versão nova para alteração e preservar
      conteúdo/digest histórico; bloquear regras `ERRO`/causa-raiz sem exemplo rotulado de erro.
    - _Requirements: 10.1, 10.2, 10.6, 12.2, 12.3, 12.5, 12.6, 12.7_

  - [x] 11.4 Implementar o classificador de cenário fail-closed
    - Criar `log_analyzer/core/classificacao.py` com `ClassificadorDeCenario`: considerar somente
      regras `ACTIVE`, exigir todos os predicados, aplicar precedência versionada e devolver regra,
      condições e evidências; qualquer erro/ambiguidade/partial match resulta em
      `NAO_CLASSIFICADA`.
    - Manter severidade independente e causa-raiz como “não determinada” sem regra causal ativa.
    - _Requirements: 10.3, 10.4, 10.5, 10.6, 11.2, 11.5, 13.1, 13.2, 13.5, 13.7, 17.4, 17.6_

  - [x] 11.5 Criar o catálogo distribuído inicial sem ativar regra real
    - Criar `log_analyzer/catalogos/fase2.json` e configuração de package data em `pyproject.toml`
      com versão, cobertura “1 sucesso; 0 erros”, lacunas e referência ao candidato estrutural,
      mas nenhuma regra `ACTIVE`, nenhuma regra `ERRO` e nenhuma causa-raiz.
    - Não definir condições necessárias/suficientes do Cenário_Dourado; carregamento padrão deve
      produzir `NAO_CLASSIFICADA` até artefatos externos válidos existirem.
    - _Requirements: 10.3, 10.5, 11.6, 12.1, 12.3, 17.2, 17.3, 17.4_

  - [x] 11.6 Escrever testes unitários e de integração do catálogo/DSL/classificador
    - Criar `tests/phase2/test_catalogo_classificacao.py` com catálogos sintéticos temporários para
      schema, operadores, gates, estados, digests, precedência, histórico, carga atômica, regra
      candidata e ausência de regras de erro/causa-raiz.
    - Confirmar que o catálogo distribuído e a fixture candidata permanecem fail-closed.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.5, 12.2, 12.3, 12.5, 12.6, 12.7_

  - [x] 11.7 Escrever o único PBT da Property 19 — Somente regras completas, apoiadas e aprovadas podem ser ativadas
    - Criar `tests/phase2/properties/test_property_19_gates_catalogo.py` com uma única função que
      gere manifestos sintéticos completos/incompletos e verifique a equivalência entre todos os
      gates e ativação, preservando o catálogo anterior em falhas.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 19: Somente regras completas, apoiadas e aprovadas podem ser ativadas`
      e `@settings(max_examples=100)`.
    - _Requirements: 10.1, 10.2, 12.2, 12.4, 12.6, 12.7_

  - [x] 11.8 Escrever o único PBT da Property 20 — Histórico do catálogo é append-only
    - Criar `tests/phase2/properties/test_property_20_historico_catalogo.py` com uma única função
      que gere sequências de alterações e confirme nova versão, imutabilidade e digest histórico.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 20: Histórico do catálogo é append-only`
      e `@settings(max_examples=100)`.
    - _Requirements: 12.5_

  - [x] 11.9 Escrever o único PBT da Property 21 — Classificação é sound e fail-closed
    - Criar `tests/phase2/properties/test_property_21_classificacao_fail_closed.py` com uma única
      função que gere cenários/regras sintéticos e confirme que somente match integral de regra
      ativa classifica, independentemente de severidade, candidato ou condição parcial.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 21: Classificação é sound e fail-closed`
      e `@settings(max_examples=100)`.
    - _Requirements: 10.3, 10.4, 10.5, 13.1, 17.4, 17.6_

  - [x] 11.10 Escrever o único PBT da Property 22 — Precedência versionada é determinística
    - Criar `tests/phase2/properties/test_property_22_precedencia.py` com uma única função que gere
      regras ativas sobrepostas com precedência válida e permute a ordem física do JSON.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 22: Precedência versionada é determinística`
      e `@settings(max_examples=100)`.
    - _Requirements: 10.6_

  - [x] 11.11 Escrever o único PBT da Property 23 — Near-miss da regra dourada não generaliza
    - Criar `tests/phase2/properties/test_property_23_near_miss.py` com uma única função que monte
      **em memória** uma regra de teste sintética com conjunto gerado de condições, remova cada
      condição e espere `NAO_CLASSIFICADA`; não persistir nem tratar essas condições como a regra
      real do Cenário_Dourado.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 23: Near-miss da regra dourada não generaliza`
      e `@settings(max_examples=100)`.
    - _Requirements: 11.5_

- [x] 12. Integrar o pipeline da Fase 2 ao orquestrador preservando VOCI
  - [x] 12.1 Implementar o pipeline streaming VPL/ORK
    - Criar `log_analyzer/core/pipeline_fase2.py` para conectar preflight, leitura, multiline,
      parsing, índice/grafo, busca, materialização, tempo, correlação, classificação e sanitização,
      com recursos fechados em `finally`.
    - Isolar falhas por entrada/arquivo, manter resultados parciais e evitar materialização global;
      não importar implementações concretas no núcleo além da resolução pelo registro/protocolo.
    - _Requirements: 1.1, 4.1, 5.1, 7.2, 8.3, 9.4, 10.3, 14.7, 15.1, 15.2, 15.3, 15.6, 15.8_

  - [x] 12.2 Roteirizar a fachada preservada entre fluxos Fase 2 e legado
    - Atualizar `log_analyzer/core/analisador.py` sem mudar `Analisador_de_Logs.analisar`: VPL/ORK
      usam o pipeline novo e VOCI/plugins sem `Parser_de_Bloco` usam o fluxo atual.
    - Preservar validação do identificador, reassociação, acumulação de erros, registro e retorno
      `ResultadoDeAnalise`; remover presunções de correlação apenas do caminho novo.
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 7.7, 9.6, 9.7, 15.1, 16.1_

  - [x] 12.3 Implementar a composição aditiva do resultado da Fase 2
    - Criar `log_analyzer/core/composicao.py` para preencher agrupamentos/contagens legados,
      timeline e coleção sem UTC, categoria de cenário, IDs, vínculos, correlação, evidências,
      regra, versão, sanitização, causa-raiz, aplicações analisadas/ausentes e cobertura.
    - Garantir união exata das entradas selecionadas e manter categoria por entrada/severidade
      independentes da categoria de cenário.
    - _Requirements: 6.5, 6.7, 9.4, 13.6, 16.1, 16.2, 16.3, 17.1, 17.2, 17.3_

  - [x] 12.4 Escrever testes de integração do orquestrador e dos adapters públicos
    - Criar `tests/phase2/test_pipeline_orquestrador.py` com arquivos temporários sintéticos,
      VPL/ORK válidos e inválidos, lado ausente, consulta inválida, mudança de fonte, spill e
      limpeza; verificar também VOCI no fluxo legado e wrappers públicos.
    - Confirmar limites de 100 arquivos/500 MB por doubles controlados e uma falha por fonte
      inválida sem abortar fontes válidas.
    - _Requirements: 1.2, 1.3, 1.4, 1.6, 9.7, 15.1, 15.2, 15.3, 15.5, 15.6, 15.8, 16.1, 17.1_

  - [x] 12.5 Escrever o único PBT da Property 18 — Falhas parciais preservam o lado disponível e a cobertura
    - Criar `tests/phase2/properties/test_property_18_falhas_parciais.py` com uma única função que
      gere combinações VPL/ORK válidas, ausentes e inválidas e verifique entradas, uma falha por
      fonte e partição de aplicações.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 18: Falhas parciais preservam o lado disponível e a cobertura`
      e `@settings(max_examples=100)`.
    - _Requirements: 9.7, 15.6, 17.1_

  - [x] 12.6 Escrever o único PBT da Property 28 — Robustez do lote preserva válidos, falhas e repetições
    - Criar `tests/phase2/properties/test_property_28_robustez_lote.py` com uma única função que
      gere lotes virtuais mistos e compare processamento, falhas isoladas, multiplicidade e ordem
      a um modelo sequencial.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 28: Robustez do lote preserva válidos, falhas e repetições`
      e `@settings(max_examples=100)`.
    - _Requirements: 15.1, 15.2, 15.3, 15.6, 15.7_

  - [x] 12.7 Escrever o único PBT da Property 30 — Análise repetida é determinística
    - Criar `tests/phase2/properties/test_property_30_determinismo.py` com uma única função que
      execute duas análises sobre seleção/configuração/catálogo sintéticos estáveis e compare
      categoria, ordem, correlação, regra, evidências, versão e placeholders canônicos.
    - Incluir o comentário `Feature: log-analyzer-phase-2, Property 30: Análise repetida é determinística`
      e `@settings(max_examples=100)`.
    - _Requirements: 16.5, 17.2_

- [x] 13. Evoluir CLI e observabilidade sem expor dados
  - [x] 13.1 Implementar renderer iterável e seguro
    - Evoluir `log_analyzer/cli/apresentacao.py` com iterador de linhas que consome somente a visão
      sanitizada e acrescenta categoria de cenário, catálogo/regra, cobertura, correlação,
      timeline UTC, entradas sem UTC, evidências e causa-raiz.
    - Manter `renderizar_resultado` como wrapper que junta o iterador; preservar seções, contagens e
      severidades da Fase 1 e suprimir toda saída em falha de sanitização/apresentação.
    - _Requirements: 13.1, 13.2, 13.3, 13.5, 13.6, 13.7, 16.1, 16.2, 16.3, 16.4, 16.6_

  - [x] 13.2 Preservar a sintaxe da CLI e conectar a saída sanitizada
    - Atualizar `log_analyzer/cli/main.py` mantendo argumentos posicionais, app IDs e códigos
      básicos; nunca ecoar consulta, caminho ou erro bruto em stdout/stderr.
    - Reter o `ResultadoDeAnalise` interno se o writer falhar e emitir somente mensagem segura.
    - _Requirements: 1.3, 14.1, 16.3, 16.4, 16.6_

  - [x] 13.3 Implementar observabilidade segura
    - Criar `log_analyzer/core/observabilidade.py` com métricas por contagem/duração/código e logs
      por `analysis_id`, token, app e posição; vedar labels de caminho, ID, UUID, telefone,
      documento, host, URL, mensagem e evidência.
    - Garantir que nível debug não habilite conteúdo bruto e que falhas registrem apenas códigos.
    - _Requirements: 13.3, 14.1, 14.7, 16.4_

  - [x] 13.4 Escrever testes unitários e de integração da CLI/observabilidade
    - Criar `tests/phase2/test_cli_observabilidade.py` para sintaxe antiga, seções aditivas,
      categoria versus severidade, iterator/wrapper, códigos de saída, labels permitidos e falha de
      writer com resultado preservado.
    - _Requirements: 1.3, 13.6, 16.1, 16.2, 16.3, 16.4, 16.6_

  - [x] 13.5 Escrever testes de não vazamento em todas as fronteiras
    - Criar `tests/phase2/test_seguranca_saidas.py` injetando dados sintéticos sensíveis e falhas em
      parser, catálogo, sanitizador, renderer e writer; inspecionar stdout, stderr, logging,
      exceções e JSON serializado.
    - Confirmar que somente placeholders/códigos seguros aparecem e que a apresentação nunca usa
      `texto_original` bruto diretamente.
    - _Requirements: 14.1, 14.2, 14.3, 14.7, 16.4, 16.6_

- [x] 14. Cobrir integração sanitizada, cenário candidato e comportamento golden genérico
  - [x] 14.1 Testar o candidato estrutural VPL–ORK de ponta a ponta em fail-closed
    - Criar `tests/phase2/test_integracao_candidato_dourado.py` usando somente a fixture de
      placeholders para verificar parsing real, multiline, normalização, busca por `<CALL_ID_1>`,
      correlação VPL–ORK, timeline e evidência sanitizada.
    - Como não há predicados/ativação reais, exigir `NAO_CLASSIFICADA`, regra ausente e causa-raiz
      não determinada; não enfraquecer o teste para inferir `SUCESSO`.
    - _Requirements: 9.3, 9.4, 9.5, 10.3, 10.5, 11.5, 13.5, 14.4, 17.3, 17.4_

  - [x] 14.2 Testar mecanicamente uma regra ativa exclusivamente sintética
    - Criar `tests/phase2/test_integracao_regra_sintetica.py` que monte em diretório temporário uma
      regra e fixture totalmente sintéticas, passe todos os gates e verifique categoria `SUCESSO`,
      regra/versão, evidência de ambas as apps e correlação.
    - Identificar a regra como artefato de teste genérico, não persistir seus predicados no catálogo
      distribuído e não afirmar equivalência com o Cenário_Dourado real.
    - _Requirements: 10.1, 10.2, 11.1, 11.2, 11.3, 11.4, 13.1, 13.2_

  - [x] 14.3 Testar integração com entradas malformadas e lados ausentes
    - Criar `tests/phase2/test_integracao_resultado_parcial.py` combinando blocos válidos,
      cabeçalhos aparentes inválidos, UTF-8 inválido, timestamp irresolvível, VPL-only e ORK-only;
      verificar preservação segura, coleções temporais e lacunas.
    - _Requirements: 6.7, 9.6, 9.7, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 17.1_

  - [x] 14.4 Testar declaração de cobertura e limites de diagnóstico
    - Criar `tests/phase2/test_cobertura_diagnostico.py` para versão do catálogo, apps analisadas e
      ausentes, “1 cenário de sucesso; 0 cenários de erro”, ausência de regra `ERRO`, causa-raiz
      não determinada e mensagem de VOCI fora do escopo quando solicitada regra nova.
    - _Requirements: 12.1, 12.3, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [x] 15. Completar regressão de VOCI, plugins legados e APIs da Fase 1
  - [x] 15.1 Escrever regressão dedicada do fluxo VOCI
    - Criar `tests/phase2/test_regressao_voci.py` comparando parsing, impressão, filtragem,
      classificação por entrada, agrupamento, contagens e CLI aos resultados caracterizados, sem
      catálogo, vínculos ou regras novas.
    - _Requirements: 1.2, 1.4, 17.5_

  - [x] 15.2 Escrever regressão de plugins de terceiros e registro
    - Criar `tests/phase2/test_regressao_plugins.py` com plugins mínimos line-based, registro
      dinâmico, resolução, análise e falhas atômicas; verificar que bootstrap continua exatamente
      VPL, ORK e VOCI.
    - _Requirements: 1.3, 1.6_

  - [x] 15.3 Escrever regressão de imports, wrappers, modelos e CLI
    - Criar `tests/phase2/test_regressao_api_publica.py` para `core.__all__`, construções antigas,
      serialização, wrappers de carga/filtro/correlação/ordem/renderização e todos os argumentos
      posicionais/códigos caracterizados.
    - _Requirements: 1.3, 1.4, 1.5, 16.1, 16.3_

  - [x] 15.4 Adicionar guarda automatizada contra uso de fontes brutas locais
    - Criar `tests/phase2/test_higiene_fixtures.py` para varrer código de fixtures, catálogos e
      testes da Fase 2 e falhar diante de referência/import/cópia de `logs/`, `curation.db`,
      relatórios ou dashboard como fonte de regra.
    - Permitir somente os artefatos sintéticos/sanitizados explicitamente governados em
      `tests/fixtures/log_analyzer_phase2`.
    - _Requirements: 14.5, 14.6, 14.8_

- [x] 16. Implementar validações automatizadas de limites e desempenho
  - [x] 16.1 Criar testes slow de streaming e pico de memória
    - Criar `tests/phase2/performance/test_streaming_memoria.py` com dados temporários gerados para
      limites em torno de 500 MB, bloco grande e muitos blocos pequenos; medir `tracemalloc` e
      comprovar que RAM acompanha estado/índice/resultado, não bytes totais.
    - Usar arquivos esparsos/doubles de stat quando apropriado e nunca versionar os dados gerados.
    - _Requirements: 15.8_

  - [x] 16.2 Criar testes slow de lote, spill e seletividade
    - Criar `tests/phase2/performance/test_lote_indice.py` para 100 arquivos, rejeição do 101º,
      spill SQLite, muitos identificadores, match raro/frequente e segundo passe limitado aos
      intervalos selecionados.
    - _Requirements: 7.4, 15.6, 15.8_

  - [x] 16.3 Criar testes técnicos de integridade e limpeza sob carga
    - Criar `tests/phase2/performance/test_integridade_limpeza.py` para alteração concorrente da
      fonte, falha de disco/índice, permissões e remoção de temporários em sucesso/exceção, sem
      fallback para RAM irrestrita.
    - _Requirements: 14.7, 15.1, 15.6, 15.8_

- [x] 17. Executar validações focadas por onda e validação final
  - [x] 17.1 Validar a fundação aditiva e a compatibilidade de contratos
    - Executar `python -m pytest -q tests/test_modelos.py tests/test_excecoes.py tests/test_parser_interface.py tests/test_registro.py tests/phase2/test_caracterizacao_contratos_fase1.py tests/phase2/test_caracterizacao_fluxos_legados.py tests/phase2/test_modelos_contratos_aditivos.py tests/phase2/properties/test_property_29_plugins_legados.py`.
    - Corrigir regressões antes de iniciar serviços de I/O; não atualizar expectativas legadas para
      mascarar mudança incompatível.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 17.2 Validar streaming, multiline, tempo e identificadores
    - Executar os testes `tests/phase2/test_streaming_indice_materializacao.py`,
      `test_multiline.py`, `test_temporal_identificadores.py` e Properties 5, 6, 9, 10 e 11.
    - Verificar também que nenhum temporário permanece e que os testes não acessam fontes brutas.
    - _Requirements: 4.1, 4.3, 4.6, 5.1, 6.1, 6.7, 7.1, 15.4_

  - [x] 17.3 Validar parsers reais e todos os perfis legados
    - Executar `python -m pytest -q tests/test_vpl_parser.py tests/test_ork_parser.py tests/test_voci_parser.py tests/test_property_parsers.py tests/phase2/test_vpl_parser_real.py tests/phase2/test_ork_parser_real.py tests/phase2/properties/test_property_01_parsing_vpl.py tests/phase2/properties/test_property_02_vpl_invalido.py tests/phase2/properties/test_property_03_parsing_ork.py tests/phase2/properties/test_property_04_ork_invalido.py tests/phase2/properties/test_property_07_roundtrip_vpl.py tests/phase2/properties/test_property_08_roundtrip_ork.py`.
    - Confirmar Properties 1–4, 7 e 8 com pelo menos 100 exemplos cada e nenhuma mudança VOCI.
    - _Requirements: 1.2, 2.1, 2.5, 3.1, 3.4, 5.4, 5.5_

  - [x] 17.4 Validar grafo, busca, correlação e explicabilidade
    - Executar os testes unitários correspondentes e Properties 12–17 e 24; reexecutar
      `tests/test_filtro.py`, `tests/test_correlacao.py` e `tests/test_ordenacao.py`.
    - Confirmar que nenhum teste aceita proximidade temporal, similaridade ou mera coexistência
      como vínculo/correlação.
    - _Requirements: 7.2, 7.3, 8.3, 8.4, 8.5, 9.1, 9.2, 9.6, 13.4_

  - [x] 17.5 Validar sanitização, governança, catálogo e fail-closed
    - Executar os testes unitários correspondentes, Properties 19–23 e 25–27 e o scanner sobre
      `tests/fixtures/log_analyzer_phase2` e `log_analyzer/catalogos`.
    - Confirmar catálogo distribuído sem regra ativa/ERRO/causa-raiz, fixture candidata
      `NAO_CLASSIFICADA` e zero valor sintético sensível ecoado nos relatórios de rejeição.
    - _Requirements: 10.1, 10.3, 10.5, 11.5, 12.3, 14.1, 14.5, 14.6, 14.7, 14.8_

  - [x] 17.6 Auditar mecanicamente a cobertura única das 30 propriedades
    - Criar `tests/phase2/test_manifesto_propriedades.py` para inspecionar
      `tests/phase2/properties/test_property_*.py` e exigir exatamente os números 1–30, um arquivo e
      uma função Hypothesis por número, comentário `Feature` correspondente e
      `max_examples >= 100`.
    - Executar esse teste e toda a pasta de propriedades; tratar duplicata, lacuna ou tag divergente
      como falha.
    - _Requirements: 2.1, 2.5, 3.1, 3.4, 4.1, 4.6, 5.4, 5.5, 6.1, 6.8, 7.7, 8.6, 9.7, 10.6, 11.5, 12.7, 13.7, 14.7, 15.7, 16.5_

  - [x] 17.7 Executar a validação final funcional, de regressão e segurança
    - Executar `python -m pytest -q -m "not slow"`, o scanner de fixtures e os testes de não
      vazamento; confirmar que a suíte completa da Fase 1 continua verde e que não há acesso a
      `logs/` ou `curation.db`.
    - Executar um smoke automatizado da CLI com arquivos temporários sintéticos para VPL, ORK e
      VOCI, verificando códigos e saída exclusivamente sanitizada.
    - _Requirements: 1.2, 1.3, 1.4, 1.6, 14.1, 14.8, 16.1, 16.3, 16.4, 16.6, 17.1_

  - [x] 17.8 Executar a validação final de desempenho e limites
    - Executar `python -m pytest -q -m slow tests/phase2/performance` em ambiente com espaço
      temporário controlado; verificar limites de memória, tempo definidos pelos próprios testes,
      100/101 arquivos, 500 MB/500 MB+1, spill, segundo passe e limpeza.
    - Reexecutar `python -m pytest -q` após os testes slow para confirmar ausência de resíduos ou
      dependência de ordem.
    - _Requirements: 15.6, 15.8, 16.5_

## Notes

- Todas as 99 folhas são técnicas e executáveis por agente de código; nenhuma solicita aprovação,
  curadoria ou decisão humana durante a execução.
- As 30 Correctness Properties aparecem em exatamente uma folha PBT cada: Properties 1–30 são
  cobertas, sem duplicação, com Hypothesis e no mínimo 100 exemplos.
- Testes, scanners e validações são obrigatórios neste plano porque protegem compatibilidade e
  dados sensíveis; nenhuma folha foi marcada como opcional.
- A fixture `golden_candidate` é somente uma representação estrutural manual com placeholders. O
  teste de regra ativa usa uma regra genérica criada em diretório temporário e não define o
  comportamento de produção.
- **Bloqueio externo conhecido:** a ativação real do Requirement 11 depende da definição das
  condições necessárias/suficientes, de fixture sanitizada aprovada e da aprovação do
  `Responsavel_de_Dominio`. Nenhuma tarefa executável deste plano inventa esses predicados ou
  ativa a regra real; até esses artefatos existirem, o comportamento esperado é fail-closed com
  `NAO_CLASSIFICADA`.
- Nenhum log bruto, call ID, telefone, UUID, IP, URL, credencial ou dado de cliente real pode ser
  copiado ou versionado. Builders geram valores sintéticos em tempo de teste e fixtures persistidas
  usam somente placeholders tipados.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["2.4"] },
    { "id": 5, "tasks": ["2.5", "2.6"] },
    { "id": 6, "tasks": ["17.1"] },
    { "id": 7, "tasks": ["3.1", "3.2", "5.1", "5.3"] },
    { "id": 8, "tasks": ["3.3", "4.1", "5.2"] },
    { "id": 9, "tasks": ["3.4", "4.2", "4.3", "4.4", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 10, "tasks": ["17.2"] },
    { "id": 11, "tasks": ["6.1", "6.2"] },
    { "id": 12, "tasks": ["6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9", "6.10"] },
    { "id": 13, "tasks": ["17.3"] },
    { "id": 14, "tasks": ["7.1", "9.2", "10.1", "10.3", "11.1"] },
    { "id": 15, "tasks": ["7.2", "7.3", "7.4", "7.5", "8.1", "10.2", "10.4", "11.2"] },
    { "id": 16, "tasks": ["8.2", "8.3", "8.4", "9.1", "10.5", "10.6", "10.7", "10.8", "11.3"] },
    { "id": 17, "tasks": ["9.3", "9.4", "9.5", "11.4", "11.5"] },
    { "id": 18, "tasks": ["17.4"] },
    { "id": 19, "tasks": ["11.6", "11.7", "11.8", "11.9", "11.10", "11.11"] },
    { "id": 20, "tasks": ["17.5"] },
    { "id": 21, "tasks": ["12.3", "13.1", "13.3"] },
    { "id": 22, "tasks": ["12.1"] },
    { "id": 23, "tasks": ["12.2", "13.2"] },
    { "id": 24, "tasks": ["12.4", "12.5", "12.6", "12.7", "13.4", "13.5"] },
    { "id": 25, "tasks": ["17.6"] },
    { "id": 26, "tasks": ["14.1", "14.2", "14.3", "14.4", "15.1", "15.2", "15.3", "15.4"] },
    { "id": 27, "tasks": ["17.7"] },
    { "id": 28, "tasks": ["16.1", "16.2", "16.3"] },
    { "id": 29, "tasks": ["17.8"] }
  ]
}
```
