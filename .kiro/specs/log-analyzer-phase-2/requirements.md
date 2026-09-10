# Requirements Document

## Introduction

Este documento especifica a **Fase 2 do Analisador_de_Logs**. A entrega evolui a estrutura
extensível implementada na Fase 1 para interpretar dados reais de **VPL** e **ORK**, localizar e
relacionar identificadores técnicos de uma chamada, construir uma linha do tempo comum e aplicar
somente classificações sustentadas por exemplos rotulados. A Fase 2 deve reutilizar os contratos
de plugin, o registro de aplicações, o pipeline, os modelos de resultado, as categorias e a CLI da
Fase 1, adicionando comportamento sem redesenhar o núcleo sem necessidade.

### Fatos confirmados pelas amostras e pelo usuário

- O escopo funcional novo desta entrega abrange VPL e ORK.
- Existe um único Cenário_Dourado rotulado pelo usuário como **SUCESSO**.
- Neste documento, o Identificador_de_Cenario real é representado exclusivamente pelo placeholder
  anonimizado `<CALL_ID>`.
- O mesmo Identificador_de_Cenario aparece no VPL no contexto de um canal SIP e no ORK nos campos
  `TelecomCallId` e `CallId`.
- Os timestamps do VPL não possuem offset explícito e devem ser interpretados no
  Fuso_Horario_VPL `America/Sao_Paulo`.
- Os timestamps do ORK possuem offset explícito `-03:00` nas amostras avaliadas.
- As duas amostras contêm Linhas_de_Continuacao e Blocos_Multiline sem repetição de um
  Cabecalho_Completo em cada linha física.
- As amostras podem conter Dados_Sensiveis, incluindo dados pessoais, telefones, identificadores,
  UUIDs, endereços IP, URLs internas e dados de cliente.

### Limites das evidências disponíveis

O Cenário_Dourado é o único caso rotulado disponível. Esse caso confirma o resultado esperado do
cenário específico, mas não sustenta marcadores universais de sucesso, regras de erro, diagnóstico
universal nem inferência de causa-raiz. Qualquer entrada ou cenário sem correspondência com uma
Regra_Validada deve permanecer `NAO_CLASSIFICADA`. Novas generalizações dependem de amostras
adicionais de sucesso e erro, rotuladas e incorporadas segundo a governança definida neste
documento.

### Escopo e fora de escopo

Estão no escopo: parsing real de VPL e ORK, agrupamento multiline, preservação integral,
normalização temporal, extração e vínculo evidenciado de identificadores, busca, correlação,
linha do tempo, classificação restrita ao Cenário_Dourado, explicabilidade, sanitização,
robustez e não regressão da Fase 1.

Estão fora do escopo: novos formatos ou regras para VOCI, diagnóstico universal de erros,
classificação de causa-raiz sem Regra_Validada e generalização de padrões a partir do único caso
rotulado.

## Glossary

- **Analisador_de_Logs**: Sistema completo da Fase 1, evoluído por esta especificação para
  analisar logs reais de VPL e ORK.
- **Fase_1**: Versão existente que fornece arquitetura de plugins, parsers genéricos,
  Registro_de_Aplicacoes, pipeline, correlação, CLI, modelos e categorias.
- **Fase_2**: Evolução especificada neste documento, limitada às novas capacidades para VPL e
  ORK e à preservação de compatibilidade com a Fase 1.
- **VPL**: Aplicação PBX FreeSWITCH que produz uma das amostras de log confirmadas.
- **ORK**: Aplicação orquestradora de agente de IA que produz uma das amostras de log
  confirmadas e se conecta ao VPL.
- **VOCI**: Aplicação de transcrição existente na Fase 1, sem novos formatos ou regras no escopo
  desta entrega.
- **Arquivo_de_Log**: Arquivo de texto de VPL ou ORK fornecido ao Analisador_de_Logs.
- **Linha_Fisica**: Sequência de caracteres delimitada por uma quebra de linha no
  Arquivo_de_Log.
- **Cabecalho_Completo**: Prefixo reconhecível de uma nova Entrada_de_Log que contém os campos
  obrigatórios do formato da Aplicação.
- **Linha_de_Continuacao**: Linha_Fisica sem Cabecalho_Completo que sucede uma Entrada_de_Log
  iniciada no mesmo Arquivo_de_Log.
- **Bloco_Multiline**: Entrada_de_Log composta por uma Linha_Fisica com Cabecalho_Completo e
  zero ou mais Linhas_de_Continuacao contíguas.
- **Entrada_de_Log**: Unidade lógica produzida pelo parser, formada por uma linha com cabeçalho
  ou por um Bloco_Multiline.
- **Entrada_Nao_Interpretada**: Entrada_de_Log cujo cabeçalho ou campos obrigatórios não podem
  ser estruturados, mas cujo Texto_Original permanece preservado.
- **Texto_Original**: Sequência integral de caracteres e quebras de linha que formou uma
  Entrada_de_Log antes de extração, normalização, classificação ou sanitização.
