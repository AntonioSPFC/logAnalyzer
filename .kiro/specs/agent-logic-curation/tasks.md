# Implementation Plan: Agent Logic Curation

## Overview

Implementar a feature `agent-logic-curation` em Python 3.11+ como extensão do monólito modular existente. O trabalho parte de migração SQLite aditiva e modelos de domínio puros, evolui até ingestão e JSON lossless, catálogo e evidência, edição e validação, versionamento e exportação, e termina com serviços Flask, templates Jinja/Bootstrap e jornadas integradas. A implementação deve reutilizar `dashboard.app.create_app`, `CurationStore`, `CallLogParser`, pytest e Hypothesis, sem executar `Action_Code`, sem transmitir dados para fora do armazenamento local e sem alterar o artefato original ou os relatórios legados.

## Tasks

- [ ] 1. Criar as fundações de domínio e persistência aditiva
  - [ ] 1.1 Criar os pacotes e modelos de domínio puros da feature
    - Criar `log_analyzer/curation/` e definir, em módulos coesos, os tipos imutáveis de artefato, documento, catálogo, evidência, sessão, curadoria, cópia de trabalho, validação, versão, auditoria e exportação descritos no design.
    - Representar resultados de sucesso, falha, bloqueio, lacuna e conflito como tipos explícitos, sem dependência de Flask ou SQLite.
    - Preservar valores tipados, revisões, fingerprints, referências e estados necessários para concorrência otimista e prontidão.
    - _Requisitos: 1.1, 1.2, 2.1, 6.3, 8.1, 9.1, 10.1, 11.16, 14.1, 17.7_

  - [ ] 1.2 Implementar migração SQLite aditiva e `UnitOfWork`
    - Criar `dashboard/curation/migrations.py` e `dashboard/curation/db.py` com migração versionada, checksum, `PRAGMA foreign_keys = ON`, `busy_timeout`, `BEGIN IMMEDIATE`, commit e rollback único por comando.
    - Criar idempotentemente todas as tabelas `alc_` definidas no design, seus índices, foreign keys `RESTRICT`, índice parcial da raiz de linhagem e triggers que rejeitam `UPDATE`/`DELETE` de originais, versões e auditoria.
    - Manter a tabela `curation_reports` e seus dados sem alteração; uma falha de migração deve reverter integralmente a tentativa.
    - _Requisitos: 1.2, 14.3, 14.8, 14.9, 17.4, 17.5, 17.6, 17.7_

  - [ ] 1.3 Implementar repositórios especializados sobre uma única conexão transacional
    - Criar `dashboard/curation/repositories.py` com responsabilidades exclusivas para `Original_Artifact`, `Agent_Document`/`Work_Copy`, UI metadata/versões/auditoria e vínculos legados.
    - Implementar inserts atômicos, leituras determinísticas, append-only, revisão otimista por `WHERE revision = ?` e resultados distinguíveis para conflito, constraint, lock e rollback.
    - Impedir que os novos repositórios escrevam em `curation_reports`; referências legadas devem ser somente vínculos por identificador.
    - _Requisitos: 1.2, 14.3, 14.9, 16.2, 16.3, 16.5, 17.4, 17.5, 17.6, 17.7_

  - [ ]* 1.4 Criar fixtures e estratégias reutilizáveis da feature
    - Criar `tests/agent_logic_curation/conftest.py` e `tests/agent_logic_curation/strategies.py` com SQLite temporário, relógio/IDs determinísticos, atores, árvores lossless com chaves duplicadas, schemas pequenos, eventos, grafos, mudanças, versões e políticas sensíveis.
    - Gerar objetos lossless como listas ordenadas de membros, sem usar `dict` como oráculo para objetos JSON.
    - Reutilizar pytest e Hypothesis já configurados em `pyproject.toml`, sem adicionar framework paralelo.
    - _Requisitos: 2.1, 2.6, 6.2, 10.10, 11.13, 13.4, 14.8, 15.6, 18.1_

  - [ ]* 1.5 Testar migração, atomicidade, imutabilidade e concorrência SQLite
    - Criar `tests/agent_logic_curation/test_persistence_integration.py` para executar a migração duas vezes, abrir banco legado, verificar FKs/triggers/índices, injetar falhas em cada etapa e provar rollback integral.
    - Simular duas revisões concorrentes de `Work_Copy`, locks e commit malsucedido, verificando que não há sobrescrita nem estado parcial.
    - _Requisitos: 1.2, 1.7, 1.9, 14.9, 17.4, 17.5, 17.6, 17.7_

  - [ ]* 1.6 Criar regressão do `CurationStore` e do banco legado
    - Criar `tests/agent_logic_curation/test_legacy_store_regression.py` para salvar, atualizar, listar e exportar relatórios antes e depois da migração, preservando texto e timestamps.
    - Verificar que vínculos e dados estruturados novos não modificam, substituem nem removem `curation_reports`.
    - _Requisitos: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 17.7_

