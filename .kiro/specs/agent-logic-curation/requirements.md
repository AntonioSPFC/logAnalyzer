# Requirements Document

## Introduction

Esta fase especifica a feature `agent-logic-curation`: uma interface web para curadoria e manutenção controlada da lógica de um agente digital. A feature deve permitir que curadores investiguem uma ocorrência, compreendam a lógica que influenciou o comportamento observado, proponham uma correção em uma cópia de trabalho, comparem o antes e o depois, validem a correção, criem uma versão auditável e exportem um documento completo. Esta fase não inclui design técnico, plano de implementação, código, telas prontas, execução de ações importadas, publicação do agente ou alteração do JSON original.

A análise do workspace encontrou a aplicação Flask existente, templates Bootstrap, persistência SQLite de relatórios de curadoria e o `CallLogParser`. Também encontrou `logs/OpsCloud-AthenaAdaStudio.json`, uma cópia textual equivalente e `logs/olos-ai-orchestrator.log`. O log contém uma execução do próprio `OpsCloud-AthenaAdaStudio`, identificada pelo CallId `0018c022303de447`, com carregamento e normalização de `node (ork.json)`, actions, modelos, estágios, prompts, transcrições, falha HTTP 400 do categorizador, fallback de staging, transições, chamada e resultado de `consultar_dependentes`, segunda chamada ao modelo e resposta final. Essas evidências fundamentam os requisitos, mas não substituem a preservação formal de uma cópia original imutável.

O perfil de referência informado para o artefato é: app `OpsCloud-AthenaAdaStudio`, type `digitalAgent`, version 22, specVersion 1, historyNumber 23, published `true`, fluxos `Main` e `Stages Module`, ASR Voci, TTS ElevenLabs, múltiplos modelos e 12 estágios. Esses valores são dados de referência a serem descobertos e exibidos a partir do artefato importado; a solução não deve fixar nomes, quantidades ou valores como constantes.

## Preconditions and Scope Boundaries

1. A análise integral e reprodutível exige uma cópia imutável do JSON original, com bytes e impressão digital de integridade preservados. O arquivo presente no workspace é um candidato a essa cópia e somente passa a ser o artefato de referência após a ingestão controlada definida neste documento.
2. A validação integral de schema exige um Source_Schema autoritativo compatível com a `specVersion` importada. Na ausência desse schema, a solução pode executar validações sintáticas, estruturais e referenciais, mas deve declarar a validação de schema como incompleta.
3. A determinação segura da fonte canônica exige evidências explícitas no documento para separar conteúdo publicado, rascunhos e histórico. Empates ou conflitos exigem decisão registrada do curador.
4. Requests, responses, prompts e resultados somente podem ser apresentados como observados quando existirem evidências nos logs importados. Ausência de log deve ser representada como lacuna de evidência, não como valor inferido.
5. As inconsistências preliminares são hipóteses de validação. A feature deve detectá-las e explicá-las sem corrigir automaticamente o artefato original.

## Glossary

- **JSON**: Formato textual de objetos, arrays e valores usado pelo artefato do agente.
- **CallId**: Identificador de uma chamada com exatamente 16 caracteres hexadecimais, validado pela regra existente do Dashboard e usado para correlacionar linhas de log de uma Occurrence.
- **ORK**: Orquestrador do agente digital que carrega a configuração normalizada e executa a lógica conversacional.
- **VPL**: Componente de telefonia FreeSWITCH cujos logs podem ser correlacionados aos logs ORK.
- **ASR**: Serviço que converte áudio do cliente em transcrição textual.
- **TTS**: Serviço que converte uma resposta textual do agente em áudio.
- **Request**: Dados enviados a um componente, preservados como valor original ou como valor processado quando os logs registram as duas formas.
- **Response**: Dados retornados por um componente, preservados como valor original ou como valor processado quando os logs registram as duas formas.
- **Action_Code**: Código-fonte embutido no Agent_Document para implementar ou despachar uma Tool.
- **Sensitive_Data_Policy**: Lista configurada de campos, padrões de log e regras de mascaramento usada para identificar Sensitive_Values.
- **Curation_System**: A feature web `agent-logic-curation` integrada à aplicação existente.
- **Artifact_Importer**: Componente que recebe, identifica e registra um artefato de agente e seus dados de integridade.
- **Original_Artifact**: Sequência exata e imutável de bytes importados como fonte de uma sessão de curadoria.
- **Integrity_Fingerprint**: Hash SHA-256, tamanho em bytes e nome de origem usados para verificar a identidade do Original_Artifact.
- **Agent_Document**: Estrutura JSON obtida pela interpretação do Original_Artifact, incluindo campos conhecidos e desconhecidos.
- **Agent_JSON_Parser**: Componente que interpreta o Original_Artifact como JSON e preserva tipos, ordem e origem dos elementos.
- **Agent_JSON_Printer**: Componente que produz uma representação JSON indentada de forma determinística sem alterar o significado de um Agent_Document.
- **Agent_Exporter**: Componente que serializa uma Work_Version para um JSON completo e separa dados do agente de dados da interface.
- **Source_Schema**: Definição autoritativa de campos, tipos, valores permitidos, obrigatoriedade e regras estruturais para uma `specVersion`.
- **Source_Path**: Identificador inequívoco da posição de um elemento no Agent_Document, incluindo índices de arrays.
- **Logic_Element**: Elemento do Agent_Document que participa da configuração ou do comportamento do agente.
- **Structure_Catalog**: Inventário hierárquico dos Logic_Elements, respectivos Source_Paths, tipos, relações e proveniência.
- **Graph_Node**: Nó presente na representação gráfica de fluxos do Agent_Document.
- **Normalized_ORK_Node**: Nó ou seção que contém a configuração normalizada consumida pelo orquestrador ORK.
- **Flow**: Conjunto nomeado de nós e conexões que organiza a lógica de navegação do agente.
- **Stage**: Estado conversacional identificável que possui instruções, regras, referências ou transições.
- **Prompt**: Instrução textual geral, de staging, de finalize, de call-disposition ou específica de Stage.
- **Rule**: Condição e resultado que influenciam resposta, uso de Tool, disponibilidade ou transição.
- **Tool**: Função declarada para consulta ou alteração externa durante uma interação do agente.
- **Tool_Contract**: Nome, descrição, parâmetros, campos obrigatórios, tipos e formato de resultado declarados para uma Tool.
- **Canonical_Source_Resolver**: Componente que classifica candidatos de lógica como Published_Source, Draft_Source, Historical_Source ou Unresolved_Source.
- **Published_Source**: Candidato explicitamente marcado ou referenciado pelo formato de origem como lógica publicada.
- **Draft_Source**: Candidato explicitamente marcado ou referenciado pelo formato de origem como rascunho editável.
- **Historical_Source**: Candidato mantido como versão anterior ou registro histórico no formato de origem.
- **Unresolved_Source**: Candidato cuja função canônica não pode ser determinada por evidência explícita do documento.
- **Canonical_Source**: Candidato confirmado como base da comparação e da correção em uma sessão de curadoria.
- **Work_Copy**: Cópia editável derivada de uma Canonical_Source e mantida separada do Original_Artifact.
- **Work_Version**: Registro imutável e auditável de uma Work_Copy após comparação e validação.
- **Change_Set**: Conjunto ordenado de alterações com Source_Path, valor anterior e valor posterior.
- **Log_Parser**: Parser existente que filtra e estrutura eventos de logs ORK ou VPL por CallId.
- **Occurrence**: Execução do agente identificada por CallId e pelas linhas de log relacionadas.
- **Occurrence_Inspector**: Componente que apresenta eventos, requests, responses, prompts, decisões, Tools e erros de uma Occurrence.
- **Execution_Event**: Evento cronológico extraído de uma linha ou bloco de log.
- **Raw_Evidence**: Conteúdo original do log, arquivo de origem, posição e timestamp que sustentam uma afirmação.
- **Processed_Value**: Valor produzido após normalização, substituição, categorização, execução de Tool ou outra transformação registrada.
- **Evidence_Gap**: Indicação explícita de que um dado necessário não foi observado nas fontes disponíveis.
- **Traceability_Engine**: Componente que relaciona Execution_Events, Raw_Evidence e Logic_Elements.
- **Traceability_Link**: Relação registrada entre uma evidência e um ou mais Source_Paths, acompanhada da justificativa e do estado de confirmação.
- **Complaint**: Descrição do problema relatado pelo curador para uma Occurrence.
- **Observed_Behavior**: Comportamento demonstrado por Raw_Evidence e Processed_Values.
- **Expected_Behavior**: Resultado verificável que o curador esperava na Occurrence.
- **Correction**: Alteração proposta em um ou mais Logic_Elements para tratar uma Complaint.
- **Expected_Result**: Resultado verificável previsto após a Correction.
- **Curation_Record**: Registro estruturado da cadeia Complaint → Observed_Behavior → Logic_Element responsável → Correction → Expected_Result.
- **Existing_Curation_Store**: Instância SQLite atual do `CurationStore`, responsável pelos relatórios textuais existentes.
- **Existing_Curation_Report**: Relatório textual já persistido pelo Existing_Curation_Store com CallId, texto e timestamps.
- **Structured_Editor**: Editor que oferece controles específicos para cada tipo de Logic_Element e JSON bruto como fallback.
- **Validation_Engine**: Componente que analisa sintaxe, schema, referências, contratos, regras, fluxos e incompatibilidades sem executar código importado.
- **Validation_Finding**: Diagnóstico com código, severidade, mensagem, Source_Paths, evidências e orientação de correção.
- **Blocking_Error**: Validation_Finding que impede a classificação da Work_Copy como pronta para exportação final.
- **Warning**: Validation_Finding que exige ciência do curador, mas não representa violação comprovada de integridade.
- **Version_Store**: Persistência SQLite de Curation_Records, Work_Versions, decisões, validações e eventos de auditoria.
- **Version_Comparator**: Componente que calcula diferenças e impacto entre Original_Artifact, Work_Copies ou Work_Versions.
- **Audit_Event**: Registro de somente acréscimo contendo ator, instante UTC, ação, entidade afetada e resultado.
- **UI_Metadata**: Dados exclusivos da experiência de curadoria, como seleção, comentários, estados de tela, auditoria e links de reclamação.
- **Source_Native_Metadata**: Campo já pertencente ao formato original do agente, incluindo versionamento, publicação e histórico quando presente.
- **Semantic_Equivalence**: Igualdade de chaves, tipos, valores e ordem de arrays após interpretação JSON, independentemente de espaços em branco externos.
- **Sensitive_Value**: Valor classificado por política configurada como credencial, identificador pessoal ou dado operacional restrito.
- **Existing_Web_Architecture**: App factory Flask, rotas, templates Jinja, Bootstrap, SQLite e módulos de parser presentes no workspace.