- **Parser_VPL**: Implementação do contrato de parser da Fase 1 responsável pelo formato real do
  VPL.
- **Parser_ORK**: Implementação do contrato de parser da Fase 1 responsável pelo formato real do
  ORK.
- **Timestamp_Original**: Representação temporal exatamente como encontrada no log.
- **Fuso_Horario_VPL**: Zona IANA `America/Sao_Paulo`, aplicada aos timestamps VPL sem offset.
- **Timestamp_Normalizado**: Instante equivalente ao Timestamp_Original convertido para UTC e
  representado com offset explícito.
- **Identificador_de_Cenario**: Valor fornecido pelo usuário para localizar uma chamada ou
  sessão; neste documento é representado por `<CALL_ID>`.
- **Identificador_Tecnico**: Identificador extraído com tipo e proveniência, como identificador
  externo de chamada, identificador SIP, UUID de canal ou UUID de sessão.
- **Campo_Estruturado_Conhecido**: Campo cujo nome e posição são reconhecidos pelo parser. O
  conjunto mínimo inclui, no VPL, identificadores explicitamente rotulados como `CALLID`,
  `CallId` ou `call-id`, o identificador presente no endereço do canal SIP e UUIDs de canal ou
  sessão explicitamente posicionados; no ORK, inclui `TelecomCallId`, `CallId` e UUIDs de sessão
  explicitamente rotulados.
- **Valor_Normalizado_de_Identificador**: Valor de Identificador_Tecnico sem delimitadores,
  aspas ou espaços sintáticos externos, usado para comparação sem diferenciar maiúsculas de
  minúsculas; o valor extraído original também permanece armazenado.
- **Vinculo_Explicito**: Relação entre dois Identificadores_Tecnicos declarada por uma
  Entrada_de_Log que nomeia, mapeia ou contextualiza os dois identificadores como pertencentes à
  mesma chamada, canal ou sessão.
- **Cadeia_de_Vinculos**: Sequência de Vinculos_Explicitos em que cada aresta possui uma
  Entrada_de_Log de evidência.
- **Correlacao**: Associação entre entradas de VPL e ORK sustentada por um identificador
  normalizado compartilhado ou por uma Cadeia_de_Vinculos.
- **Linha_do_Tempo**: Sequência conjunta de Entradas_de_Log ordenada por Timestamp_Normalizado.
- **Categoria_de_Cenario**: Resultado atribuído ao cenário completo: `SUCESSO`, `ERRO` ou
  `NAO_CLASSIFICADA`.
- **Severidade_de_Log**: Nível textual da Entrada_de_Log, como DEBUG, INFO, NOTICE, WARNING ou
  ERROR; não equivale à Categoria_de_Cenario.
- **Exemplo_Rotulado**: Conjunto sanitizado de entradas com uma Categoria_de_Cenario confirmada
  por um Responsavel_de_Dominio.
- **Responsavel_de_Dominio**: Pessoa autorizada a confirmar o rótulo e o escopo de evidência de
  um cenário.
- **Cenario_Dourado**: Único Exemplo_Rotulado atualmente disponível, formado pelas amostras VPL
  e ORK relacionadas por `<CALL_ID>` e confirmado como `SUCESSO`.
- **Regra_Candidata**: Proposta de classificação ainda não autorizada para classificar cenários.
- **Regra_Validada**: Regra de classificação versionada, associada a Exemplo_Rotulado e aprovada
  pelo processo de governança do Catalogo_de_Regras.
- **Catalogo_de_Regras**: Catálogo versionado que mantém Regras_Validadas, escopo, evidências,
  precedência e proveniência.
- **Evidencia**: Referência rastreável e sanitizada a uma entrada, campo, vínculo ou condição que
  justifica uma Correlacao ou Categoria_de_Cenario.
- **Resultado_de_Analise**: Saída estruturada da Fase 1 acrescida, de forma compatível, de
  identificadores, Correlacao, Categoria_de_Cenario, Evidencias e estado de sanitização.
- **Dado_Sensivel**: Dado pessoal ou operacional que não pode ser exposto em texto bruto,
  incluindo telefone, documento, dado de cliente, identificador de chamada, UUID, endereço IP,
  hostname interno, URL interna, credencial, token ou conteúdo de cliente.
- **Representacao_Sanitizada**: Conteúdo no qual cada Dado_Sensivel foi substituído por um
  placeholder tipado e consistente dentro da mesma análise.
- **Fixture_Versionada**: Dado sintético ou Representacao_Sanitizada armazenado no repositório
  para teste automatizado.
- **Governanca_de_Fixtures**: Regras que autorizam ou rejeitam dados preparados para inclusão no
  repositório.
- **Contrato_Publico_da_Fase_1**: Assinaturas de plugins, argumentos da CLI, campos e tipos dos
  modelos, nomes de categorias e comportamentos documentados na Fase 1.
- **Registro_de_Aplicacoes**: Componente existente que associa cada Aplicação aos contratos de
  parser e padrão de análise.