- [ ] 2. Implementar schema local, ingestão e JSON lossless
  - [ ] 2.1 Implementar o registro local de `Source_Schema`
    - Criar `log_analyzer/curation/schema.py` com `SourceSchemaRegistry`, descritores tipados, fingerprint e resultados `CompatibleSchema`, `MissingSchema` e `IncompatibleSchema` por `specVersion`.
    - Ler somente raízes locais configuradas, sem rede e sem inferir regras a partir do artefato Athena; ausência de schema deve permanecer um estado explícito.
    - Expor marcadores canônicos, campos embutidos, categorias, referências e restrições para os componentes posteriores.
    - _Requisitos: 2.2, 2.3, 3.6, 4.1, 4.2, 10.2, 10.3, 10.4, 10.5, 10.7, 10.12, 11.2, 11.3, 18.9_

  - [ ] 2.2 Implementar a árvore JSON lossless e o codec de `Source_Path`
    - Criar `log_analyzer/curation/source_path.py` e `log_analyzer/curation/json_model.py` para objetos como listas de `JsonMember`, arrays ordenados, strings, números com lexema, booleanos e `null`.
    - Implementar percent-encoding UTF-8 canônico, ordinais de chaves duplicadas, caminhos distintos para chave/valor e índices de array conforme o design.
    - Manter spans em bytes, lexemas, `Node_Id` de linhagem e unicidade/reprodutibilidade de caminhos.
    - _Requisitos: 2.1, 2.2, 2.7, 3.1, 10.10_

  - [ ] 2.3 Implementar o scanner e `AgentJsonParser` sem perda
    - Criar `log_analyzer/curation/lossless_json.py` com scanner posicional e parser que preservem cada ocorrência de chave, ordem, tipo, lexema numérico, campos desconhecidos e bytes de origem.
    - Produzir a primeira falha sintática com motivo, offset de byte iniciado em zero, linha/coluna iniciadas em um e posição posterior ao último byte para fim inesperado.
    - Aceitar exatamente um documento JSON e rejeitar bytes/encoding, truncamento, valor extra e limites configuráveis de profundidade/nós de forma controlada.
    - _Requisitos: 2.1, 2.2, 2.4, 2.7, 15.12_

  - [ ] 2.4 Implementar JSON embutido, printer determinístico e codec de snapshot
    - Interpretar separadamente strings declaradas pelo schema como JSON embutido, preservando a string externa e produzindo diagnóstico localizado quando o conteúdo interno for inválido.
    - Implementar `AgentJsonPrinter` com indentação uniforme não vazia, saída determinística e reparse obrigatório; implementar snapshot interno versionado que preserve objetos como membros ordenados.
    - Retornar os bytes originais por uma via explícita quando o documento não tiver mudanças, sem usar o printer para identidade byte a byte.
    - _Requisitos: 2.3, 2.5, 2.6, 2.8, 15.3, 15.6, 15.7_

  - [ ] 2.5 Implementar `ArtifactImporter` e reabertura com verificação de integridade
    - Criar `log_analyzer/curation/artifacts.py` para staging de stream limitado, leitura integral, nome recebido como dado, SHA-256 incremental, tamanho e intervalo UTC.
    - Exigir parse externo bem-sucedido antes do commit atômico de artefato/documento/auditoria e não registrar tentativas parciais.
    - Reabrir exclusivamente o BLOB persistido após recalcular tamanho/hash; divergência ou falha deve impedir reabertura e criação de cópia sem alterar estado existente.
    - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 15.10, 15.12, 17.5_

  - [ ]* 2.6 Testar por exemplos ingestão, parser, printer e schema
    - Criar `tests/agent_logic_curation/test_artifact_json_examples.py` para JSON truncado, encoding inválido, vírgula extra, fim inesperado, chave duplicada, número extremo, campo desconhecido e JSON embutido válido/inválido.
    - Cobrir upload incompleto, hash falho, nome não confiável, limite de corpo, reabertura divergente, schema ausente/incompatível e ausência de registro parcial.
    - _Requisitos: 1.1–1.9, 2.1–2.8, 11.3, 15.10, 15.12_

  - [ ]* 2.7 Escrever PBT da Property 1: Integridade e invariância do artefato original
    - Criar `tests/agent_logic_curation/properties/test_property_01_original_integrity.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 1: Integridade e invariância do artefato original` e gerar sequências de reabertura, edição, descarte, validação, versão e exportação.
    - **Valida: Requisitos 1.3, 1.6, 1.8, 12.15**

  - [ ]* 2.8 Escrever PBT da Property 2: Round-trip lossless e impressão determinística
    - Criar `tests/agent_logic_curation/properties/test_property_02_lossless_round_trip.py` com um único teste e `@settings(max_examples=100)` para duplicatas, Unicode, números e JSON embutido.
    - Usar a tag `Feature: agent-logic-curation, Property 2: Round-trip lossless e impressão determinística`.
    - **Valida: Requisitos 2.1, 2.2, 2.3, 2.5, 2.6**

  - [ ]* 2.9 Escrever PBT da Property 3: Unicidade e determinismo de Source_Path
    - Criar `tests/agent_logic_curation/properties/test_property_03_source_path.py` com um único teste e `@settings(max_examples=100)` para chaves duplicadas, `%`, `/`, `~` e Unicode.
    - Usar a tag `Feature: agent-logic-curation, Property 3: Unicidade e determinismo de Source_Path`.
    - **Valida: Requisitos 2.7**

- [ ] 3. Checkpoint — validar fundações, migração, ingestão e JSON lossless
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implementar catálogo, fonte canônica e grafo de dependências
  - [ ] 4.1 Implementar `StructureCatalogBuilder`
    - Criar `log_analyzer/curation/catalog.py` para percorrer todas as ocorrências sem deduplicar, registrar pai/filhos, conexões, categorias, metadados raiz, contagens por caminho e campos esperados ausentes sem defaults.
    - Manter projeções estruturada e textual bruta sob o mesmo caminho e descobrir nomes/contagens do perfil Athena a partir do documento, sem constantes do perfil de referência.
    - _Requisitos: 3.1–3.8_

  - [ ] 4.2 Implementar `CanonicalSourceResolver`
    - Criar `log_analyzer/curation/canonical.py` para classificar cada candidato exatamente uma vez somente por marcadores/referências do schema.
    - Manter `promptText`, `allPrompts`, `drafts` e históricos em caminhos distintos; representar ausência, empate ou marcadores conflitantes como `Unresolved_Source` e bloqueio de prontidão.
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.8_

  - [ ] 4.3 Implementar confirmação canônica, baseline e `Work_Copy` isolada
    - Persistir candidato escolhido, demais candidatos, justificativa não vazia, ator e UTC como UI metadata, em uma única transação com versão baseline, cópia de trabalho, workflow e auditoria.
    - Inicializar a cópia lossless-equivalente ao candidato confirmado sem alterar qualquer caminho ou candidato do documento de origem.
    - _Requisitos: 4.4, 4.6, 4.7, 8.4, 14.8, 17.5_

  - [ ] 4.4 Implementar `DependencyGraphBuilder` e comparação de representações duplicadas
    - Criar `log_analyzer/curation/dependency_graph.py` com arestas resolvidas/não resolvidas, origem, destino, tipo, evidência e consultas `incoming`, `outgoing` e `uses` resistentes a ciclos.
    - Agrupar Graph/ORK somente por schema ou referência explícita; produzir equivalência ou finding divergente com todos os valores/proveniências, sem reconciliação automática.
    - Implementar comando de resolução que só altera representações explicitamente selecionadas após confirmação.
    - _Requisitos: 5.1–5.7, 11.9_

  - [ ]* 4.5 Testar catálogo, resolução canônica e grafo por exemplos
    - Criar `tests/agent_logic_curation/test_catalog_canonical_graph_examples.py` para campos ausentes, metadados, texto bruto, contagens Athena descobertas, histórico separado, empates, conflitos de marcadores, referências órfãs, ciclos e divergências.
    - Verificar que nenhuma decisão ou correção automática altera o documento original.
    - _Requisitos: 3.1–3.8, 4.1–4.8, 5.1–5.7_

  - [ ]* 4.6 Escrever PBT da Property 4: Fidelidade estrutural do catálogo
    - Criar `tests/agent_logic_curation/properties/test_property_04_catalog_structure.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 4: Fidelidade estrutural do catálogo`.
    - **Valida: Requisitos 3.1, 3.3, 3.8**

  - [ ]* 4.7 Escrever PBT da Property 5: Projeções do catálogo preservam a origem
    - Criar `tests/agent_logic_curation/properties/test_property_05_catalog_projections.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 5: Projeções do catálogo preservam a origem`.
    - **Valida: Requisitos 3.2, 3.4, 3.5**

  - [ ]* 4.8 Escrever PBT da Property 6: Classificação canônica exclusiva e baseada em evidência
    - Criar `tests/agent_logic_curation/properties/test_property_06_canonical_classification.py` com um único teste e `@settings(max_examples=100)`, incluindo permutações e datas irrelevantes.
    - Usar a tag `Feature: agent-logic-curation, Property 6: Classificação canônica exclusiva e baseada em evidência`.
    - **Valida: Requisitos 4.1, 4.2, 4.3**

  - [ ]* 4.9 Escrever PBT da Property 7: Criação isolada da cópia canônica
    - Criar `tests/agent_logic_curation/properties/test_property_07_canonical_copy.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 7: Criação isolada da cópia canônica`.
    - **Valida: Requisitos 4.7**

  - [ ]* 4.10 Escrever PBT da Property 8: Exatidão do grafo de dependências
    - Criar `tests/agent_logic_curation/properties/test_property_08_dependency_graph.py` com um único teste e `@settings(max_examples=100)` para referências resolvidas, órfãs e ciclos.
    - Usar a tag `Feature: agent-logic-curation, Property 8: Exatidão do grafo de dependências`.
    - **Valida: Requisitos 5.1, 5.2, 5.7**

  - [ ]* 4.11 Escrever PBT da Property 9: Equivalência e divergência de representações duplicadas
    - Criar `tests/agent_logic_curation/properties/test_property_09_duplicate_representations.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 9: Equivalência e divergência de representações duplicadas`.
    - **Valida: Requisitos 5.3, 5.4, 11.9**