## Requirements

### Requirement 1: Ingestão imutável do artefato original

**User Story:** Como curador, quero trabalhar sobre uma cópia verificável do agente, para que a curadoria não altere nem confunda a fonte original.

#### Acceptance Criteria

1. WHEN um arquivo candidato é importado com sucesso, THE Artifact_Importer SHALL registrar, em um único Original_Artifact, a sequência integral e inalterada dos bytes lidos, uma cópia exata do nome de origem recebido, o tamanho igual à contagem desses bytes, o hash SHA-256 calculado sobre essa mesma sequência e identificado como Integrity_Fingerprint, e um instante UTC situado entre o início e a conclusão da importação.
2. WHILE um Original_Artifact estiver registrado, THE Curation_System SHALL rejeitar qualquer tentativa de alterar seus bytes ou os valores registrados no momento da importação, indicar que o artefato é somente para leitura e preservar esses bytes e valores.
3. WHEN a reabertura de um Original_Artifact é solicitada, THE Artifact_Importer SHALL recalcular o Integrity_Fingerprint sobre a sequência completa dos bytes registrados e comparar o resultado por igualdade com o Integrity_Fingerprint registrado.
4. IF o Integrity_Fingerprint recalculado difere do Integrity_Fingerprint registrado, THEN THE Artifact_Importer SHALL atribuir à tentativa de reabertura um resultado observável de falha de integridade, indicá-lo ao curador, não concluir a reabertura, impedir a criação de uma Work_Copy baseada no conteúdo divergente e manter inalterados o Original_Artifact e as Work_Copies existentes.
5. WHILE nenhum Original_Artifact correspondente ao JSON original estiver registrado, THE Curation_System SHALL indicar ao curador que a importação é uma pré-condição pendente e manter desabilitadas a análise integral, a edição e a exportação desse JSON.
6. THE Curation_System SHALL assegurar que, após toda sequência finita de zero ou mais operações de criação, edição, descarte, versionamento ou exportação de Work_Copies, os bytes, o nome de origem, o tamanho, o Integrity_Fingerprint e o instante UTC de cada Original_Artifact permaneçam idênticos aos valores registrados no momento da importação. *(Propriedade de invariância para teste baseado em propriedades.)*
7. IF a leitura integral dos bytes, o cálculo do SHA-256 ou o registro completo de qualquer dado exigido para um Original_Artifact não é concluído durante uma tentativa de importação, THEN THE Artifact_Importer SHALL indicar ao curador a falha da importação, não registrar um Original_Artifact parcial e manter inalterados todos os Original_Artifacts existentes.
8. WHEN a comparação confirma que o Integrity_Fingerprint recalculado é idêntico ao Integrity_Fingerprint registrado, THE Artifact_Importer SHALL concluir a reabertura usando os bytes registrados, sem alterar os bytes nem os valores do Original_Artifact.
9. IF a leitura integral dos bytes registrados, o recálculo do Integrity_Fingerprint ou a comparação não é concluída durante uma tentativa de reabertura, THEN THE Artifact_Importer SHALL atribuir à tentativa um resultado observável de falha de verificação de integridade, indicá-lo ao curador, não concluir a reabertura, impedir a criação de uma Work_Copy a partir desse conteúdo e manter inalterados o Original_Artifact e as Work_Copies existentes.

### Requirement 2: Interpretação e impressão do JSON do agente

**User Story:** Como curador, quero que o JSON seja interpretado sem perda, para que elementos conhecidos e desconhecidos permaneçam disponíveis.

#### Acceptance Criteria

1. WHEN um Original_Artifact contém JSON sintaticamente válido, THE Agent_JSON_Parser SHALL construir um Agent_Document que preserve cada ocorrência de chave, cada valor e seu tipo JSON sem arredondamento ou truncamento, a ordem de todos os membros de objetos, inclusive daqueles com chaves duplicadas, e a ordem dos elementos de arrays.
2. WHEN o Agent_JSON_Parser encontra um campo desconhecido pelo Source_Schema, THE Agent_JSON_Parser SHALL preservar cada ocorrência do campo, seu valor, seu tipo e seu Source_Path no Agent_Document.
3. WHEN um campo é declarado pelo Source_Schema como JSON embutido em string e o conteúdo da string é JSON sintaticamente válido, THE Agent_JSON_Parser SHALL preservar integralmente a string original e disponibilizar, sem substituí-la, uma interpretação separada associada ao mesmo Source_Path.
4. IF o Original_Artifact contém JSON sintaticamente inválido, THEN THE Agent_JSON_Parser SHALL retornar um resultado que contenha a sequência completa e inalterada dos bytes importados e um diagnóstico com o motivo da falha, o offset em bytes iniciado em 0 e a linha e a coluna iniciadas em 1 da primeira posição que viola a sintaxe JSON ou, em caso de fim inesperado, da posição imediatamente posterior ao último byte.
5. WHEN uma representação formatada de um Agent_Document resultante de uma interpretação bem-sucedida é solicitada, THE Agent_JSON_Printer SHALL produzir JSON sintaticamente válido, usar uma unidade de indentação não vazia e uniforme em todos os níveis de aninhamento e produzir saídas idênticas caractere por caractere em solicitações repetidas para o mesmo Agent_Document.
6. WHEN um Agent_Document resultante de uma interpretação bem-sucedida é impresso e interpretado novamente, THE Agent_JSON_Parser SHALL produzir um segundo Agent_Document com as mesmas ocorrências de chaves, os mesmos valores e tipos JSON, as mesmas ordens de membros de objetos e elementos de arrays, os mesmos campos desconhecidos e as mesmas strings com JSON embutido e respectivas interpretações separadas. *(Propriedade de ida e volta para teste baseado em propriedades.)*
7. WHEN o Agent_JSON_Parser conclui uma interpretação com sucesso, THE Agent_JSON_Parser SHALL atribuir exatamente um Source_Path a cada ocorrência de chave e a cada ocorrência de valor, incluindo cada elemento de array, sem reutilizar um Source_Path entre ocorrências distintas e reproduzindo os mesmos Source_Paths ao interpretar novamente a mesma sequência de bytes.
8. IF um campo é declarado pelo Source_Schema como JSON embutido em string e o conteúdo da string é sintaticamente inválido como JSON, THEN THE Agent_JSON_Parser SHALL preservar integralmente a string original e seu Source_Path no Agent_Document, não disponibilizar uma interpretação separada para o campo e associar ao campo um diagnóstico que indique a invalidade sintática.

### Requirement 3: Catálogo completo da estrutura e da hierarquia

**User Story:** Como curador, quero compreender a organização integral do agente, para que eu localize a lógica relevante sem percorrer JSON bruto.

#### Acceptance Criteria