- **CLI**: Interface de linha de comando existente na Fase 1.
- **Causa_Raiz**: Explicação causal de uma falha sustentada por uma Regra_Validada específica;
  não corresponde apenas a uma mensagem ou Severidade_de_Log.

## Requirements

### Requirement 1: Escopo incremental e compatibilidade com a Fase 1

**User Story:** Como mantenedor, quero evoluir a análise real de VPL e ORK sobre a arquitetura
existente, para que a Fase 2 agregue valor sem quebrar integrações da Fase 1.

#### Acceptance Criteria

1. THE Analisador_de_Logs SHALL limitar as novas regras de parsing, correlação e classificação
   da Fase_2 às Aplicações VPL e ORK.
2. WHERE a Aplicação selecionada é VOCI, THE Analisador_de_Logs SHALL manter o comportamento
   genérico fornecido pela Fase_1 sem aplicar regras novas da Fase_2.
3. WHEN a invocação aceita pela CLI da Fase_1 é executada, THE CLI SHALL aceitar os mesmos
   argumentos obrigatórios e as mesmas associações de Aplicação.
4. WHEN um consumidor lê campos definidos no Contrato_Publico_da_Fase_1, THE
   Resultado_de_Analise SHALL fornecer esses campos com os mesmos nomes, tipos e significados.
5. WHEN novos campos da Fase_2 são incluídos no Resultado_de_Analise, THE Analisador_de_Logs
   SHALL incluí-los como extensões aditivas ao Contrato_Publico_da_Fase_1.
6. WHEN um plugin válido segundo o Contrato_Publico_da_Fase_1 é registrado, THE
   Registro_de_Aplicacoes SHALL preservar a capacidade de registrar e resolver o plugin.

### Requirement 2: Parsing do formato real de VPL

**User Story:** Como analista, quero que o VPL seja interpretado conforme o formato observado,
para que cada evento e seu contexto sejam estruturados sem perda de conteúdo.

#### Acceptance Criteria

1. WHEN uma Linha_Fisica de VPL contém um Cabecalho_Completo com timestamp local, percentual
   operacional, Severidade_de_Log delimitada, origem do evento e mensagem, THE Parser_VPL SHALL
   criar uma nova Entrada_de_Log com esses campos estruturados.
2. WHEN um Cabecalho_Completo de VPL contém um UUID antes do Timestamp_Original, THE Parser_VPL
   SHALL extrair o UUID como Identificador_Tecnico do tipo UUID de canal ou sessão com a posição
   da Entrada_de_Log como proveniência.
3. WHEN uma mensagem VPL contém um Identificador_de_Cenario no endereço de um canal SIP, THE
   Parser_VPL SHALL extrair o valor como Identificador_Tecnico externo de chamada.
4. WHEN uma mensagem VPL contém um Campo_Estruturado_Conhecido, THE Parser_VPL SHALL extrair o
   nome do campo, o valor original, o Valor_Normalizado_de_Identificador e a proveniência.
5. IF uma linha que aparenta iniciar um evento VPL contém timestamp, severidade ou mensagem
   inválidos, THEN THE Parser_VPL SHALL produzir uma Entrada_Nao_Interpretada com o
   Texto_Original integral.
6. WHEN uma Entrada_de_Log VPL contém caracteres Unicode válidos, THE Parser_VPL SHALL preservar
   os caracteres no Texto_Original e na mensagem estruturada.

### Requirement 3: Parsing do formato real de ORK

**User Story:** Como analista, quero que o ORK seja interpretado conforme o formato observado,
para que eventos, contexto e identificadores do orquestrador possam ser correlacionados.

#### Acceptance Criteria

1. WHEN uma Linha_Fisica de ORK contém um Cabecalho_Completo com timestamp ISO 8601 e offset,
   host, processo, Severidade_de_Log, logger e mensagem, THE Parser_ORK SHALL criar uma nova
   Entrada_de_Log com esses campos estruturados.
2. WHEN uma Entrada_de_Log ORK contém `TelecomCallId` ou `CallId`, THE Parser_ORK SHALL extrair
   cada campo como Identificador_Tecnico com nome, valor original, valor normalizado e
   proveniência.
3. WHEN uma Entrada_de_Log ORK contém um UUID de sessão explicitamente rotulado no contexto da
   mensagem ou do logger, THE Parser_ORK SHALL extrair o UUID como Identificador_Tecnico de
   sessão.
4. IF uma linha que aparenta iniciar um evento ORK contém timestamp, severidade, logger ou
   mensagem inválidos, THEN THE Parser_ORK SHALL produzir uma Entrada_Nao_Interpretada com o
   Texto_Original integral.
5. WHEN uma Entrada_de_Log ORK contém caracteres Unicode válidos, THE Parser_ORK SHALL preservar
   os caracteres no Texto_Original e na mensagem estruturada.

### Requirement 4: Agrupamento determinístico de conteúdo multiline

**User Story:** Como analista, quero que linhas de continuação pertençam ao evento correto, para
que blocos de protocolo, estruturas e exceções não sejam fragmentados ou descartados.