- [ ] 5. Adaptar evidências do `CallLogParser` e inspecionar ocorrências
  - [ ] 5.1 Implementar `LogEvidenceAdapter` sem duplicar a semântica do parser
    - Criar `log_analyzer/curation/evidence_adapter.py` para descobrir fontes configuradas, capturar arquivo lógico, linha iniciada em um, ordem global e texto bruto e invocar exclusivamente `CallLogParser` para associação semântica ao CallId.
    - Preservar linhas pertencentes ao CallId que o parser não interpretar e falhas por fonte como `Raw_Evidence`/`Evidence_Gap`, sem declarar ausência em fonte não examinada.
    - _Requisitos: 6.1, 6.3, 6.9, 6.10, 6.12, 17.3_

  - [ ] 5.2 Implementar `OccurrenceInspector` e ordenação estável
    - Criar `log_analyzer/curation/occurrence.py` para envelopar os modelos existentes, ordenar eventos válidos por `(timestamp, read_order)` e colocar timestamps ausentes/inválidos ao final sem inferência.
    - Projetar transcrições, respostas, transições, prompts, modelos, decisões, warnings e erros com CallId, conteúdo integral, evidência, fonte, linha/posição ou gap.
    - _Requisitos: 6.1, 6.2, 6.3, 6.6, 6.8, 6.9, 6.10, 6.11, 6.12_

  - [ ] 5.3 Implementar pares observados e agrupamento de chamadas de Tool
    - Criar `log_analyzer/curation/observed_values.py` para comparar Request/Response integralmente e classificar campos como inalterado, alterado, apenas original ou apenas processado.
    - Agrupar somente registros com identificador observado da mesma chamada e preservar argumentos, resultado, segunda chamada, erro e latências; registros sem vínculo devem permanecer separados com gap.
    - _Requisitos: 6.4, 6.5, 6.7, 6.9_

  - [ ]* 5.4 Testar o adaptador com fixtures ORK/VPL e fontes parciais
    - Criar `tests/agent_logic_curation/test_occurrence_examples.py` usando `CallLogParser` real para linhas ORK/VPL, formatos intercalados, timestamp inválido, linha não interpretável, fonte inacessível e Tool sem identificador.
    - Verificar conteúdo bruto, número de linha, ordem de leitura e ausência de inferências.
    - _Requisitos: 6.1–6.12, 17.3_

  - [ ]* 5.5 Escrever PBT da Property 10: Ordenação cronológica estável
    - Criar `tests/agent_logic_curation/properties/test_property_10_stable_event_order.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 10: Ordenação cronológica estável`.
    - **Valida: Requisitos 6.2**

  - [ ]* 5.6 Escrever PBT da Property 11: Projeção de evento preserva conteúdo e evidência
    - Criar `tests/agent_logic_curation/properties/test_property_11_event_projection.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 11: Projeção de evento preserva conteúdo e evidência`.
    - **Valida: Requisitos 6.3, 6.6, 6.8**

  - [ ]* 5.7 Escrever PBT da Property 12: Diff completo de pares observados
    - Criar `tests/agent_logic_curation/properties/test_property_12_observed_pair_diff.py` com um único teste e `@settings(max_examples=100)` para Requests e Responses.
    - Usar a tag `Feature: agent-logic-curation, Property 12: Diff completo de pares observados`.
    - **Valida: Requisitos 6.4, 6.5**

  - [ ]* 5.8 Escrever PBT da Property 13: Isolamento de chamadas de Tool
    - Criar `tests/agent_logic_curation/properties/test_property_13_tool_call_isolation.py` com um único teste e `@settings(max_examples=100)` para registros intercalados.
    - Usar a tag `Feature: agent-logic-curation, Property 13: Isolamento de chamadas de Tool`.
    - **Valida: Requisitos 6.7**

- [ ] 6. Implementar rastreabilidade, registros de curadoria e workflow
  - [ ] 6.1 Implementar `TraceabilityEngine`
    - Criar `log_analyzer/curation/traceability.py` com índices exatos por categoria, tipo e valor, propostas zero/um/múltiplos candidatos e navegação bidirecional sem atribuição causal implícita.
    - Preservar evidências, todos os caminhos e regra; representar cadeias de transformação apenas com transições observadas e gaps para saltos sem evidência.
    - _Requisitos: 7.1–7.6, 7.8, 7.9_

  - [ ] 6.2 Implementar confirmação causal transacional e auditada
    - Confirmar somente candidato apresentado, persistir estado e exatamente um `Audit_Event` na primeira transição, tornando retry idempotente e decisão conflitante explícita.
    - Manter `Agent_Document` e `Raw_Evidence` inalterados e conservar todos os candidatos após a confirmação.
    - _Requisitos: 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 17.5_

  - [ ] 6.3 Implementar `CurationRecordService` e integração legada somente leitura
    - Criar `log_analyzer/curation/curation_records.py` com os campos obrigatórios, condição de sucesso/falha, relações individuais complaint-evidence/source/correction e prontidão causal.
    - Tratar whitespace como vazio, listar cada ausência e manter relatório legado distinto; vínculo explícito deve copiar apenas IDs e nunca confirmar responsabilidade.
    - _Requisitos: 8.1–8.8, 16.1–16.6_

  - [ ] 6.4 Implementar a máquina persistente das nove etapas
    - Criar `log_analyzer/curation/workflow.py` com ordem fixa, pré-condições calculadas, próxima etapa, invalidação de etapas posteriores e estados disabled/pending/complete.
    - Tornar navegação uma leitura pura e preservar revisão da cópia e marcações; expor termos e campos faltantes para explicações em português na UI.
    - _Requisitos: 9.1–9.6, 9.8, 9.11_

  - [ ]* 6.5 Testar rastreabilidade, curadoria, legado e workflow por exemplos
    - Criar `tests/agent_logic_curation/test_traceability_curation_workflow_examples.py` para zero/um/vários candidatos, confirmação repetida/conflitante, transição sem evidência, campos vazios, relatório legado e progressão/bloqueio das nove etapas.
    - _Requisitos: 7.1–7.9, 8.1–8.8, 9.1–9.6, 16.1–16.6_

  - [ ]* 6.6 Escrever PBT da Property 14: Correspondência exata de rastreabilidade
    - Criar `tests/agent_logic_curation/properties/test_property_14_exact_traceability.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 14: Correspondência exata de rastreabilidade`.
    - **Valida: Requisitos 7.1, 7.2**

  - [ ]* 6.7 Escrever PBT da Property 15: Fidelidade da cadeia de transformação observada
    - Criar `tests/agent_logic_curation/properties/test_property_15_transformation_chain.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 15: Fidelidade da cadeia de transformação observada`.
    - **Valida: Requisitos 7.6**

  - [ ]* 6.8 Escrever PBT da Property 16: Completude textual da curadoria
    - Criar `tests/agent_logic_curation/properties/test_property_16_curation_completeness.py` com um único teste e `@settings(max_examples=100)` para texto vazio/whitespace e evidências.
    - Usar a tag `Feature: agent-logic-curation, Property 16: Completude textual da curadoria`.
    - **Valida: Requisitos 8.3**

  - [ ]* 6.9 Escrever PBT da Property 17: Relações de curadoria são aditivas
    - Criar `tests/agent_logic_curation/properties/test_property_17_additive_curation_relations.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 17: Relações de curadoria são aditivas`.
    - **Valida: Requisitos 8.5, 8.6**

  - [ ]* 6.10 Escrever PBT da Property 18: Progressão e bloqueio do workflow
    - Criar `tests/agent_logic_curation/properties/test_property_18_workflow_progression.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 18: Progressão e bloqueio do workflow`.
    - **Valida: Requisitos 9.2, 9.3**

  - [ ]* 6.11 Escrever PBT da Property 19: Navegação não altera o trabalho
    - Criar `tests/agent_logic_curation/properties/test_property_19_navigation_identity.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 19: Navegação não altera o trabalho`.
    - **Valida: Requisitos 9.6**