1. WHEN um Agent_Document é carregado, THE Structure_Catalog SHALL inventariar separadamente cada ocorrência de Logic_Element, inclusive ocorrências com tipo ou nome iguais, registrando para cada uma seu Source_Path, seu tipo, seu nome somente quando presente e, pelos respectivos Source_Paths, seu pai direto e todos os seus filhos diretos, com a ausência de pai ou de filhos explicitamente marcada.
2. WHEN um Agent_Document com metadados de raiz é carregado, THE Structure_Catalog SHALL exibir cada valor presente de app, type, version, specVersion, historyNumber e published associado ao campo correspondente exatamente como consta na raiz do Agent_Document, sem associar valor aos campos ausentes.
3. WHEN um Agent_Document que contém Flows, Graph_Nodes, Normalized_ORK_Nodes, branches ou conexões é carregado, THE Structure_Catalog SHALL representar as relações de pai e filho presentes entre essas ocorrências e, para cada conexão explícita, os elementos relacionados, vinculando cada ocorrência e relação aos respectivos Source_Paths de origem sem acrescentar relações ausentes do Agent_Document.
4. WHEN um Agent_Document que contém Prompts, Rules, Stages, Tools, parâmetros, mensagens, modelos, ASR, TTS, fillers, paths, error handling ou configurações é carregado, THE Structure_Catalog SHALL classificar separadamente cada ocorrência na categoria indicada por sua designação ou por seu agrupamento explícito no Agent_Document e associar a classificação ao Source_Path da mesma ocorrência.
5. WHEN um Agent_Document contendo um Logic_Element com conteúdo estruturado e conteúdo textual bruto é carregado, THE Structure_Catalog SHALL disponibilizar, sob o mesmo Source_Path, uma representação com todos os campos e valores estruturados presentes e outra com o conteúdo textual bruto integral e sem alteração, sem que uma representação substitua a outra.
6. IF um campo esperado pelo Source_Schema está ausente da localização esperada no Agent_Document, THEN THE Structure_Catalog SHALL marcar o campo como ausente, não lhe associar valor substituto e manter no catálogo todos os valores e Logic_Elements presentes.
7. WHEN o perfil `OpsCloud-AthenaAdaStudio` é importado, THE Structure_Catalog SHALL exibir exatamente os nomes presentes e as contagens de ocorrências do Agent_Document importado, inclusive quando divergirem dos dados do perfil de referência, sem incluir nomes ou ocorrências presentes somente na referência.
8. WHEN um Agent_Document que contém Flows, Graph_Nodes, Normalized_ORK_Nodes, branches ou conexões é carregado, THE Structure_Catalog SHALL exibir separadamente, para cada um desses tipos presente, a contagem exata de suas ocorrências no Agent_Document, contando uma única vez cada ocorrência localizada em um Source_Path distinto.

### Requirement 4: Resolução segura da fonte canônica

**User Story:** Como curador, quero distinguir conteúdo publicado, rascunho e histórico, para que uma correção seja aplicada à fonte pretendida.

#### Acceptance Criteria

1. WHEN o Canonical_Source_Resolver analisa um Agent_Document que contém candidatos com marcadores ou referências definidos pelo Source_Schema como evidência explícita de publicação, rascunho ou histórico, THE Canonical_Source_Resolver SHALL atribuir a cada candidato exatamente uma classificação entre Published_Source, Draft_Source, Historical_Source e Unresolved_Source e associar à classificação os Source_Paths correspondentes e os marcadores ou referências considerados.
2. THE Canonical_Source_Resolver SHALL basear cada classificação em campos e referências do formato de origem reconhecidos pelo Source_Schema, sem permitir que a posição no arquivo ou o fato de um candidato possuir a data mais recente determine isoladamente a classificação.
3. WHEN o Canonical_Source_Resolver analisa conteúdo histórico que contém `promptText`, `allPrompts`, `drafts` ou campos classificados pelo Source_Schema como históricos, THE Canonical_Source_Resolver SHALL apresentar cada estrutura de conteúdo localizada em Source_Paths distintos como um candidato separado com exatamente uma classificação entre Published_Source, Draft_Source, Historical_Source e Unresolved_Source.
4. IF dois ou mais candidatos possuem valores de conteúdo diferentes e satisfazem o mesmo conjunto de marcadores de Published_Source definido pelo Source_Schema, THEN THE Canonical_Source_Resolver SHALL classificar a decisão sobre a Canonical_Source como não resolvida e sinalizar a prontidão para exportação final como bloqueada enquanto nenhuma Canonical_Source tiver sido confirmada para essa decisão.
5. IF nenhum marcador ou referência presente em um candidato corresponder a uma regra do Source_Schema para Published_Source, Draft_Source ou Historical_Source, THEN THE Canonical_Source_Resolver SHALL classificar o candidato como Unresolved_Source e associar aos respectivos Source_Paths a indicação de que nenhuma evidência de classificação correspondente foi encontrada.
6. WHEN o curador confirma exatamente uma Canonical_Source entre os candidatos envolvidos em uma decisão canônica não resolvida e fornece uma justificativa não vazia, THE Version_Store SHALL registrar a decisão, a identificação do curador, o instante da confirmação em UTC, os Source_Paths do candidato confirmado, os Source_Paths dos demais candidatos envolvidos e a justificativa como UI_Metadata externo ao Agent_Document.
7. WHEN uma Canonical_Source é confirmada, THE Curation_System SHALL criar a Work_Copy com conteúdo inicial idêntico ao conteúdo integral do candidato confirmado e manter inalterados, nos Source_Paths originais do Agent_Document, todos os candidatos, inclusive os não confirmados.
8. IF um candidato satisfaz integralmente os marcadores definidos pelo Source_Schema para duas ou mais classificações entre Published_Source, Draft_Source e Historical_Source e o Source_Schema não define uma única classificação para essa combinação, THEN THE Canonical_Source_Resolver SHALL classificar o candidato como Unresolved_Source e associar aos respectivos Source_Paths todos os marcadores ou referências conflitantes.

### Requirement 5: Mapeamento de dependências, referências e duplicações

**User Story:** Como curador, quero visualizar dependências e duplicações, para que uma mudança não produza efeitos ocultos.

#### Acceptance Criteria

1. WHEN o Structure_Catalog identifica no Agent_Document uma referência entre Logic_Elements, THE Structure_Catalog SHALL construir uma relação direcionada do Logic_Element que contém a referência para o Logic_Element indicado como destino, incluindo referências de ou para Flows, Stages, Prompts, Rules, Tools, parâmetros, variáveis, mensagens e configurações.
2. WHEN uma relação direcionada com origem e destino resolvidos é construída, THE Structure_Catalog SHALL registrar para essa relação o Source_Path da origem, o Source_Path do destino e o tipo da relação.
3. WHEN o Structure_Catalog identifica representações da mesma configuração em pelo menos um Normalized_ORK_Node e pelo menos um Graph_Node, THE Structure_Catalog SHALL apresentar cada representação em uma entrada separada da mesma comparação, com o valor, o Source_Path e a proveniência como Normalized_ORK_Node ou Graph_Node, e classificar o estado de equivalência como equivalente somente se todos os valores forem iguais ou como divergente se ao menos dois valores forem diferentes.
4. IF o estado de equivalência de representações duplicadas for divergente, THEN THE Structure_Catalog SHALL criar um Validation_Finding que indique a divergência, associe o valor de cada representação ao respectivo Source_Path e preserve todas as representações sem alteração.
5. WHEN o curador inicia a resolução de um Validation_Finding de divergência, THE Curation_System SHALL apresentar cada valor candidato com seu Source_Path e solicitar que o curador selecione e confirme explicitamente o valor a manter e cada representação a alterar, mantendo todas as representações inalteradas até essa confirmação.
6. IF uma referência do Agent_Document indicar um destino que não corresponde a nenhum Logic_Element existente, THEN THE Structure_Catalog SHALL manter a referência no catálogo com o Source_Path de origem e a identificação de destino contida na referência, marcá-la como não resolvida e não associá-la a um Logic_Element de destino.
7. WHEN um Logic_Element é selecionado, THE Structure_Catalog SHALL listar, em categorias separadas, todas as relações cujo destino é o elemento como dependências de entrada, todas as relações e referências não resolvidas cuja origem é o elemento como dependências de saída e todos os Source_Paths de origem das referências cujo destino é o elemento como ocorrências de uso, exibindo o estado resolvido ou não resolvido de cada item e cada categoria mesmo quando não contiver itens.

### Requirement 6: Inspeção cronológica de ocorrências e dados de execução

**User Story:** Como curador, quero inspecionar uma execução real em detalhe, para que a correção seja sustentada por evidências.

#### Acceptance Criteria