#### Acceptance Criteria

1. WHEN um Cabecalho_Completo é encontrado, THE Analisador_de_Logs SHALL iniciar uma nova
   Entrada_de_Log e encerrar o Bloco_Multiline anterior do mesmo Arquivo_de_Log.
2. WHEN uma Linha_de_Continuacao sucede uma Entrada_de_Log aberta no mesmo Arquivo_de_Log, THE
   Analisador_de_Logs SHALL anexar a Linha_de_Continuacao a essa Entrada_de_Log.
3. WHEN uma Linha_de_Continuacao é anexada, THE Analisador_de_Logs SHALL preservar a ordem, os
   caracteres e a quebra de linha que a separa da Linha_Fisica anterior.
4. IF uma Linha_Fisica sem Cabecalho_Completo não possui uma Entrada_de_Log anterior no mesmo
   Arquivo_de_Log, THEN THE Analisador_de_Logs SHALL criar uma Entrada_Nao_Interpretada autônoma
   com o Texto_Original integral.
5. WHEN o fim do Arquivo_de_Log é alcançado com um Bloco_Multiline aberto, THE
   Analisador_de_Logs SHALL finalizar o bloco incluindo todas as Linhas_de_Continuacao recebidas.
6. THE Analisador_de_Logs SHALL atribuir cada Linha_Fisica a exatamente uma Entrada_de_Log.

### Requirement 5: Preservação e reversibilidade das entradas

**User Story:** Como auditor, quero conservar o texto recebido e os campos interpretados, para
que resultados possam ser verificados contra a fonte sem perda de informação.

#### Acceptance Criteria

1. THE Analisador_de_Logs SHALL conservar o Texto_Original de toda Entrada_de_Log antes de
   normalização, correlação, classificação ou sanitização de saída.
2. WHEN campos estruturados são extraídos, THE Analisador_de_Logs SHALL manter o Texto_Original
   inalterado na representação interna da Entrada_de_Log.
3. WHEN uma Entrada_Nao_Interpretada é produzida, THE Analisador_de_Logs SHALL manter o
   Arquivo_de_Log, a posição inicial, a posição final e o Texto_Original associados à entrada.
4. WHEN uma Entrada_de_Log interpretada pelo Parser_VPL é impressa e interpretada novamente,
   THE Parser_VPL SHALL reproduzir os mesmos campos estruturados e identificadores extraídos.
5. WHEN uma Entrada_de_Log interpretada pelo Parser_ORK é impressa e interpretada novamente,
   THE Parser_ORK SHALL reproduzir os mesmos campos estruturados e identificadores extraídos.

### Requirement 6: Normalização temporal entre VPL e ORK

**User Story:** Como analista, quero comparar eventos VPL e ORK no mesmo referencial temporal,
para que a sequência da chamada seja cronologicamente coerente.

#### Acceptance Criteria

1. WHEN um Timestamp_Original de VPL não contém offset, THE Analisador_de_Logs SHALL interpretá-lo
   segundo as regras de `America/Sao_Paulo` vigentes na data do evento.
2. WHEN um Timestamp_Original de ORK contém offset explícito, THE Analisador_de_Logs SHALL
   respeitar o offset fornecido no cálculo do instante.
3. WHEN um Timestamp_Original válido é interpretado, THE Analisador_de_Logs SHALL produzir um
   Timestamp_Normalizado em UTC com precisão igual à precisão disponível na origem.
4. WHEN dois Timestamp_Original representam o mesmo instante, THE Analisador_de_Logs SHALL
   produzir Timestamp_Normalizado iguais independentemente da Aplicação de origem.
5. WHEN a Linha_do_Tempo é composta, THE Analisador_de_Logs SHALL ordenar entradas com timestamp
   válido por Timestamp_Normalizado crescente.
6. WHEN duas entradas possuem Timestamp_Normalizado igual, THE Analisador_de_Logs SHALL
   desempatar pelo nome da Aplicação em ordem alfabética e depois pela ordem de leitura no
   Arquivo_de_Log.
7. IF um Timestamp_Original não pode ser resolvido de forma válida segundo as regras temporais da
   Aplicação, THEN THE Analisador_de_Logs SHALL preservar a entrada fora da ordenação cronológica
   e registrar a falha temporal associada à entrada.
8. THE Analisador_de_Logs SHALL manter o Timestamp_Original junto ao Timestamp_Normalizado.

### Requirement 7: Extração de identificadores e semântica de busca

**User Story:** Como usuário, quero buscar uma chamada pelos campos conhecidos ou pelo texto em
que o identificador aparece, para que ocorrências relevantes não dependam de igualdade com a
linha inteira.

#### Acceptance Criteria

1. WHEN um Campo_Estruturado_Conhecido contém um identificador, THE Analisador_de_Logs SHALL
   armazenar o tipo, o nome do campo, o valor original, o Valor_Normalizado_de_Identificador e a
   proveniência do Identificador_Tecnico.