- [ ] 7. Checkpoint — validar catálogo, evidências, rastreabilidade e curadoria
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implementar cópia de trabalho, edição estruturada e descarte
  - [ ] 8.1 Implementar overlay de `Work_Copy` e `Change_Set`
    - Criar `log_analyzer/curation/editing.py` com materialização do documento efetivo, operações add/remove/replace ordenadas, composição por caminho e revisão otimista.
    - Aplicar cada mudança somente à cópia alvo, registrar before/after imediato e marcar validação/comparação/etapas posteriores como desatualizadas sem tocar na base ou em outras cópias.
    - _Requisitos: 9.6, 10.1, 10.9, 10.10, 11.14, 12.17, 13.1_

  - [ ] 8.2 Implementar `StructuredEditor` por tipo e fallback limitado
    - Criar editores derivados do schema para Prompt, Rule/condição, Flow/Stage, Tool_Contract, configuração/modelo/ASR/TTS/mensagem e editor textual de `Action_Code`.
    - Implementar fallback JSON restrito ao subtree selecionado; rejeitar atomicamente JSON inválido, path/tipo/valor anterior divergente ou restrição de schema violada.
    - Manter diagnósticos de código fora do conteúdo JSON editável.
    - _Requisitos: 10.2–10.8, 10.12, 18.7, 18.8_

  - [ ] 8.3 Implementar solicitação, confirmação e cancelamento de descarte
    - Persistir `DiscardIntent` com revisão, expiração e conjunto exato de caminhos distintos; não alterar a cópia antes da confirmação.
    - Cancelar/rejeitar sem mutação e, ao confirmar na mesma revisão, restaurar exatamente a versão/base vigente e invalidar estados posteriores de forma atômica.
    - _Requisitos: 9.7, 9.9, 9.10, 10.11, 17.5, 17.6_

  - [ ]* 8.4 Testar todos os editores e descartes por exemplos
    - Criar `tests/agent_logic_curation/test_editing_examples.py` com um fixture por editor tipado, fallback válido/inválido, schema ausente, Action_Code como texto, conflito de revisão, contagem de paths e confirmação/cancelamento expirado.
    - _Requisitos: 9.7, 9.9, 9.10, 10.1–10.12, 18.7, 18.8_

  - [ ]* 8.5 Escrever PBT da Property 20: Isolamento, frame e registro da edição
    - Criar `tests/agent_logic_curation/properties/test_property_20_edit_isolation.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 20: Isolamento, frame e registro da edição`.
    - **Valida: Requisitos 10.1, 10.8, 10.9, 10.10, 12.17**

  - [ ]* 8.6 Escrever PBT da Property 21: Edição seguida de descarte é round-trip
    - Criar `tests/agent_logic_curation/properties/test_property_21_edit_discard_round_trip.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 21: Edição seguida de descarte é round-trip`.
    - **Valida: Requisitos 9.10, 10.11**

- [ ] 9. Implementar comparação estrutural e análise de impacto
  - [ ] 9.1 Implementar `VersionComparator`
    - Criar `log_analyzer/curation/comparison.py` para comparar snapshots por ocorrência, presença, tipo, valor e ordem relevante e produzir somente add/remove/replace necessários.
    - Implementar `apply`, `invert`, comparação entre versões e diff textual por linha sem substituir os valores brutos.
    - _Requisitos: 13.1, 13.3, 13.4, 13.5, 13.6, 14.6_

  - [ ] 9.2 Implementar `ImpactAnalyzer` e confirmação de comparação final
    - Criar `log_analyzer/curation/impact.py` com busca terminante em grafos cíclicos e categorias separadas para dependências diretas/transitivas, links e curadorias, incluindo listas vazias.
    - Criar o comando que exige confirmação explícita do resumo completo de mudanças e do impacto antes de concluir a etapa de validação final.
    - _Requisitos: 13.2, 13.7_

  - [ ]* 9.3 Testar diff, inversão, texto, impacto e confirmação por exemplos
    - Criar `tests/agent_logic_curation/test_comparison_examples.py` para adição/remoção/substituição, deslocamento em arrays, chave duplicada, equivalência semântica, ciclos e categorias vazias.
    - _Requisitos: 13.1–13.7, 14.6_

  - [ ]* 9.4 Escrever PBT da Property 35: Diff estrutural exato e equivalência semântica
    - Criar `tests/agent_logic_curation/properties/test_property_35_structural_diff.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 35: Diff estrutural exato e equivalência semântica`.
    - **Valida: Requisitos 13.1, 13.6, 14.6**

  - [ ]* 9.5 Escrever PBT da Property 36: Análise de impacto exata e terminante
    - Criar `tests/agent_logic_curation/properties/test_property_36_impact_analysis.py` com um único teste e `@settings(max_examples=100)` para grafos cíclicos.
    - Usar a tag `Feature: agent-logic-curation, Property 36: Análise de impacto exata e terminante`.
    - **Valida: Requisitos 13.2**

  - [ ]* 9.6 Escrever PBT da Property 37: Classificação correta do diff textual
    - Criar `tests/agent_logic_curation/properties/test_property_37_text_diff.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 37: Classificação correta do diff textual`.
    - **Valida: Requisitos 13.3**

  - [ ]* 9.7 Escrever PBT da Property 38: Reversibilidade do Change_Set
    - Criar `tests/agent_logic_curation/properties/test_property_38_change_set_reversibility.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 38: Reversibilidade do Change_Set`.
    - **Valida: Requisitos 13.4**

  - [ ]* 9.8 Escrever PBT da Property 39: Simetria do diff
    - Criar `tests/agent_logic_curation/properties/test_property_39_diff_symmetry.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 39: Simetria do diff`.
    - **Valida: Requisitos 13.5**