1. WHEN o curador seleciona um CallId cujo valor está registrado como CallId em pelo menos uma entrada dos logs configurados, THE Occurrence_Inspector SHALL carregar, por meio do Log_Parser existente, uma Occurrence identificada pelo CallId selecionado e contendo todos os registros que o Log_Parser associar a esse CallId.
2. WHEN uma Occurrence com Execution_Events que possuem timestamps válidos é carregada, THE Occurrence_Inspector SHALL ordenar todos esses eventos por timestamp crescente e, para eventos cujos timestamps representem o mesmo instante, preservar a ordem relativa em que o Log_Parser os leu dos logs configurados. *(Propriedade de ordenação estável para teste baseado em propriedades.)*
3. WHEN um Execution_Event é apresentado, THE Occurrence_Inspector SHALL disponibilizar, associados a esse mesmo evento, o timestamp, o tipo, o conteúdo processado integral, a Raw_Evidence integral, o arquivo de origem e o número da linha ou um Evidence_Gap de posição.
4. WHEN o Log_Parser existente associa uma Request original a uma Request processada, THE Occurrence_Inspector SHALL apresentar os dois valores integrais como um par e, para cada campo cuja presença ou cujo valor difira, indicar se o campo foi alterado, existe apenas na Request original ou existe apenas na Request processada, exibindo os valores observados em cada lado em que estiverem presentes.
5. WHEN o Log_Parser existente associa uma Response original a uma Response processada, THE Occurrence_Inspector SHALL apresentar os dois valores integrais como um par e, para cada campo cuja presença ou cujo valor difira, indicar se o campo foi alterado, existe apenas na Response original ou existe apenas na Response processada, exibindo os valores observados em cada lado em que estiverem presentes.
6. WHEN os logs identificam um Prompt, um Stage, um modelo, uma decisão de categorização, staging, finalize ou call-disposition, THE Occurrence_Inspector SHALL apresentar cada item identificado com sua categoria, seu valor integral observado, o CallId selecionado, a Raw_Evidence, o arquivo de origem, o número da linha ou Evidence_Gap de posição e sua posição na sequência da Occurrence.
7. WHEN os logs registram uma chamada de Tool, THE Occurrence_Inspector SHALL agrupar somente os dados que o Log_Parser existente associar à mesma chamada, manter em grupos distintos os registros com identificadores de chamada diferentes e disponibilizar, em cada grupo, nome, identificador da chamada, argumentos integrais, resultado integral, mensagens identificadas nos logs como pertencentes à segunda chamada, erro e cada latência observada com o respectivo valor e unidade registrados.
8. WHEN os logs registram transcrição, resposta do assistente, transição, fallback, Warning ou erro, THE Occurrence_Inspector SHALL incluir cada Execution_Event correspondente na Occurrence, associado à sua Raw_Evidence e na posição determinada pelos critérios 2 e 11.
9. IF um dado exigido pelos critérios 3 a 8 não aparecer nas fontes de log configuradas que foram examinadas para o CallId selecionado, THEN THE Occurrence_Inspector SHALL exibir um Evidence_Gap que identifique o dado ausente, o item da Occurrence ao qual ele pertence e todas as fontes examinadas, sem substituir o dado por um valor inferido.
10. IF uma linha de log examinada não puder ser interpretada pelo Log_Parser existente, THEN THE Occurrence_Inspector SHALL preservar seu conteúdo integral e inalterado como Raw_Evidence, associá-lo ao arquivo de origem e ao número da linha, mantê-lo na ordem relativa de leitura e apresentar um Evidence_Gap de interpretação.
11. IF um Execution_Event não possuir timestamp ou seu timestamp não puder ser interpretado como válido pelo Log_Parser existente, THEN THE Occurrence_Inspector SHALL apresentá-lo após todos os eventos com timestamps válidos, preservar sua ordem relativa de leitura entre os eventos sem timestamp válido, exibir um Evidence_Gap de timestamp e não lhe atribuir um timestamp inferido.
12. IF uma fonte de log configurada não puder ser examinada durante o carregamento da Occurrence, THEN THE Occurrence_Inspector SHALL preservar os dados carregados das demais fontes e exibir um Evidence_Gap que identifique a fonte não examinada e a impossibilidade de verificar seu conteúdo, sem declarar como ausentes nessa fonte os dados solicitados.

### Requirement 7: Rastreabilidade entre comportamento e lógica responsável

**User Story:** Como curador, quero relacionar eventos do log aos trechos do agente, para que eu encontre a causa provável de uma reclamação.

#### Acceptance Criteria

1. WHEN um Execution_Event contém um identificador, Source_Path, referência ou valor registrado de Stage, Prompt, Rule, Tool, parâmetro, modelo ou configuração, THE Traceability_Engine SHALL localizar, para cada registro, todos e somente os Logic_Elements que contenham um registro da mesma categoria e do mesmo tipo com valor exatamente igual, sem aceitar correspondência parcial.
2. WHEN um Traceability_Link é criado, THE Traceability_Engine SHALL registrar a Raw_Evidence sem alteração, todos os Source_Paths dos candidatos, a regra de correspondência aplicada e o estado não resolvido.
3. IF exatamente um Logic_Element for localizado como candidato para um Execution_Event, THEN THE Traceability_Engine SHALL permitir navegação do Execution_Event para esse Logic_Element e desse Logic_Element para o Execution_Event.
4. IF dois ou mais Logic_Elements forem localizados como candidatos para o mesmo identificador, Source_Path, referência ou valor registrado, THEN THE Traceability_Engine SHALL apresentar todos os candidatos com o respectivo Source_Path e a evidência da correspondência e solicitar que o curador confirme um candidato, sem atribuir responsabilidade antes da confirmação.
5. IF a aplicação da regra de correspondência exata a cada identificador, Source_Path, referência e valor registrado no Execution_Event resultar em zero Logic_Elements candidatos, THEN THE Traceability_Engine SHALL registrar um Evidence_Gap associado ao Execution_Event e à Raw_Evidence avaliada, sem criar um Traceability_Link confirmado nem atribuir responsabilidade a qualquer Logic_Element.
6. WHEN uma transformação entre um valor original e um Processed_Value está registrada na Raw_Evidence, THE Traceability_Engine SHALL representar uma sequência ordenada contendo o valor original como primeiro item, cada valor intermediário registrado na ordem observada e o Processed_Value como último item, associando cada transição consecutiva à Raw_Evidence que a registra.
7. WHEN o curador confirma um Traceability_Link, THE Version_Store SHALL registrar exatamente um Audit_Event que identifique o Traceability_Link, o Execution_Event, o Logic_Element confirmado e o curador, mantendo o Audit_Event fora do Agent_Document e o conteúdo do Agent_Document inalterado.
8. WHEN o curador confirma um Logic_Element candidato para um Traceability_Link não resolvido, THE Traceability_Engine SHALL associar o Logic_Element confirmado ao Traceability_Link, alterar o estado para confirmado e preservar a Raw_Evidence, os Source_Paths candidatos e a regra de correspondência registrados.
9. IF a Raw_Evidence não registrar uma transição entre dois valores consecutivos da sequência, THEN THE Traceability_Engine SHALL registrar um Evidence_Gap para essa transição sem inferir valores intermediários nem atribuir responsabilidade a um Logic_Element.

### Requirement 8: Registro estruturado da cadeia de curadoria

**User Story:** Como curador, quero documentar problema, causa, correção e resultado esperado, para que a manutenção seja verificável.

#### Acceptance Criteria

1. WHEN o curador solicita a criação de uma curadoria para uma Occurrence, THE Curation_System SHALL criar um Curation_Record vinculado ao CallId e ao Original_Artifact dessa Occurrence.
2. THE Curation_Record SHALL conter Complaint, Observed_Behavior, cada Raw_Evidence associada, Expected_Behavior, cada Source_Path confirmado como responsável, Correction e Expected_Result.
3. IF um Curation_Record não possuir valor registrado para Complaint, Observed_Behavior, Expected_Behavior, Correction ou Expected_Result, possuir somente espaços, tabulações ou quebras de linha em qualquer desses elementos, ou não possuir Raw_Evidence associada, THEN THE Curation_System SHALL manter esse Curation_Record como incompleto e identificar separadamente cada elemento ausente ou vazio.
4. IF o Curation_Record não possuir ao menos um Source_Path com confirmação registrada de responsabilidade, THEN THE Curation_System SHALL manter a relação causal como não resolvida e impedir a classificação desse Curation_Record como pronto para versionamento.
5. WHEN uma Raw_Evidence ou um Source_Path confirmado como responsável é associado a uma Complaint, THE Curation_System SHALL registrar uma relação individual entre a Complaint e o elemento associado e conservar todas as relações previamente registradas para essa Complaint.
6. WHEN uma Correction é associada a uma Complaint, THE Curation_System SHALL registrar uma relação individual entre essa Correction e essa Complaint e conservar as relações da mesma Correction com outras Complaints.
7. WHEN o curador define um Expected_Result, THE Curation_System SHALL solicitar uma condição de sucesso para uma Occurrence de validação que identifique o resultado observável a verificar e declare separadamente o resultado que representa sucesso e o resultado que representa falha.
8. IF um Existing_Curation_Report estiver associado ao CallId, THEN THE Curation_System SHALL apresentá-lo identificado como evidência legada, sem usar essa associação como confirmação de qualquer Source_Path responsável ou de qualquer relação causal entre Complaint, Source_Path e Correction.

### Requirement 9: Fluxo guiado para curadores não desenvolvedores

**User Story:** Como curador não desenvolvedor, quero um fluxo orientado, para que eu conclua a manutenção sem depender de conhecimento da estrutura JSON.

#### Acceptance Criteria