2. WHEN um Identificador_de_Cenario válido é pesquisado, THE Analisador_de_Logs SHALL comparar o
   valor normalizado da consulta por igualdade com todos os Campos_Estruturados_Conhecidos sem
   diferenciar maiúsculas de minúsculas.
3. IF uma Entrada_de_Log não possui Campo_Estruturado_Conhecido igual à consulta normalizada,
   THEN THE Analisador_de_Logs SHALL procurar a ocorrência literal do Identificador_de_Cenario no
   Texto_Original sem diferenciar maiúsculas de minúsculas.
4. WHEN a consulta corresponde a um campo estruturado ou a uma ocorrência literal no
   Texto_Original, THE Analisador_de_Logs SHALL incluir a Entrada_de_Log uma única vez no
   Resultado_de_Analise.
5. WHEN o Identificador_de_Cenario ocupa apenas uma parte da Linha_Fisica ou do Bloco_Multiline,
   THE Analisador_de_Logs SHALL considerar a ocorrência literal válida sem exigir igualdade com o
   Texto_Original completo.
6. WHEN um valor é normalizado para comparação, THE Analisador_de_Logs SHALL preservar o valor
   original extraído para auditoria interna.
7. IF o Identificador_de_Cenario é vazio, contém apenas espaços ou excede o limite de 256
   caracteres da Fase_1, THEN THE Analisador_de_Logs SHALL rejeitar a busca e preservar o estado
   válido anterior.

### Requirement 8: Vínculos entre múltiplos identificadores técnicos

**User Story:** Como analista, quero relacionar identificadores externos, UUIDs de canal e UUIDs
de sessão somente quando houver evidência, para que a chamada seja acompanhada sem criar
associações falsas.

#### Acceptance Criteria

1. WHEN uma Entrada_de_Log declara um Vinculo_Explicito entre dois Identificadores_Tecnicos, THE
   Analisador_de_Logs SHALL registrar o vínculo com os tipos dos identificadores e a entrada de
   Evidencia.
2. WHEN uma chamada possui Identificador_de_Cenario, UUID de canal e UUID de sessão ligados por
   Vinculos_Explicitos, THE Analisador_de_Logs SHALL manter os três valores como identificadores
   distintos pertencentes à mesma Cadeia_de_Vinculos.
3. WHEN uma consulta corresponde a um Identificador_Tecnico de uma Cadeia_de_Vinculos, THE
   Analisador_de_Logs SHALL incluir as entradas alcançáveis pela cadeia e registrar cada vínculo
   percorrido como Evidencia.
4. IF dois identificadores apenas coexistem sem declaração de relação semântica, THEN THE
   Analisador_de_Logs SHALL mantê-los sem Vinculo_Explicito.
5. IF uma associação entre identificadores se baseia somente em proximidade temporal, ordem de
   linhas ou similaridade textual, THEN THE Analisador_de_Logs SHALL manter os identificadores
   sem vínculo.
6. IF Vinculos_Explicitos contraditórios conectam um identificador a cenários distintos, THEN THE
   Analisador_de_Logs SHALL marcar a associação como ambígua e impedir que a associação ambígua
   sustente uma classificação.

### Requirement 9: Correlação VPL–ORK e linha do tempo comum

**User Story:** Como analista, quero correlacionar os eventos VPL e ORK da mesma chamada, para
que eu visualize o cenário entre as duas Aplicações em ordem temporal.

#### Acceptance Criteria

1. WHEN VPL e ORK contêm o mesmo Valor_Normalizado_de_Identificador, THE Analisador_de_Logs
   SHALL marcar as entradas correspondentes como correlacionadas.
2. WHEN entradas VPL e ORK são conectadas por uma Cadeia_de_Vinculos, THE Analisador_de_Logs
   SHALL marcar as entradas alcançáveis pela cadeia como correlacionadas.
3. WHEN o Cenário_Dourado é analisado com o placeholder `<CALL_ID>`, THE Analisador_de_Logs SHALL
   correlacionar o identificador do canal SIP do VPL com os campos `TelecomCallId` e `CallId` do
   ORK.
4. WHEN uma Correlacao VPL–ORK é estabelecida, THE Analisador_de_Logs SHALL incluir as entradas
   selecionadas das duas Aplicações em uma Linha_do_Tempo comum.
5. WHEN uma Correlacao é apresentada, THE Analisador_de_Logs SHALL identificar se a base foi um
   valor compartilhado ou uma Cadeia_de_Vinculos.
6. IF nenhuma Evidencia sustenta uma Correlacao VPL–ORK, THEN THE Analisador_de_Logs SHALL
   indicar que nenhuma correlação foi encontrada e preservar separadamente as entradas das duas
   Aplicações.
7. IF os dados de VPL ou ORK estão ausentes ou não podem ser interpretados, THEN THE
   Analisador_de_Logs SHALL produzir o resultado parcial da Aplicação disponível e identificar a
   lacuna de correlação.

### Requirement 10: Classificação limitada a regras respaldadas por dados