- [ ] 10. Implementar a pipeline geral de validação
  - [ ] 10.1 Implementar modelos, registry, ordenação e prontidão de validação
    - Criar `log_analyzer/curation/validation/` com interface pura de regra, contexto imutável, códigos estáveis, findings completos em português e ordenação por fase/código/caminhos.
    - Vincular resultados ao hash do snapshot, revisão e fingerprint do schema; calcular complete/incomplete, stale e prontidão sem acumular resultados ou alterar a cópia.
    - _Requisitos: 9.8, 11.11–11.17_

  - [ ] 10.2 Implementar validações sintáticas e de schema
    - Validar JSON externo, cada JSON embutido declarado, presença, tipo, enumeração e restrições estruturais.
    - Sem schema compatível, criar `Blocking_Error` estável de pré-condição e resultado incompleto, mantendo as verificações independentes disponíveis.
    - _Requisitos: 11.1, 11.2, 11.3, 11.11, 11.12, 11.16_

  - [ ] 10.3 Implementar validações de referências, variáveis e Tool_Contracts
    - Verificar destino existente/único/tipado, variáveis com definição/fonte e correspondência declaração↔mapeamento↔parâmetros↔campos de resultado consumidos.
    - Produzir um finding por violação demonstrável com todos os caminhos e evidências.
    - _Requisitos: 11.4, 11.5, 11.7, 11.11_

  - [ ] 10.4 Implementar validações de Flow/Stage, duplicatas e Rules
    - Verificar um início por Flow, destinos, alcançabilidade, órfãos e terminais; reutilizar o agrupamento explícito de representações para divergências.
    - Detectar equivalência/sobreposição incompatível de Rules somente em domínio permitido demonstrável e classificar incerteza por intenção/evidência ausente como Warning.
    - _Requisitos: 11.6, 11.8, 11.9, 11.12, 12.14_

  - [ ]* 10.5 Testar pipeline, schema, referências, grafos e prontidão por exemplos
    - Criar `tests/agent_logic_curation/test_validation_examples.py` para schema ausente, embedded inválido, referência órfã/ambígua/tipo incorreto, contrato incompatível, Stage inalcançável, Rule incerta, resultado stale e bloqueios de versão/exportação.
    - _Requisitos: 11.1–11.17, 12.14_

  - [ ]* 10.6 Escrever PBT da Property 22: Validação sintática e de schema é completa
    - Criar `tests/agent_logic_curation/properties/test_property_22_schema_validation.py` com um único teste e `@settings(max_examples=100)` e oráculo independente de schemas pequenos.
    - Usar a tag `Feature: agent-logic-curation, Property 22: Validação sintática e de schema é completa`.
    - **Valida: Requisitos 11.1, 11.2**

  - [ ]* 10.7 Escrever PBT da Property 23: Validação referencial e de variáveis é exata
    - Criar `tests/agent_logic_curation/properties/test_property_23_reference_validation.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 23: Validação referencial e de variáveis é exata`.
    - **Valida: Requisitos 11.4, 11.7**

  - [ ]* 10.8 Escrever PBT da Property 24: Consistência de Tool_Contract
    - Criar `tests/agent_logic_curation/properties/test_property_24_tool_contract.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 24: Consistência de Tool_Contract`.
    - **Valida: Requisitos 11.5**

  - [ ]* 10.9 Escrever PBT da Property 25: Invariantes do grafo de Flow e Stage
    - Criar `tests/agent_logic_curation/properties/test_property_25_flow_stage_graph.py` com um único teste e `@settings(max_examples=100)` e oráculo BFS independente.
    - Usar a tag `Feature: agent-logic-curation, Property 25: Invariantes do grafo de Flow e Stage`.
    - **Valida: Requisitos 11.6**

  - [ ]* 10.10 Escrever PBT da Property 26: Detecção de regras logicamente incompatíveis
    - Criar `tests/agent_logic_curation/properties/test_property_26_rule_conflicts.py` com um único teste e `@settings(max_examples=100)` sobre domínios finitos enumeráveis.
    - Usar a tag `Feature: agent-logic-curation, Property 26: Detecção de regras logicamente incompatíveis`.
    - **Valida: Requisitos 11.8, 12.14**

  - [ ]* 10.11 Escrever PBT da Property 27: Severidade, completude e prontidão coerentes
    - Criar `tests/agent_logic_curation/properties/test_property_27_validation_readiness.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 27: Severidade, completude e prontidão coerentes`.
    - **Valida: Requisitos 11.11, 11.15, 11.16**

  - [ ]* 10.12 Escrever PBT da Property 28: Validação determinística, idempotente e não mutante
    - Criar `tests/agent_logic_curation/properties/test_property_28_validation_determinism.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 28: Validação determinística, idempotente e não mutante`.
    - **Valida: Requisitos 11.13**

  - [ ]* 10.13 Escrever PBT da Property 29: Mudança de entrada invalida a validação
    - Criar `tests/agent_logic_curation/properties/test_property_29_validation_invalidation.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 29: Mudança de entrada invalida a validação`.
    - **Valida: Requisitos 11.14**

- [ ] 11. Implementar análise estática e riscos Athena
  - [ ] 11.1 Implementar `ActionCodeAnalyzer` estritamente estático
    - Criar `log_analyzer/curation/validation/python_static.py` usando somente tokenização, `ast.parse` e visitantes de escopo/posição com limites de bytes, profundidade, nós e tempo cooperativo.
    - Detectar referência livre a `false`, referência livre a `e` no `except` e literais adjacentes em lista; falha/limite deve tornar a validação incompleta e bloqueante.
    - Proibir `compile`, `exec`, `eval`, importação dinâmica, subprocesso, socket, endpoint e chamada de Tool.
    - _Requisitos: 11.10, 12.1, 12.2, 12.3, 18.7, 18.8_

  - [ ] 11.2 Implementar todas as regras estruturais de risco Athena
    - Criar regras para pares `grau_parentesco`/`parentesco`, `codigo_especialidade`/`especialidade`, retornos `especialidadeOUT`/`especialidade`, IDs divergentes de Stage e `validate_schedule_cancellation` órfão.
    - Verificar cadeia de Tool de confirmação, execução não observada na Occurrence, transferência humana, instrução do `flow_start`, um finding por `nodeValidation.errors` e `nodeValidation.result=false` sem detalhes.
    - Manter toda correção apenas como proposta na `Work_Copy` e o original idêntico.
    - _Requisitos: 12.4–12.13, 12.15, 12.16, 12.17_

  - [ ]* 11.3 Testar análise estática e riscos Athena por exemplos e sentinelas
    - Criar `tests/agent_logic_curation/test_athena_validation_examples.py` com casos positivos/negativos de escopo, tokens, contratos, Stages, Tools, transferência, `flow_start` e `nodeValidation`.
    - Monkeypatchar APIs executáveis e usar sentinelas de arquivo/subprocesso/import/rede que fariam o teste falhar se qualquer código importado fosse executado.
    - _Requisitos: 11.10, 12.1–12.17, 18.7, 18.8_

  - [ ]* 11.4 Escrever PBT da Property 30: Diagnósticos estáticos Python respeitam escopo e tokens
    - Criar `tests/agent_logic_curation/properties/test_property_30_python_static.py` com um único teste e `@settings(max_examples=100)` usando templates AST/token, sem executar código.
    - Usar a tag `Feature: agent-logic-curation, Property 30: Diagnósticos estáticos Python respeitam escopo e tokens`.
    - **Valida: Requisitos 12.1, 12.2, 12.3**

  - [ ]* 11.5 Escrever PBT da Property 31: Incompatibilidades de contratos Athena são completas
    - Criar `tests/agent_logic_curation/properties/test_property_31_athena_contracts.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 31: Incompatibilidades de contratos Athena são completas`.
    - **Valida: Requisitos 12.4, 12.5, 12.6**

  - [ ]* 11.6 Escrever PBT da Property 32: Divergências de identificador de Stage são exatas
    - Criar `tests/agent_logic_curation/properties/test_property_32_stage_identifiers.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 32: Divergências de identificador de Stage são exatas`.
    - **Valida: Requisitos 12.7**

  - [ ]* 11.7 Escrever PBT da Property 33: Conectividade de Tool e capacidade humana
    - Criar `tests/agent_logic_curation/properties/test_property_33_tool_connectivity.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 33: Conectividade de Tool e capacidade humana`.
    - **Valida: Requisitos 12.9, 12.11**

  - [ ]* 11.8 Escrever PBT da Property 34: Bijeção de erros de origem e findings
    - Criar `tests/agent_logic_curation/properties/test_property_34_origin_errors.py` com um único teste e `@settings(max_examples=100)`, incluindo erros repetidos em posições distintas.
    - Usar a tag `Feature: agent-logic-curation, Property 34: Bijeção de erros de origem e findings`.
    - **Valida: Requisitos 12.13**