1. WHEN uma sessão de curadoria é iniciada, THE Curation_System SHALL apresentar as nove etapas nesta ordem: selecionar ocorrência → inspecionar interação, requests, responses e Tools → registrar Complaint e Expected_Behavior → localizar lógica → corrigir → comparar → validar → versionar → exportar.
2. WHILE existir ao menos uma etapa posterior pendente na ordem definida no critério 1, WHEN o curador conclui a etapa atual, THE Curation_System SHALL marcar a etapa atual como concluída e indicar como próxima etapa a primeira etapa posterior pendente nessa ordem.
3. IF uma etapa obrigatória possuir um ou mais dados identificados como obrigatórios ainda não preenchidos, THEN THE Curation_System SHALL manter essa etapa como pendente, identificar individualmente cada dado não preenchido e manter cada etapa indicada como dependente desabilitada até que todos esses dados sejam preenchidos.
4. THE Curation_System SHALL permitir que o curador conclua cada uma das nove etapas definidas no critério 1 sem exigir edição direta de JSON bruto.
5. WHEN Occurrence, requests, responses, Tools, Complaint, Expected_Behavior, Logic_Element, Work_Copy, Validation_Finding, Source_Path ou JSON é exibido ao curador, THE Curation_System SHALL fornecer uma explicação em português que defina o significado do termo e sua relação com a etapa atual.
6. WHEN o curador alterna entre Occurrence, Logic_Element, comparação e validação, THE Curation_System SHALL manter os valores e as alterações não versionadas da Work_Copy e as marcações de etapas concluídas idênticos aos respectivos estados imediatamente anteriores à alternância.
7. IF o curador solicita o descarte de uma ou mais alterações não versionadas, THEN THE Curation_System SHALL exibir a quantidade exata de Source_Paths distintos alterados, solicitar confirmação explícita antes de executar o descarte e manter a Work_Copy inalterada até o curador responder à confirmação.
8. WHEN um Validation_Finding é exibido, THE Curation_System SHALL apresentar, com rótulos distintos, valores não vazios em português para severidade, localização, evidência, efeito e ação recomendada, além de um código técnico não vazio.
9. IF o curador rejeita ou cancela a confirmação de descarte, THEN THE Curation_System SHALL manter a Work_Copy e as marcações de etapas concluídas idênticas aos respectivos estados anteriores à solicitação de descarte.
10. WHEN o curador confirma o descarte, THE Curation_System SHALL descartar todas as alterações não versionadas dos Source_Paths contabilizados e deixar a Work_Copy idêntica ao estado versionado vigente no momento da solicitação.
11. WHILE as oito etapas anteriores estão marcadas como concluídas, WHEN o curador conclui a etapa exportar, THE Curation_System SHALL marcar a etapa exportar como concluída e indicar que o fluxo de manutenção foi concluído.

### Requirement 10: Edição estruturada por tipo de elemento

**User Story:** Como curador, quero editores específicos para cada elemento, para que eu altere a lógica com menor risco de erro estrutural.

#### Acceptance Criteria

1. WHILE o curador edita uma Work_Copy selecionada, THE Structured_Editor SHALL aplicar toda alteração aceita somente a essa Work_Copy, mantendo inalteradas a base e as demais Work_Copies.
2. WHEN o curador seleciona para edição um Logic_Element do tipo Prompt, THE Structured_Editor SHALL oferecer campos editáveis para cada propriedade de texto e referência de variável definida no Source_Schema e indicar o escopo geral, de modelo ou de Stage exatamente como declarado nesse schema.
3. WHEN o curador seleciona para edição um Logic_Element do tipo Rule ou condição, THE Structured_Editor SHALL oferecer todos os campos de operandos, operadores, valores, prioridade e resultado declarados para esse elemento no Source_Schema.
4. WHEN o curador seleciona para edição um Logic_Element do tipo Flow ou Stage, THE Structured_Editor SHALL oferecer todos os campos de identificadores, instruções, conexões, condições de transição e destinos declarados para esse elemento no Source_Schema.
5. WHEN o curador seleciona para edição um Logic_Element do tipo Tool_Contract, THE Structured_Editor SHALL oferecer todos os campos de nome, descrição, parâmetros, obrigatoriedade, tipos e formato de resultado declarados para esse elemento no Source_Schema.
6. WHEN o curador seleciona para edição um Logic_Element que contém Action_Code, THE Structured_Editor SHALL oferecer edição textual do Action_Code com os diagnósticos estáticos apresentados fora do conteúdo editável do JSON externo.
7. WHEN o curador seleciona para edição um Logic_Element do tipo configuração, modelo, ASR, TTS ou mensagem, THE Structured_Editor SHALL oferecer controles cujos tipos e opções permitidas correspondam exatamente às restrições aplicáveis declaradas no Source_Schema.
8. IF o tipo do Logic_Element selecionado não possuir editor específico, THEN THE Structured_Editor SHALL oferecer edição em JSON bruto cujo conteúdo editável seja limitado exatamente ao Source_Path selecionado.
9. WHEN uma edição de um Source_Path é aceita, THE Structured_Editor SHALL registrar no Change_Set esse Source_Path e os valores imediatamente anterior e posterior à edição.
10. WHEN exatamente um Source_Path folha é editado e a edição é aceita, THE Structured_Editor SHALL manter inalterados, antes e depois da edição, o conjunto de todos os demais Source_Paths folha e os respectivos valores e tipos. *(Propriedade de localidade da mudança para teste baseado em propriedades.)*
11. WHEN o curador descarta todas as alterações, THE Structured_Editor SHALL restaurar a Work_Copy com o mesmo conjunto de Source_Paths e, em cada Source_Path, o mesmo valor e tipo da base usada na criação. *(Propriedade de ida e volta para teste baseado em propriedades.)*
12. IF uma edição contiver JSON inválido no fallback ou violar qualquer restrição aplicável do Source_Schema, THEN THE Structured_Editor SHALL rejeitar a edição, apresentar uma indicação que identifique o JSON inválido ou a restrição violada e manter inalterados a Work_Copy e o Change_Set.

### Requirement 11: Validação integral antes do versionamento e da exportação

**User Story:** Como curador, quero validar a lógica corrigida, para que erros estruturais e comportamentais conhecidos sejam identificados antes da exportação.

#### Acceptance Criteria

1. WHEN uma Work_Copy é submetida à validação, THE Validation_Engine SHALL verificar a conformidade sintática do JSON externo e de cada JSON embutido declarado pelo Source_Schema aplicável.
2. WHEN uma Work_Copy é validada com um Source_Schema compatível disponível, THE Validation_Engine SHALL verificar, em cada Source_Path abrangido por esse Source_Schema, a presença dos itens obrigatórios, a correspondência dos tipos, a inclusão dos valores nos conjuntos permitidos e o atendimento de todas as restrições estruturais nele declaradas.
3. IF uma validação de Work_Copy for iniciada sem um Source_Schema compatível disponível, THEN THE Validation_Engine SHALL marcar a validação de schema como incompleta e criar um Blocking_Error de pré-condição que indique a ausência do Source_Schema compatível.
4. WHEN uma Work_Copy contendo referências é validada, THE Validation_Engine SHALL verificar, para cada referência, que o destino existe, que seu identificador é único na Work_Copy e que o tipo do destino é compatível com o tipo declarado pela referência.
5. WHEN uma Work_Copy contendo Tool_Contracts é validada, THE Validation_Engine SHALL verificar, para cada Tool_Contract, que existe correspondência entre a declaração e o mapeamento executável, que os nomes, tipos e obrigatoriedade dos parâmetros coincidem e que cada campo de resultado consumido está declarado.
6. WHEN uma Work_Copy contendo Flows e Stages é validada, THE Validation_Engine SHALL verificar que cada Flow possui exatamente um ponto inicial declarado, que cada destino existe, que cada Stage declarado é alcançável a partir do ponto inicial, que não existem referências órfãs e que cada caminho terminal declarado termina em um destino terminal existente e alcançável.
7. WHEN uma Work_Copy contendo variáveis em Prompts, Rules ou mensagens é validada, THE Validation_Engine SHALL verificar que cada ocorrência de variável corresponde a uma definição e a uma fonte de dados presentes no Agent_Document.
8. WHEN a validação identifica duas Rules cujas condições produzem o mesmo resultado lógico para toda entrada permitida pelo Source_Schema aplicável e cujos resultados não podem ser satisfeitos simultaneamente, THE Validation_Engine SHALL criar um Validation_Finding que identifique as duas Rules e os respectivos resultados conflitantes.
9. WHEN a validação identifica valores correspondentes divergentes entre representações da mesma configuração no Normalized_ORK_Node e no Graph_Node, THE Validation_Engine SHALL criar um Validation_Finding que identifique os valores divergentes e as duas proveniências.
10. WHEN uma Work_Copy contendo Action_Code é validada, THE Validation_Engine SHALL limitar a análise à sintaxe, aos nomes, às assinaturas e às relações estáticas, sem executar o Action_Code.
11. WHEN uma verificação identifica, somente com as evidências presentes na Work_Copy e no Source_Schema aplicável, que uma condição explicitamente exigida pelos critérios 1 a 10 não foi satisfeita, THE Validation_Engine SHALL classificar o diagnóstico correspondente como Blocking_Error.
12. IF a confirmação de um risco depender de intenção de negócio ou de evidência ausente na Work_Copy e no Source_Schema aplicável, THEN THE Validation_Engine SHALL classificar o diagnóstico como Warning e indicar a intenção ou evidência necessária para confirmá-lo.
13. WHEN a mesma Work_Copy e o mesmo Source_Schema são validados repetidamente sem alterações entre as execuções, THE Validation_Engine SHALL produzir a mesma quantidade e a mesma ordem de diagnósticos, com códigos, severidades e Source_Paths idênticos nas posições correspondentes, sem acumular diagnósticos de execuções anteriores nem alterar a Work_Copy. *(Propriedade de determinismo e idempotência para teste baseado em propriedades.)*
14. WHEN qualquer valor da Work_Copy ou do Source_Schema usado no resultado de validação anterior é alterado, ou esse Source_Schema é substituído, THE Curation_System SHALL marcar esse resultado como desatualizado antes de permitir uma nova classificação de prontidão.
15. IF o resultado de validação referente ao estado atual da Work_Copy e ao Source_Schema aplicável estiver ausente, desatualizado ou incompleto, ou contiver ao menos um Blocking_Error, THEN THE Curation_System SHALL impedir a classificação da Work_Copy como pronta para versionamento final ou exportação final.
16. WHEN uma validação termina, THE Validation_Engine SHALL produzir um resultado que indique se a validação está completa ou incompleta e liste cada diagnóstico identificado com seu código, sua severidade e o Source_Path aplicável.
17. WHILE o resultado de validação do estado atual da Work_Copy estiver ausente, desatualizado ou incompleto, ou contiver ao menos um Blocking_Error, WHEN o versionamento final ou a exportação final for solicitado, THE Curation_System SHALL rejeitar a operação, indicar a condição impeditiva e manter a Work_Copy sem alterações, sem produzir o versionamento ou a exportação solicitada.