**User Story:** Como responsável de domínio, quero que classificações sejam produzidas apenas
por regras sustentadas por exemplos rotulados, para que o sistema não apresente conclusões sem
evidência.

#### Acceptance Criteria

1. WHEN uma Regra_Candidata é proposta, THE Catalogo_de_Regras SHALL exigir ao menos um
   Exemplo_Rotulado que demonstre todas as condições utilizadas pela regra.
2. WHEN uma Regra_Validada é ativada, THE Catalogo_de_Regras SHALL registrar identificador único,
   versão, Categoria_de_Cenario, Aplicações abrangidas, condições de Evidencia, exemplos de
   suporte, precedência e aprovação do Responsavel_de_Dominio.
3. IF um cenário não corresponde integralmente a uma Regra_Validada, THEN THE
   Analisador_de_Logs SHALL atribuir `NAO_CLASSIFICADA` à Categoria_de_Cenario.
4. IF uma Entrada_de_Log possui Severidade_de_Log de erro sem correspondência com uma
   Regra_Validada de cenário, THEN THE Analisador_de_Logs SHALL preservar a severidade e manter a
   Categoria_de_Cenario independente desse valor.
5. IF nenhuma Regra_Validada sustenta uma Causa_Raiz, THEN THE Analisador_de_Logs SHALL informar
   que a Causa_Raiz não foi determinada.
6. WHEN múltiplas Regras_Validadas correspondem ao mesmo cenário, THE Analisador_de_Logs SHALL
   aplicar a precedência versionada no Catalogo_de_Regras.

### Requirement 11: Classificação e evidência do Cenário Dourado

**User Story:** Como usuário, quero que o caso confirmado seja reconhecido como sucesso, para
que a primeira regra real reproduza o ground truth disponível sem extrapolá-lo.

#### Acceptance Criteria

1. WHEN a Fixture_Versionada sanitizada do Cenário_Dourado é analisada, THE
   Analisador_de_Logs SHALL atribuir `SUCESSO` à Categoria_de_Cenario.
2. WHEN o Cenário_Dourado é classificado como `SUCESSO`, THE Analisador_de_Logs SHALL associar a
   classificação a uma Regra_Validada específica e versionada.
3. WHEN o Cenário_Dourado é classificado como `SUCESSO`, THE Analisador_de_Logs SHALL apresentar
   Evidencia sanitizada proveniente de VPL e ORK.
4. WHEN o Cenário_Dourado é classificado como `SUCESSO`, THE Analisador_de_Logs SHALL apresentar
   a Evidencia que sustenta a Correlacao entre as duas Aplicações.
5. IF um cenário contém somente parte das condições da Regra_Validada do Cenário_Dourado e não
   corresponde a outra Regra_Validada, THEN THE Analisador_de_Logs SHALL atribuir
   `NAO_CLASSIFICADA` ao cenário.
6. THE Catalogo_de_Regras SHALL registrar que a Regra_Validada do Cenário_Dourado possui, nesta
   entrega, suporte de um único Exemplo_Rotulado.

### Requirement 12: Governança e ampliação do catálogo de regras

**User Story:** Como responsável de domínio, quero controlar a inclusão e a generalização de
regras, para que novos padrões de sucesso ou erro tenham proveniência e cobertura conhecidas.

#### Acceptance Criteria

1. THE Catalogo_de_Regras SHALL registrar como lacuna a necessidade de amostras adicionais
   rotuladas de sucesso e erro para generalizar padrões além do Cenário_Dourado.
2. WHEN uma Regra_Candidata é proposta para uso generalizado, THE Catalogo_de_Regras SHALL
   exigir um conjunto mínimo de amostras e critérios de diversidade documentados antes da
   ativação.
3. IF nenhuma amostra de erro foi rotulada, THEN THE Catalogo_de_Regras SHALL manter ausentes as
   Regras_Validadas de Categoria_de_Cenario `ERRO` e de Causa_Raiz.
4. WHEN um novo Exemplo_Rotulado é incorporado, THE Catalogo_de_Regras SHALL registrar o rótulo,
   a origem sanitizada, a data da validação e o Responsavel_de_Dominio.
5. WHEN as condições de uma Regra_Validada são alteradas, THE Catalogo_de_Regras SHALL criar uma
   nova versão sem substituir o histórico da versão anterior.
6. WHEN uma nova versão de regra é proposta, THE Catalogo_de_Regras SHALL exigir a avaliação de
   todos os Exemplos_Rotulados aplicáveis antes da ativação.
7. IF duas Regras_Candidatas possuem condições sobrepostas sem precedência definida, THEN THE
   Catalogo_de_Regras SHALL rejeitar a ativação até que a precedência seja documentada.

### Requirement 13: Explicabilidade e rastreabilidade

**User Story:** Como analista, quero entender por que um cenário foi correlacionado e
classificado, para que eu possa auditar o resultado sem expor dados sensíveis.

#### Acceptance Criteria