- [ ] 12. Checkpoint — validar edição, comparação e pipeline estática
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Implementar versões imutáveis, auditoria e reconhecimentos
  - [ ] 13.1 Implementar `VersionStore` e histórico imutável
    - Criar `log_analyzer/curation/versioning.py` para baseline única, versão de curador com pai, snapshot, fingerprint, change set completo, validação vigente e vínculos de curadoria.
    - Retornar `NoChanges` sem insert para cópia equivalente e rejeitar Blocking_Error, validação stale/incompleta e qualquer update/delete histórico.
    - Projetar histórico completo e comparação entre duas versões pelo comparador existente.
    - _Requisitos: 14.1, 14.2, 14.5, 14.6, 14.9, 14.10, 17.5_

  - [ ] 13.2 Implementar reversão seletiva e verificação da cadeia
    - Criar nova versão de reversão contendo somente mudanças dos caminhos selecionados e preservar todos os demais valores do pai.
    - Verificar exatamente uma raiz, pais existentes da mesma linhagem e término sem ciclos; nunca mutar a versão escolhida.
    - _Requisitos: 14.4, 14.8, 14.9_

  - [ ] 13.3 Implementar reconhecimentos de Warning e auditoria append-only
    - Exigir ator e justificativa não whitespace por finding da versão exata; invalidar autorização quando o snapshot/finding não corresponder.
    - Implementar append de `Audit_Event`, hash anterior, idempotência de comandos e bloqueio de exportação para Warning pendente, sem armazenar segredo em detalhes.
    - _Requisitos: 7.7, 14.3, 14.7, 14.11, 18.3_

  - [ ]* 13.4 Testar versões, no-op, reversão, cadeia, imutabilidade e warnings
    - Criar `tests/agent_logic_curation/test_versioning_examples.py` para criação bloqueada/válida, retry, no-op, histórico, tentativa de update/delete, reversão parcial, ciclo/pai inválido e justificativa vazia.
    - _Requisitos: 14.1–14.11_

  - [ ]* 13.5 Escrever PBT da Property 40: Versionamento sem mudança é no-op
    - Criar `tests/agent_logic_curation/properties/test_property_40_version_noop.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 40: Versionamento sem mudança é no-op`.
    - **Valida: Requisitos 14.2**

  - [ ]* 13.6 Escrever PBT da Property 41: Auditoria é append-only
    - Criar `tests/agent_logic_curation/properties/test_property_41_audit_append_only.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 41: Auditoria é append-only`.
    - **Valida: Requisitos 14.3**

  - [ ]* 13.7 Escrever PBT da Property 42: Reversão seletiva preserva o frame
    - Criar `tests/agent_logic_curation/properties/test_property_42_selective_revert.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 42: Reversão seletiva preserva o frame`.
    - **Valida: Requisitos 14.4**

  - [ ]* 13.8 Escrever PBT da Property 43: Integridade da cadeia de versões
    - Criar `tests/agent_logic_curation/properties/test_property_43_version_chain.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 43: Integridade da cadeia de versões`.
    - **Valida: Requisitos 14.8**

- [ ] 14. Implementar exportação completa e reimportação
  - [ ] 14.1 Implementar `AgentExporter.prepare` e exportação JSON
    - Criar `log_analyzer/curation/exporter.py` para autorizar somente validação vigente/completa/sem bloqueios e warnings reconhecidos, materializar o documento completo e excluir apenas UI metadata por construção.
    - Para change set efetivo vazio, retornar exatamente o BLOB original; para versão alterada, preservar frame, arrays, ordem relativa e metadados nativos e reparsear a saída inteira antes de disponibilizar.
    - _Requisitos: 11.15, 11.17, 14.11, 15.1–15.8, 15.11_

  - [ ] 14.2 Implementar pacote de auditoria e reimportação como nova base
    - Produzir JSON idêntico ao export individual e manifesto separado com versão, change set, validação e curadorias; não inserir manifesto/UI metadata no agente.
    - Encaminhar reimportação pelo `ArtifactImporter`, sempre criando identidade nova e preservando todos os originais anteriores.
    - _Requisitos: 15.2, 15.9, 15.10_

  - [ ] 14.3 Implementar autorização transacional e staging seguro da exportação
    - Preparar bytes localmente, calcular hashes e registrar autorização/auditoria atomicamente antes da exposição; limpar staging em qualquer falha e registrar falha posterior de streaming separadamente.
    - Não produzir JSON ou pacote quando sintaxe, validação, reconhecimento ou commit falhar.
    - _Requisitos: 15.7, 15.8, 15.9, 15.11, 17.5, 17.6, 18.9_

  - [ ]* 14.4 Testar exportação, bloqueios, pacote e reimportação por exemplos
    - Criar `tests/agent_logic_curation/test_export_examples.py` para serializer defeituoso, warning pendente, UI metadata, metadados nativos, JSON individual/pacote byte a byte, nova identidade e falha de commit/staging.
    - _Requisitos: 15.1–15.12_

  - [ ]* 14.5 Escrever PBT da Property 44: Exportação preserva conteúdo fora do frame
    - Criar `tests/agent_logic_curation/properties/test_property_44_export_frame.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 44: Exportação preserva conteúdo fora do frame`.
    - **Valida: Requisitos 15.1, 15.4, 15.5**

  - [ ]* 14.6 Escrever PBT da Property 45: Exportação sem mudança é byte-idêntica
    - Criar `tests/agent_logic_curation/properties/test_property_45_unchanged_export.py` com um único teste e `@settings(max_examples=100)` para whitespace, ordem e lexemas variados.
    - Usar a tag `Feature: agent-logic-curation, Property 45: Exportação sem mudança é byte-idêntica`.
    - **Valida: Requisitos 15.3**

  - [ ]* 14.7 Escrever PBT da Property 46: Round-trip semântico da exportação
    - Criar `tests/agent_logic_curation/properties/test_property_46_export_round_trip.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 46: Round-trip semântico da exportação`.
    - **Valida: Requisitos 15.6, 15.7**