### Requirement 12: Cobertura dos riscos preliminares do agente Athena

**User Story:** Como mantenedor, quero que riscos já identificados sejam verificações explícitas, para que a primeira curadoria não dependa de inspeção manual informal.

#### Acceptance Criteria

1. IF um Action_Code Python contém uma referência ao identificador exato `false` e nenhuma construção Python válida associa esse nome no escopo local da referência, THEN THE Validation_Engine SHALL criar um Blocking_Error que identifica o Source_Path, a posição da referência, o token `false` e sua incompatibilidade com o literal Python `False`.
2. IF uma referência a `e` ocorre no corpo de um bloco `except`, o cabeçalho desse bloco não associa a exceção com `as e` e nenhuma associação Python válida torna `e` resolvível no ponto da referência, THEN THE Validation_Engine SHALL criar um Blocking_Error que identifica o Source_Path, a posição e a referência não definida.
3. IF dois ou mais literais de string aparecem consecutivamente dentro de uma lista Python sem vírgula entre eles e o Python os interpreta como um único valor por concatenação implícita, THEN THE Validation_Engine SHALL criar um Warning de possível separador ausente que identifica o Source_Path e as posições inicial e final de cada literal participante.
4. IF duas ocorrências da mesma Tool, correspondentes ao mesmo parâmetro pela posição declarada ou por referência explícita, usam respectivamente `grau_parentesco` e `parentesco` entre a declaração, a implementação ou o uso, THEN THE Validation_Engine SHALL criar um Validation_Finding de contrato incompatível que identifica ambos os nomes e os Source_Paths de todas as ocorrências envolvidas.
5. IF duas ocorrências do mesmo parâmetro, correspondentes pela posição declarada ou por referência explícita, usam respectivamente `codigo_especialidade` e `especialidade` entre a declaração, a implementação ou o uso, THEN THE Validation_Engine SHALL criar um Validation_Finding de contrato incompatível que identifica ambos os nomes e os Source_Paths de todas as ocorrências envolvidas.
6. IF dois caminhos de retorno alcançáveis de uma mesma Tool expõem, para o mesmo resultado declarado ou para a mesma entrada de consumidor, respectivamente `especialidadeOUT` e `especialidade`, THEN THE Validation_Engine SHALL criar um Validation_Finding de formato de retorno inconsistente que identifica os dois caminhos de retorno, seus Source_Paths e cada consumidor correspondente identificado.
7. IF dois ou mais artefatos dentre definição de Stage, Prompt, Rule, transição, Normalized_ORK_Node ou Graph_Node estão vinculados ao mesmo Stage e usam valores textualmente distintos para o identificador desse Stage, THEN THE Validation_Engine SHALL criar um Validation_Finding que lista cada valor distinto, o tipo de artefato e todos os respectivos Source_Paths.
8. IF `validate_schedule_cancellation` é referenciado como Stage ou destino e nenhum Stage nem destino declarado possui exatamente esse identificador, THEN THE Validation_Engine SHALL criar um Blocking_Error para cada referência não resolvida que identifica o valor referenciado, o Source_Path e sua posição.
9. IF uma Tool de confirmação é declarada ou exigida e não existe uma cadeia de referências que a vincule tanto a um mapeamento executável quanto a um ponto de invocação em um caminho alcançável a partir de um Stage ou de uma Rule, THEN THE Validation_Engine SHALL criar um Validation_Finding de execução não demonstrada que identifica a Tool, o Source_Path da declaração ou exigência e cada vínculo ausente.
10. IF os logs de uma Occurrence registram que ela alcançou uma Rule que exige uma Tool de confirmação e não contêm registro de invocação dessa Tool entre o alcance da Rule e o último registro disponível da mesma Occurrence, THEN THE Validation_Engine SHALL criar um Warning de execução não observada vinculado à Occurrence, à Rule e à Tool de confirmação esperada.
11. IF uma Rule exige transferência humana e nenhum Tool_Contract, Action_Code ou transição explícita associado a essa Rule declara a transferência humana como ação ou destino, THEN THE Validation_Engine SHALL criar um Validation_Finding de capacidade ausente que identifica a Rule, seu Source_Path e as categorias de artefato verificadas.
12. IF o Stage `flow_start` existe, o Source_Schema aplicável exige `system_prompt_instruction` ou identifica explicitamente um campo equivalente e nenhum desses campos está presente com valor textual que contenha ao menos um caractere diferente de espaço em branco, THEN THE Validation_Engine SHALL criar um Validation_Finding de instrução ausente que identifica o Source_Path do Stage e o campo exigido.
13. IF `nodeValidation.errors` contém um ou mais erros de origem, THEN THE Validation_Engine SHALL criar exatamente um Validation_Finding para cada item, identificando o erro e seu Source_Path correspondente.
14. IF uma mesma combinação de entradas satisfaz simultaneamente as condições de duas Rules de indisponibilidade e essas Rules definem resultados observáveis diferentes para essa combinação, THEN THE Validation_Engine SHALL criar um Validation_Finding de regra incompatível que identifica ambas as Rules, a sobreposição das condições, cada resultado e os Source_Paths envolvidos.
15. WHEN o Validation_Engine detecta qualquer condição de risco definida nesta Requirement, THE Validation_Engine SHALL manter o Original_Artifact idêntico ao recebido.
16. IF `nodeValidation.result` é falso e `nodeValidation.errors` está ausente ou não contém itens, THEN THE Validation_Engine SHALL criar um Validation_Finding vinculado ao Source_Path do nó validado que indica falha de validação sem erro de origem detalhado.
17. WHEN o Validation_Engine detecta qualquer condição de risco definida nesta Requirement, THE Validation_Engine SHALL apresentar a correção correspondente exclusivamente como proposta na Work_Copy.

### Requirement 13: Comparação antes/depois e análise de impacto

**User Story:** Como curador, quero comparar a correção com a base, para que eu confirme exatamente o que mudará.

#### Acceptance Criteria

1. WHEN a comparação entre a base e a correção resulta em um Change_Set com pelo menos uma alteração, THE Version_Comparator SHALL apresentar todos e somente os Source_Paths presentes no Change_Set, cada um com o valor da base como valor anterior e o valor da correção como valor posterior, indicando a ausência do valor anterior em uma adição e a ausência do valor posterior em uma remoção.
2. WHEN a comparação identifica um Source_Path alterado, THE Version_Comparator SHALL listar, separadamente por categoria, todas e somente as dependências diretas, dependências transitivas, Traceability_Links e Curation_Records vinculados direta ou transitivamente a esse Source_Path na base ou na correção, apresentando uma lista vazia para cada categoria sem itens.
3. WHEN a comparação identifica alteração em conteúdo textual estruturado, THE Version_Comparator SHALL apresentar cada diferença por linha como adição quando houver somente valor posterior, remoção quando houver somente valor anterior ou substituição quando houver valores anterior e posterior distintos, juntamente com os valores brutos anterior e posterior do Source_Path correspondente.
4. WHEN um Change_Set é aplicado à base e, sem alteração intermediária, o Change_Set inverso é aplicado ao Agent_Document resultante, THE Version_Comparator SHALL produzir um Agent_Document cuja comparação com a base resulte em um Change_Set vazio. *(Propriedade de reversibilidade para teste baseado em propriedades.)*
5. WHEN a ordem da base e da correção é invertida na comparação, THE Version_Comparator SHALL produzir exatamente o mesmo conjunto de Source_Paths alterados e, para cada Source_Path, trocar entre si os valores anterior e posterior da comparação original, inclusive as indicações de ausência de valor. *(Propriedade de simetria para teste baseado em propriedades.)*
6. IF duas versões são semanticamente equivalentes, THEN THE Version_Comparator SHALL retornar um Change_Set contendo zero Source_Paths alterados.
7. WHEN o curador solicita validação final, THE Curation_System SHALL apresentar o resumo contendo todos os Source_Paths alterados e seus valores anterior e posterior e a lista de impacto separada em dependências diretas, dependências transitivas, Traceability_Links e Curation_Records, e SHALL concluir a validação somente após receber a confirmação explícita do curador referente a ambos.

### Requirement 14: Versionamento e histórico auditável

**User Story:** Como responsável pela manutenção, quero versões imutáveis e auditáveis, para que cada decisão possa ser reconstruída.

#### Acceptance Criteria