1. WHEN uma Categoria_de_Cenario diferente de `NAO_CLASSIFICADA` é atribuída, THE
   Resultado_de_Analise SHALL incluir o identificador e a versão da Regra_Validada aplicada.
2. WHEN uma Categoria_de_Cenario diferente de `NAO_CLASSIFICADA` é atribuída, THE
   Resultado_de_Analise SHALL incluir as condições da regra satisfeitas e as Evidencias
   correspondentes.
3. WHEN uma Evidencia de entrada é apresentada, THE Resultado_de_Analise SHALL incluir a
   Aplicação, a posição da entrada, o Timestamp_Original, o Timestamp_Normalizado, o campo ou
   condição relevante e uma Representacao_Sanitizada.
4. WHEN uma Cadeia_de_Vinculos sustenta uma Correlacao, THE Resultado_de_Analise SHALL listar os
   vínculos percorridos e a entrada de Evidencia de cada vínculo.
5. WHEN a Categoria_de_Cenario é `NAO_CLASSIFICADA`, THE Resultado_de_Analise SHALL informar que
   nenhuma Regra_Validada correspondeu integralmente ao cenário.
6. WHEN Severidade_de_Log e Categoria_de_Cenario são apresentadas, THE Resultado_de_Analise
   SHALL identificá-las como conceitos distintos.
7. IF a Causa_Raiz não possui Regra_Validada, THEN THE Resultado_de_Analise SHALL apresentar o
   estado "não determinada" sem produzir hipótese causal.

### Requirement 14: Sanitização e proteção de dados sensíveis

**User Story:** Como responsável por segurança, quero que dados sensíveis sejam mascarados em
saídas e fixtures, para que a análise possa ser auditada e testada sem expor informações brutas.

#### Acceptance Criteria

1. WHEN um Resultado_de_Analise é exibido, exportado ou registrado em diagnóstico, THE
   Analisador_de_Logs SHALL substituir cada Dado_Sensivel por um placeholder tipado antes da
   saída.
2. WHEN o mesmo Dado_Sensivel aparece mais de uma vez na mesma análise, THE
   Analisador_de_Logs SHALL usar o mesmo placeholder em todas as ocorrências dessa análise.
3. WHEN Dados_Sensiveis de tipos diferentes são sanitizados, THE Analisador_de_Logs SHALL usar
   placeholders que distingam ao menos identificador de chamada, UUID, telefone, documento,
   endereço IP, hostname interno, URL interna, credencial e dado de cliente.
4. WHEN uma Evidencia é sanitizada, THE Analisador_de_Logs SHALL preservar nomes de campos,
   estrutura, ordem temporal e relações necessárias para reproduzir o comportamento analisado.
5. WHEN uma Fixture_Versionada é criada a partir de uma amostra real, THE
   Governanca_de_Fixtures SHALL exigir a substituição de todos os Dados_Sensiveis por valores
   sintéticos ou placeholders tipados.
6. IF uma fixture candidata contém Dado_Sensivel bruto, THEN THE Governanca_de_Fixtures SHALL
   rejeitar a inclusão da fixture no repositório e identificar somente o tipo de dado detectado.
7. IF a sanitização de uma saída não pode ser concluída, THEN THE Analisador_de_Logs SHALL
   suprimir o conteúdo bruto e retornar uma mensagem de falha sem Dado_Sensivel.
8. THE Governanca_de_Fixtures SHALL proibir o uso das amostras brutas locais como
   Fixture_Versionada.

### Requirement 15: Robustez diante de dados incompletos ou malformados

**User Story:** Como usuário, quero obter resultados parciais e íntegros quando parte dos logs é
inválida, para que uma falha localizada não elimine evidências válidas.

#### Acceptance Criteria

1. IF uma Entrada_de_Log não pode ser interpretada, THEN THE Analisador_de_Logs SHALL preservar
   a Entrada_Nao_Interpretada e continuar o processamento das entradas seguintes.
2. IF o Parser_VPL falha em uma entrada, THEN THE Analisador_de_Logs SHALL continuar o
   processamento das demais entradas VPL e ORK.
3. IF o Parser_ORK falha em uma entrada, THEN THE Analisador_de_Logs SHALL continuar o
   processamento das demais entradas ORK e VPL.
4. IF uma sequência de caracteres não pode ser decodificada sem perda, THEN THE
   Analisador_de_Logs SHALL registrar a posição da falha e preservar uma referência segura ao
   conteúdo original sem expô-lo na saída.
5. IF uma Entrada_de_Log não possui Timestamp_Normalizado, THEN THE Analisador_de_Logs SHALL
   mantê-la no Resultado_de_Analise em uma coleção identificada como sem ordenação temporal.
6. WHEN Arquivos_de_Log válidos e inválidos são analisados juntos, THE Analisador_de_Logs SHALL
   produzir resultados para todos os arquivos válidos e uma falha identificada para cada arquivo
   inválido.
7. WHEN um Arquivo_de_Log contém linhas repetidas, THE Analisador_de_Logs SHALL preservar cada
   ocorrência e sua ordem de leitura.