- [ ] 15. Implementar política sensível, mascaramento e armazenamento local
  - [ ] 15.1 Implementar `SensitiveDataPolicy` e classificação determinística
    - Criar `log_analyzer/curation/sensitive.py` para carregar configuração local versionada, casar nomes de campo/padrões de log e aplicar exatamente a regra de mascaramento selecionada.
    - Manter classificação/máscara como projeções puras, sem escrever máscara em documento, evidência, cópia ou exportação.
    - _Requisitos: 18.1, 18.2, 18.6_

  - [ ] 15.2 Implementar revelação auditada, revisão de texto e limites locais
    - Resolver referências no servidor, confirmar `Audit_Event` antes de revelar somente o valor solicitado e falhar fechado se a auditoria não confirmar.
    - Implementar fluxo de dois passos para texto técnico com detecções, token opaco vinculado a conteúdo/ator/sessão/expiração e nenhuma persistência antes da revisão.
    - Garantir que artefatos, logs, cópias e auditoria permaneçam no armazenamento local salvo exportação explícita e que observabilidade nunca registre conteúdo sensível.
    - _Requisitos: 18.3, 18.4, 18.5, 18.9, 18.10_

  - [ ]* 15.3 Testar política, revelação e revisão sensível por exemplos
    - Criar `tests/agent_logic_curation/test_sensitive_examples.py` para múltiplas regras, spans, máscara, revelação isolada, commit falho, token expirado/alterado e exportação com valor original.
    - _Requisitos: 18.1–18.6, 18.9, 18.10_

  - [ ]* 15.4 Escrever PBT da Property 47: Classificação e máscara seguem a política
    - Criar `tests/agent_logic_curation/properties/test_property_47_sensitive_policy.py` com um único teste e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 47: Classificação e máscara seguem a política`.
    - **Valida: Requisitos 18.1**

  - [ ]* 15.5 Escrever PBT da Property 48: Mascaramento não contamina estado nem exportação
    - Criar `tests/agent_logic_curation/properties/test_property_48_masking_frame.py` com um único teste stateful e `@settings(max_examples=100)`.
    - Usar a tag `Feature: agent-logic-curation, Property 48: Mascaramento não contamina estado nem exportação`.
    - **Valida: Requisitos 18.2, 18.6**

- [ ] 16. Implementar serviços de aplicação e fronteiras transacionais
  - [ ] 16.1 Criar infraestrutura de serviços, ator, erros e idempotência
    - Criar `dashboard/curation/application.py` com `ActorProvider`, relógio/ID injetáveis, chaves idempotentes, correlation id e mapeamento de resultados de domínio para erros seguros.
    - Falhar fechado para ator ausente em confirmação, edição, versão, warning, revelação e exportação; não criar autenticação paralela.
    - _Requisitos: 4.6, 7.7, 14.1, 14.7, 18.3, 17.5, 17.6_

  - [ ] 16.2 Implementar casos de uso de investigação e curadoria
    - Criar `dashboard/curation/query_services.py` e comandos correlatos para import/reopen, catálogo, sessão, ocorrência, fonte canônica, rastreabilidade, registro estruturado e vínculo legado.
    - Coordenar repositórios pelo mesmo `UnitOfWork`, preservar gaps e atualizar as pré-condições das etapas sem estado parcial.
    - _Requisitos: 1.1–1.9, 3.1–9.6, 16.1–16.6, 17.5, 17.6_

  - [ ] 16.3 Implementar casos de uso de edição, validação, versão e exportação
    - Criar `dashboard/curation/command_services.py` para editar/descartar, comparar/confirmar impacto, validar snapshot, versionar/reverter, reconhecer warning, revelar e exportar.
    - Revalidar revisão e fingerprint antes do commit, aplicar cada comando persistente em uma transação e invalidar etapas/resultados dependentes quando necessário.
    - _Requisitos: 9.7–9.11, 10.1–15.12, 17.5, 17.6, 18.3–18.10_

  - [ ]* 16.4 Testar orquestração, rollback e idempotência dos serviços
    - Criar `tests/agent_logic_curation/test_application_services.py` com fault injection entre writes, revisão/schema alterados durante validação, retry do mesmo comando, ator ausente e falha de persistência distinguível.
    - Verificar commit completo ou nenhum efeito para cada comando composto da matriz transacional do design.
    - _Requisitos: 7.7, 17.5, 17.6, 18.3, 18.5_

- [ ] 17. Integrar Blueprint Flask e templates Jinja/Bootstrap
  - [ ] 17.1 Implementar `curation_bp` e todos os endpoints propostos
    - Criar `dashboard/curation/blueprint.py` com prefixo `/curation`, IDs opacos, `validate_call_id`, POST para mutações, Post/Redirect/Get, CSRF, limite de upload, autorização por sessão/artefato e downloads seguros `no-store`.
    - Mapear resultados para 400/403/404/409/413/422/503 conforme a taxonomia, sem stack trace ou valor sensível.
    - _Requisitos: 1.5, 6.1, 9.1–9.11, 11.17, 15.8, 17.1, 18.2–18.5_

  - [ ] 17.2 Criar templates de entrada, artefato, catálogo e ocorrência
    - Criar templates em `dashboard/templates/curation/` reutilizando `base.html` e Bootstrap existentes para pré-condições, fingerprint somente leitura, estrutura hierárquica, metadados, dependências, candidatos canônicos, timeline, requests/responses, Tools, gaps e relatório legado.
    - Renderizar sempre projeções mascaradas, escapar todo conteúdo não confiável e fornecer explicações em português ligadas à etapa atual.
    - _Requisitos: 1.2, 1.4, 1.5, 3.1–5.7, 6.1–6.12, 8.8, 9.5, 17.2, 18.2_

  - [ ] 17.3 Criar templates do fluxo guiado, editor, diff, validação, histórico e exportação
    - Renderizar as nove etapas na ordem exigida, campos faltantes, próxima etapa, confirmações de descarte/causa/impacto, editores tipados, before/after, findings com cinco rótulos em português, warnings, versões e downloads.
    - Manter navegação sem mutação e permitir concluir o fluxo sem edição direta de JSON quando houver editor tipado.
    - _Requisitos: 7.3–7.8, 8.1–8.8, 9.1–9.11, 10.2–10.12, 11.16–11.17, 13.1–15.11, 18.2–18.5_

  - [ ] 17.4 Registrar a feature na app factory existente
    - Atualizar somente `dashboard/app.py` e inicialização do pacote para criar migração/repositórios/serviços a partir da configuração e registrar `curation_bp` na mesma instância Flask.
    - Preservar rotas atuais, `CurationStore`, templates e comportamento do dashboard; adicionar configuração local para schema, política, limites, logs e ator.
    - _Requisitos: 16.4, 17.1, 17.2, 17.3, 17.7, 18.9_

  - [ ]* 17.5 Testar rotas, formulários, navegação e renderização
    - Criar `tests/agent_logic_curation/test_curation_routes.py` com cliente Flask para códigos HTTP, PRG, CSRF, estado das etapas, termos em português, campos faltantes, descarte, findings, histórico e downloads.
    - _Requisitos: 9.1–9.11, 17.1, 17.2_

  - [ ]* 17.6 Testar segurança da camada web
    - Criar `tests/agent_logic_curation/test_web_security.py` para XSS em nomes/chaves/logs/prompts/findings, SQL injection, path/header traversal, CSRF ausente, ator ausente, IDOR entre sessões, cache de revelação e nomes de download gerados.
    - _Requisitos: 17.5, 17.6, 18.2–18.5, 18.9, 18.10_

- [ ] 18. Integrar e validar jornadas completas sem regressão
  - [ ]* 18.1 Testar a jornada completa de curadoria
    - Criar `tests/agent_logic_curation/test_full_curation_journey.py` para importar artefato, selecionar CallId, inspecionar evidência, registrar complaint/esperado, confirmar lógica, editar, comparar impacto, validar, versionar, reconhecer warning e exportar.
    - Verificar as nove etapas, persistência após navegação e conclusão final, usando app factory, SQLite e parser reais com fixtures locais.
    - _Requisitos: 1.1, 6.1, 7.7, 8.1, 9.1–9.11, 10.1, 11.15–11.17, 14.1, 15.1, 17.1–17.5_

  - [ ]* 18.2 Testar jornada degradada por schema ausente e evidência parcial
    - Criar `tests/agent_logic_curation/test_incomplete_prerequisites_journey.py` para investigação e edição limitada com `MissingSchema`, fonte de log inacessível e gaps, provando bloqueio de versão/exportação sem perda dos dados válidos.
    - _Requisitos: 4.5, 6.9, 6.12, 10.12, 11.3, 11.15, 11.17_

  - [ ]* 18.3 Testar regressão Athena e integração real do `CallLogParser`
    - Criar `tests/agent_logic_curation/test_athena_occurrence_integration.py` usando cópia fixture mínima do documento/log para catálogo descoberto, fallback, Stage, Prompt, Tool, segunda chamada, finalize e riscos preliminares.
    - Confirmar que `CallLogParser` continua sendo a única fonte semântica e que dados não capturados são gaps, não valores inferidos.
    - _Requisitos: 3.7, 6.1–6.12, 12.1–12.17, 17.3_

  - [ ]* 18.4 Executar regressão automatizada do dashboard e parsers existentes
    - Estender os testes de integração para executar toda a suíte atual de `CurationStore`, dashboard, ORK, VPL e VOCI junto à feature, sem alterar contratos legados.
    - Cobrir banco contendo somente `curation_reports`, migração repetida e rollback da feature sem perda dos relatórios.
    - _Requisitos: 16.1–16.6, 17.1–17.7_

  - [ ]* 18.5 Testar garantias de segurança sem execução nem rede
    - Criar `tests/agent_logic_curation/test_security_boundaries.py` com monitor de rede e sentinelas para provar que importação, inspeção, validação e exportação não executam `Action_Code`, não invocam Tool/endpoint e não transmitem dados.
    - Verificar logs operacionais sem raw/prompt/código/texto/segredo, arquivos temporários limpos e revelação somente após commit da auditoria.
    - _Requisitos: 11.10, 18.3–18.10_

  - [ ]* 18.6 Testar ciclo de exportação, reimportação, rollback e concorrência ponta a ponta
    - Criar `tests/agent_logic_curation/test_export_reimport_integration.py` para export sem mudança byte-idêntico, export alterado/reparse, pacote com JSON idêntico, nova identidade na reimportação, reversão seletiva e originais anteriores intactos.
    - Injetar falhas de validação, commit e streaming e competir revisões para provar ausência de artefato parcial, download indevido ou sobrescrita.
    - _Requisitos: 1.6, 13.4, 14.4, 15.1–15.12, 17.5, 17.6_

- [ ] 19. Checkpoint final — validar toda a implementação
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- A linguagem de implementação é Python 3.11+, determinada explicitamente pelo design; Flask/Jinja/Bootstrap, SQLite, pytest e Hypothesis existentes devem ser reutilizados.
- Tarefas marcadas com `*` são opcionais e podem ser ignoradas para um MVP; tarefas de implementação sem `*` são obrigatórias.
- Cada Property 1–48 possui exatamente uma subtarefa PBT própria, um único teste Hypothesis, `@settings(max_examples=100)` ou mais e a tag de rastreabilidade exigida.
- Os testes baseados em propriedades complementam, e não substituem, testes unitários por exemplo, integração, regressão e segurança.
- `Action_Code` deve permanecer texto não confiável: nenhuma tarefa autoriza execução, compilação executável, importação dinâmica, subprocesso, socket ou chamada externa.
- O `Source_Schema` é carregado apenas quando existir localmente; nenhuma tarefa cria regras autoritativas a partir do perfil Athena.
- A migração é somente aditiva. `.config.kiro`, `requirements.md`, `design.md`, `curation_reports` e o comportamento legado devem permanecer preservados.
- Checkpoints devem usar execução única, por exemplo `pytest`, sem servidor, watcher ou aplicação interativa.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["1.5", "1.6", "2.2"] },
    { "id": 3, "tasks": ["2.3"] },
    { "id": 4, "tasks": ["2.4", "2.5"] },
    { "id": 5, "tasks": ["2.6", "2.7", "2.8", "2.9"] },
    { "id": 6, "tasks": ["4.1"] },
    { "id": 7, "tasks": ["4.2", "4.4"] },
    { "id": 8, "tasks": ["4.3"] },
    { "id": 9, "tasks": ["4.5", "4.6", "4.7", "4.8", "4.9", "4.10", "4.11"] },
    { "id": 10, "tasks": ["5.1"] },
    { "id": 11, "tasks": ["5.2", "5.3"] },
    { "id": 12, "tasks": ["5.4", "5.5", "5.6", "5.7", "5.8"] },
    { "id": 13, "tasks": ["6.1", "6.3", "6.4"] },
    { "id": 14, "tasks": ["6.2"] },
    { "id": 15, "tasks": ["6.5", "6.6", "6.7", "6.8", "6.9", "6.10", "6.11"] },
    { "id": 16, "tasks": ["8.1"] },
    { "id": 17, "tasks": ["8.2", "8.3"] },
    { "id": 18, "tasks": ["8.4", "8.5", "8.6"] },
    { "id": 19, "tasks": ["9.1"] },
    { "id": 20, "tasks": ["9.2"] },
    { "id": 21, "tasks": ["9.3", "9.4", "9.5", "9.6", "9.7", "9.8"] },
    { "id": 22, "tasks": ["10.1"] },
    { "id": 23, "tasks": ["10.2", "10.3", "10.4"] },
    { "id": 24, "tasks": ["10.5", "10.6", "10.7", "10.8", "10.9", "10.10", "10.11", "10.12", "10.13"] },
    { "id": 25, "tasks": ["11.1"] },
    { "id": 26, "tasks": ["11.2"] },
    { "id": 27, "tasks": ["11.3", "11.4", "11.5", "11.6", "11.7", "11.8"] },
    { "id": 28, "tasks": ["13.1"] },
    { "id": 29, "tasks": ["13.2", "13.3"] },
    { "id": 30, "tasks": ["13.4", "13.5", "13.6", "13.7", "13.8"] },
    { "id": 31, "tasks": ["14.1"] },
    { "id": 32, "tasks": ["14.2"] },
    { "id": 33, "tasks": ["14.3"] },
    { "id": 34, "tasks": ["14.4", "14.5", "14.6", "14.7"] },
    { "id": 35, "tasks": ["15.1"] },
    { "id": 36, "tasks": ["15.2"] },
    { "id": 37, "tasks": ["15.3", "15.4", "15.5"] },
    { "id": 38, "tasks": ["16.1"] },
    { "id": 39, "tasks": ["16.2"] },
    { "id": 40, "tasks": ["16.3"] },
    { "id": 41, "tasks": ["16.4"] },
    { "id": 42, "tasks": ["17.1"] },
    { "id": 43, "tasks": ["17.2", "17.4"] },
    { "id": 44, "tasks": ["17.3"] },
    { "id": 45, "tasks": ["17.5", "17.6"] },
    { "id": 46, "tasks": ["18.1", "18.2", "18.3", "18.4", "18.5", "18.6"] }
  ]
}
```