1. WHILE uma Work_Copy não contiver Blocking_Error vigente e diferir da versão pai em pelo menos um Source_Path, WHEN o curador solicitar seu versionamento, THE Version_Store SHALL criar exatamente uma Work_Version imutável com identificador único entre as Work_Versions existentes, referência à versão pai, identificação do curador solicitante, instante do versionamento em UTC, Integrity_Fingerprint da base associada à Work_Copy, Change_Set contendo todas e somente as alterações de Source_Path em relação à versão pai, todos os Curation_Records vinculados à Work_Copy e o resultado da validação vigente no instante do versionamento.
2. WHILE nenhum Source_Path tiver sido adicionado, removido ou alterado em uma Work_Copy em relação à versão pai, WHEN o curador solicitar seu versionamento, THE Version_Store SHALL concluir a solicitação sem criar uma Work_Version, manter inalterada a quantidade de Work_Versions e informar ao curador a ausência de alteração. *(Propriedade de idempotência para teste baseado em propriedades.)*
3. THE Version_Store SHALL acrescentar cada novo Audit_Event após os Audit_Events existentes, sem alterar, substituir, reordenar ou excluir qualquer Audit_Event anterior.
4. WHEN o curador solicitar a reversão dos valores selecionados de uma Work_Version, THE Version_Store SHALL criar exatamente uma nova Work_Version cujo Change_Set contenha todas e somente as alterações necessárias para restaurar esses valores aos registrados na Work_Version selecionada, sem alterar os valores não selecionados em relação à versão pai da nova Work_Version.
5. WHEN o curador consultar o histórico, THE Version_Store SHALL apresentar todas as Work_Versions registradas e, para cada uma, o identificador, a versão pai quando não inicial, o curador, o instante UTC, o Integrity_Fingerprint, o Change_Set, os Curation_Records, o resultado da validação e todos os Complaints, decisões canônicas, reconhecimentos de Warning e exportações a ela vinculados.
6. WHEN o curador selecionar exatamente duas Work_Versions distintas, THE Curation_System SHALL apresentar, por meio do Version_Comparator, uma comparação identificada pelas duas Work_Versions e contendo todos e somente os Source_Paths cuja presença ou valor difira entre elas, com a presença e o valor correspondentes em cada Work_Version.
7. WHEN o curador fornecer o reconhecimento de um Warning de uma Work_Version e uma justificativa contendo pelo menos um caractere que não seja espaço em branco, THE Version_Store SHALL registrar o reconhecimento e a justificativa vinculados ao Warning, à Work_Version e ao curador antes de autorizar a exportação final dessa Work_Version.
8. WHEN a cadeia de Work_Versions for verificada, THE Version_Store SHALL garantir que ela contenha exatamente uma Work_Version inicial sem versão pai, que cada Work_Version não inicial referencie exatamente uma versão pai existente e que o seguimento sucessivo das referências de parentesco a partir de qualquer Work_Version termine na Work_Version inicial sem ciclos. *(Propriedade de integridade da cadeia para teste baseado em propriedades.)*
9. IF for solicitada a alteração ou a exclusão de uma Work_Version existente, THEN THE Version_Store SHALL rejeitar a solicitação, preservar todos os valores e vínculos da Work_Version e informar ao solicitante que a operação foi rejeitada por imutabilidade.
10. IF o curador solicitar o versionamento de uma Work_Copy com Blocking_Error vigente, THEN THE Version_Store SHALL rejeitar a solicitação sem criar uma Work_Version, preservar a Work_Copy e informar ao curador que o Blocking_Error vigente impede o versionamento.
11. IF o curador solicitar a exportação final de uma Work_Version que contenha pelo menos um Warning sem reconhecimento registrado ou sem justificativa registrada contendo pelo menos um caractere que não seja espaço em branco, THEN THE Version_Store SHALL impedir a exportação, preservar a Work_Version e informar ao curador quais Warnings ainda exigem reconhecimento ou justificativa.

### Requirement 15: Importação e exportação completas sem perda

**User Story:** Como mantenedor, quero importar e exportar o agente completo, para que a correção preserve integralmente conteúdo não alterado e permaneça utilizável fora da interface.

#### Acceptance Criteria

1. WHEN o curador solicita a exportação de uma Work_Version sem Blocking_Error vigente e com todos os Warning vigentes reconhecidos, THE Agent_Exporter SHALL produzir um documento JSON que contenha todas e somente as chaves, os valores e os tipos JSON do Agent_Document da versão selecionada, preserve a ordem dos elementos de cada array e exclua apenas UI_Metadata.
2. THE Agent_Exporter SHALL excluir todo o UI_Metadata do documento JSON do agente e preservar esse UI_Metadata sem alteração, associado à mesma Work_Version, em pelo menos um destes locais: Version_Store ou artefato de auditoria separado do documento JSON do agente.
3. WHEN o curador solicita a exportação de uma Work_Version sem Blocking_Error vigente, com todos os Warning vigentes reconhecidos e cujo Change_Set está vazio, THE Agent_Exporter SHALL produzir uma sequência de bytes com o mesmo comprimento e o mesmo byte em cada posição que o Original_Artifact. *(Propriedade de identidade de ida e volta para teste baseado em propriedades.)*
4. WHEN o Agent_Exporter serializa uma Work_Version cujo Change_Set altera um ou mais Source_Paths, THE Agent_Exporter SHALL preservar, fora desses Source_Paths e em relação ao Original_Artifact, todas as chaves, os valores e os tipos JSON, a ordem dos elementos de arrays e a ordem relativa dos membros de objetos. *(Propriedade de preservação de quadro para teste baseado em propriedades.)*
5. WHEN o Agent_Exporter serializa uma Work_Version cujo Change_Set não altera nenhum Source_Path de Source_Native_Metadata, THE Agent_Exporter SHALL preservar, em relação ao Original_Artifact, todas e somente as chaves, os valores e os tipos JSON de Source_Native_Metadata, a ordem dos elementos de seus arrays e a ordem relativa dos membros de seus objetos.
6. WHEN um documento JSON disponibilizado pelo Agent_Exporter é importado novamente, THE Agent_JSON_Parser SHALL produzir um Agent_Document cujo conteúdo, após desconsiderar UI_Metadata, tenha todas e somente as mesmas chaves, os mesmos valores e tipos JSON e a mesma ordem dos elementos de arrays que o Agent_Document da Work_Version de origem após desconsiderar UI_Metadata, admitindo diferenças apenas nos caracteres de espaço permitidos pela sintaxe JSON e na ordem dos membros de objetos. *(Propriedade de ida e volta para teste baseado em propriedades.)*
7. WHEN a serialização da Work_Version é concluída, THE Agent_Exporter SHALL verificar, antes de disponibilizar o arquivo, que a sequência de bytes inteira representa exatamente um documento JSON sintaticamente válido.
8. IF a Work_Version selecionada possui um ou mais Blocking_Error vigentes ou pelo menos um Warning vigente não reconhecido, THEN THE Agent_Exporter SHALL impedir a exportação final, não disponibilizar o documento JSON do agente nem o pacote de auditoria dessa tentativa, disponibilizar um relatório de validação que indique cada condição impeditiva e manter inalterados a Work_Version e todos os Original_Artifacts.
9. WHEN o curador solicita um pacote de auditoria de uma Work_Version sem Blocking_Error vigente e com todos os Warning vigentes reconhecidos, THE Agent_Exporter SHALL disponibilizar dois artefatos separados: o documento JSON do agente com a mesma sequência de bytes da exportação final individual dessa Work_Version e um manifesto contendo a identificação da Work_Version, todos os elementos do Change_Set, o resultado da validação que autorizou a exportação e todos os Curation_Records associados à versão.
10. WHEN o documento JSON do agente disponibilizado pelo Agent_Exporter é reimportado como nova base, THE Artifact_Importer SHALL registrar a sequência completa de bytes reimportada como um novo Original_Artifact com identidade distinta e manter registrados, com suas sequências de bytes inalteradas, todos os Original_Artifacts anteriores.
11. IF a validação sintática do conteúdo serializado falha, THEN THE Agent_Exporter SHALL não disponibilizar nenhum documento JSON nem pacote de auditoria dessa tentativa, disponibilizar um relatório de validação que indique a falha de sintaxe e manter inalterados a Work_Version e todos os Original_Artifacts.
12. IF um arquivo solicitado para importação não contém exatamente um documento JSON sintaticamente válido ou não pode ser convertido pelo Agent_JSON_Parser em um Agent_Document, THEN THE Artifact_Importer SHALL rejeitar a importação, disponibilizar uma indicação de erro que identifique a condição impeditiva, não registrar um novo Original_Artifact e manter inalterados todos os Original_Artifacts existentes.

### Requirement 16: Integração com a curadoria existente

**User Story:** Como curador, quero reutilizar relatórios já registrados, para que o histórico atual continue disponível na nova feature.

#### Acceptance Criteria