8. WHEN são processados até 100 Arquivos_de_Log de até 500 MB cada, THE Analisador_de_Logs SHALL
   preservar os limites de entrada aceitos pela Fase_1.

### Requirement 16: Resultado e CLI compatíveis e seguros

**User Story:** Como usuário da CLI, quero receber a nova análise no formato familiar da Fase 1,
para que eu possa adotar a Fase 2 sem refazer meu fluxo de uso.

#### Acceptance Criteria

1. WHEN a análise VPL–ORK é concluída, THE Resultado_de_Analise SHALL manter agrupamento por
   Aplicação, linha do tempo, categoria por entrada, contagens, mensagens e erros definidos na
   Fase_1.
2. WHEN uma análise da Fase_2 é concluída, THE Resultado_de_Analise SHALL acrescentar
   Categoria_de_Cenario, identificadores extraídos, vínculos, Correlacao, Evidencias, versão do
   Catalogo_de_Regras e estado de sanitização.
3. WHEN a CLI apresenta uma Categoria_de_Cenario, THE CLI SHALL exibir `SUCESSO`, `ERRO` ou
   `NAO_CLASSIFICADA` sem substituir a Severidade_de_Log das entradas.
4. WHEN a CLI apresenta identificadores ou Evidencias, THE CLI SHALL exibir somente a
   Representacao_Sanitizada.
5. WHEN a mesma entrada e a mesma versão do Catalogo_de_Regras são analisadas repetidamente, THE
   Analisador_de_Logs SHALL produzir a mesma classificação, ordenação e justificativa.
6. IF a apresentação da CLI falha, THEN THE CLI SHALL preservar o Resultado_de_Analise em memória
   e retornar uma mensagem sanitizada de falha.

### Requirement 17: Limites de diagnóstico e declaração de cobertura

**User Story:** Como analista, quero que o sistema declare o que conseguiu concluir e o que
permanece desconhecido, para que ausência de evidência não seja confundida com diagnóstico.

#### Acceptance Criteria

1. WHEN uma análise é concluída, THE Resultado_de_Analise SHALL informar as Aplicações
   efetivamente analisadas e as Aplicações ausentes ou inválidas.
2. WHEN uma análise é concluída, THE Resultado_de_Analise SHALL informar a versão do
   Catalogo_de_Regras usada para classificação.
3. WHERE somente os dados desta entrega estão disponíveis, THE Resultado_de_Analise SHALL
   declarar que a cobertura rotulada contém um cenário de sucesso e nenhum cenário de erro.
4. IF o usuário solicita diagnóstico de erro sem Regra_Validada aplicável, THEN THE
   Analisador_de_Logs SHALL retornar Categoria_de_Cenario `NAO_CLASSIFICADA` e Causa_Raiz "não
   determinada".
5. IF o usuário solicita análise específica de novos formatos ou regras de VOCI, THEN THE
   Analisador_de_Logs SHALL informar que essa capacidade está fora do escopo da Fase_2.
6. IF uma conclusão depende de uma regra não sustentada por Exemplo_Rotulado, THEN THE
   Analisador_de_Logs SHALL omitir a conclusão e registrar a ausência de Regra_Validada.

## Suposições e Questões em Aberto

### Suposições adotadas

- `America/Sao_Paulo` é a origem temporal normativa para todo timestamp VPL sem offset nesta
  entrega.
- UTC é o referencial comum da Linha_do_Tempo; o Timestamp_Original continua disponível para
  auditoria.
- O vínculo direto pelo mesmo valor normalizado entre VPL e ORK e cada aresta explicitamente
  evidenciada de uma Cadeia_de_Vinculos são bases válidas de correlação.
- A Fase 2 pode acrescentar campos opcionais aos modelos, mas não remover nem reinterpretar os
  campos públicos da Fase 1.
- A amostra sanitizada do Cenário_Dourado será a única base inicial para uma regra de `SUCESSO`.

### Questões ainda abertas

- Quais variações de cabeçalho VPL e ORK, além das observadas nas duas amostras, devem integrar a
  gramática suportada?
- Quais condições exatas da Evidencia sanitizada do Cenário_Dourado serão aprovadas pelo
  Responsavel_de_Dominio como necessárias e suficientes para a regra de escopo restrito?
- Quantas amostras e quais dimensões de diversidade serão exigidas para promover uma regra de
  sucesso ou erro ao uso generalizado?
- Qual tolerância, se houver, deve ser aplicada a desvio de relógio entre VPL e ORK sem usar o
  tempo como evidência de vínculo?
- Por quanto tempo logs brutos podem ser retidos, quem pode acessá-los e quais controles externos
  ao Analisador_de_Logs governam essa retenção?
- Os placeholders sanitizados precisam permanecer estáveis entre execuções autorizadas ou apenas
  dentro de cada Resultado_de_Analise?
- Quais amostras rotuladas de erro e respectivas causas-raiz serão fornecidas para a próxima
  expansão do Catalogo_de_Regras?