1. WHEN for solicitada a leitura de uma Occurrence associada a um Existing_Curation_Report presente no Existing_Curation_Store, THE Curation_System SHALL disponibilizar o CallId, o texto integral, o timestamp de criação e o timestamp de modificação com valores idênticos aos persistidos, sem modificar o Existing_Curation_Report.
2. WHEN o curador solicitar explicitamente o vínculo de um Existing_Curation_Report a um Curation_Record, THE Version_Store SHALL registrar esse vínculo somente em resposta à solicitação e manter inalterado o texto persistido do Existing_Curation_Report.
3. WHEN o curador criar campos estruturados a partir de um Existing_Curation_Report, THE Curation_System SHALL manter o Existing_Curation_Report armazenado e consultável como evidência legada distinta, sem substituí-lo nem alterar seu CallId, texto, timestamp de criação ou timestamp de modificação.
4. THE Curation_System SHALL permitir salvar um Existing_Curation_Report no Existing_Curation_Store, listar uma entrada correspondente a cada Existing_Curation_Report persistido e exportar o Existing_Curation_Report selecionado com CallId, texto, timestamp de criação e timestamp de modificação idênticos aos valores persistidos.
5. WHEN dados estruturados de nova curadoria forem persistidos para um Curation_Record, THE Version_Store SHALL armazená-los como conteúdo distinto do Existing_Curation_Report associado, sem modificar a existência, o CallId, o texto, o timestamp de criação ou o timestamp de modificação do Existing_Curation_Report.
6. IF a leitura de um Existing_Curation_Report falhar, THEN THE Curation_System SHALL indicar ao curador que o relatório não foi carregado e manter inalterados e acessíveis os valores da Work_Copy e do Curation_Record existentes antes da tentativa.

### Requirement 17: Reutilização da arquitetura existente

**User Story:** Como mantenedor do projeto, quero estender a arquitetura atual, para que a feature permaneça coerente com o sistema existente.

#### Acceptance Criteria

1. WHEN a app factory Flask existente criar uma instância da aplicação, THE Curation_System SHALL registrar nessa instância todas as rotas e todos os serviços introduzidos pela feature por meio dessa app factory.
2. WHEN uma página web introduzida pela feature for solicitada, THE Curation_System SHALL renderizar a página com templates Jinja e recursos Bootstrap disponibilizados pela Existing_Web_Architecture.
3. WHEN um log for fornecido para o carregamento de Occurrences, THE Curation_System SHALL processar o log por meio do Log_Parser existente e representar cada Occurrence resultante com os modelos de evento existentes.
4. THE Version_Store SHALL persistir cada Curation_Record, Work_Version e Audit_Event usando SQLite.
5. WHEN uma operação solicitar alterações persistentes em Work_Copy, Curation_Record, Work_Version ou Audit_Event, THE Version_Store SHALL aplicar todas as alterações persistentes causadas pela operação em uma única transação atômica, confirmando o conjunto completo ou nenhuma alteração.
6. IF uma transação de persistência não for confirmada, THEN THE Version_Store SHALL restaurar a existência e o conteúdo de cada item abrangido pela transação ao estado observado antes de seu início e retornar ao chamador uma indicação de falha distinguível de um resultado de sucesso que identifique a persistência como não concluída.
7. THE Curation_System SHALL atribuir todas as operações de persistência de cada uma das categorias Original_Artifacts, Agent_Documents, UI_Metadata e Existing_Curation_Reports a uma responsabilidade exclusiva dessa categoria, distinta das responsabilidades das outras três categorias.

### Requirement 18: Proteção de evidências e valores sensíveis

**User Story:** Como responsável pela curadoria, quero consultar evidências sem alterar ou divulgar dados inadvertidamente, para que a investigação preserve integridade e confidencialidade.

#### Acceptance Criteria

1. THE Curation_System SHALL aplicar a Sensitive_Data_Policy configurada para classificar como Sensitive_Value cada valor correspondente a um nome de campo ou padrão de log configurado e gerar sua representação visual conforme a regra de mascaramento configurada para a correspondência detectada.
2. WHEN Raw_Evidence ou um Logic_Element contendo Sensitive_Value é aberto para apresentação ao curador, THE Curation_System SHALL exibir a representação mascarada no lugar de cada Sensitive_Value e manter cada valor subjacente idêntico ao valor existente antes da apresentação.
3. WHEN o curador solicita revelar um Sensitive_Value, THE Version_Store SHALL criar exatamente um registro de auditoria contendo a ação de revelação, a identificação do curador solicitante, o instante da solicitação em UTC e a referência de origem associada ao valor, expressa pelo Source_Path ou pelo evento afetado.
4. WHEN o Version_Store conclui o registro de auditoria da solicitação de revelação, THE Curation_System SHALL substituir, na apresentação corrente, somente a representação mascarada solicitada pelo respectivo valor subjacente, sem alterar o valor armazenado nem o texto de curadoria.
5. IF o Version_Store não conseguir concluir o registro de auditoria da solicitação de revelação, THEN THE Curation_System SHALL manter o Sensitive_Value mascarado, indicar ao curador que a revelação não foi realizada e preservar sem alteração o valor subjacente e o texto de curadoria.
6. IF no momento da exportação o conteúdo associado a um Source_Path for idêntico ao conteúdo recebido na importação, THEN THE Agent_Exporter SHALL incluir no JSON completo o Sensitive_Value original nesse Source_Path sem substituí-lo pela representação mascarada.
7. WHEN Action_Code é importado, THE Validation_Engine SHALL analisá-lo estaticamente sem executar qualquer parte do Action_Code nem invocar funções, endpoints ou Tools definidos nele.
8. IF a análise estática do Action_Code importado não puder ser concluída, THEN THE Validation_Engine SHALL produzir um resultado de validação malsucedido indicando a impossibilidade da análise e manter o Action_Code sem execução e sem alteração.
9. WHILE Original_Artifacts, logs, Work_Copies ou dados de auditoria não forem objeto de uma ação explícita de exportação, THE Curation_System SHALL mantê-los exclusivamente no armazenamento local configurado e não os transmitir para fora desse armazenamento.
10. WHEN conteúdo técnico é copiado para Complaint, Observed_Behavior ou Expected_Result, THE Curation_System SHALL aplicar a Sensitive_Data_Policy ao conteúdo, indicar ao curador cada trecho detectado como Sensitive_Value e não persistir o texto de curadoria antes de apresentar todas as indicações detectadas.

## Property-Based Testing Candidates

Os critérios abaixo são candidatos explícitos a testes baseados em propriedades porque variam de forma relevante com documentos, caminhos, valores e sequências gerados:

| Propriedade | Critérios | Oráculo verificável |
|---|---|---|
| Imutabilidade do original | 1.6 | Após qualquer sequência finita de operações de Work_Copy, bytes e metadados registrados do Original_Artifact permanecem idênticos aos valores da importação. |
| Parse/print/parse | 2.6 | Imprimir e reinterpretar preserva ocorrências de chaves, valores, tipos, ordens, campos desconhecidos e JSON embutido. |
| Ordenação estável de eventos | 6.2 | Eventos válidos ficam em ordem temporal crescente e empates preservam a ordem relativa de leitura. |
| Localidade da edição | 10.10 | Editar um único Source_Path folha preserva o conjunto, os valores e os tipos de todos os demais Source_Paths folha. |
| Editar e descartar | 10.11 | Descartar todas as alterações restaura caminhos, valores e tipos da base da Work_Copy. |
| Validação determinística e idempotente | 11.13 | Repetições sem mudanças preservam quantidade, ordem, códigos, severidades e caminhos dos diagnósticos, sem acúmulo nem mutação da Work_Copy. |
| Change_Set inversível | 13.4 | Aplicar um Change_Set e seu inverso faz a comparação com a base resultar em Change_Set vazio. |
| Diff simétrico | 13.5 | Inverter base e correção preserva exatamente os caminhos alterados e troca os valores anterior e posterior, inclusive ausências. |
| Versionamento sem alteração | 14.2 | Solicitar versionamento sem diferenças não cria Work_Version nem altera sua quantidade. |
| Integridade da cadeia | 14.8 | Existe exatamente uma versão inicial; toda versão não inicial possui um pai existente; todas as cadeias terminam na inicial sem ciclos. |
| Exportação sem mudança | 15.3 | Uma versão com Change_Set vazio exporta o mesmo comprimento e o mesmo byte em cada posição do Original_Artifact. |
| Preservação de campos | 15.4 | Fora dos Source_Paths alterados, chaves, valores, tipos e ordens permanecem iguais aos do Original_Artifact. |
| Export/import semântico | 15.6 | Reimportar o export preserva chaves, valores, tipos e ordem de arrays, desconsiderando UI_Metadata e as diferenças permitidas. |

## Evidence and Known Limitations

- O workspace comprova que o formato `node (ork.json)` é transformado em `actions`, `ai_models`, `asr`, `paths`, `stages`, `system_prompts`, `tts`, `fillers` e configurações relacionadas.
- A ocorrência Athena observada comprova fallback após erro do categorizador, escolha de Stage, carregamento de Prompt, chamada de Tool, resultado externo, segunda chamada ao modelo, finalize e resposta vocalizada.
- O parser atual já extrai conversa, timeline, Tools, decisões, erros, modelos, latências e mailing, mas não demonstra captura integral de todo request, response e Prompt bruto; esses itens permanecem sujeitos a Evidence_Gaps.
- O Source_Schema autoritativo de `specVersion` 1 não foi identificado no workspace examinado; a validação de schema permanece pré-condicionada ao fornecimento ou identificação desse artefato.
- A definição definitiva de Canonical_Source entre Normalized_ORK_Node, Graph_Nodes, conteúdo publicado, `promptText`, `allPrompts` e `drafts` depende das referências explícitas do Original_Artifact e de decisão auditável quando houver conflito.
