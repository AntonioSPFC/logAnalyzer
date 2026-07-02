# Requirements Document

## Introduction

Esta funcionalidade define uma ferramenta de análise de logs capaz de processar diferentes
tipos de arquivos de log produzidos por aplicações distintas. O usuário seleciona um ou mais
arquivos de log, informa um identificador a ser buscado (por exemplo, um identificador de
chamada ou de sessão) e a ferramenta extrai e analisa as entradas de log relacionadas a esse
identificador.

A análise é orientada por padrões específicos de cada aplicação (Padrões de Análise). Nesta
primeira fase o objetivo é estabelecer a estrutura extensível da ferramenta, contemplando três
aplicações iniciais: VPL (logs de um PBX FreeSWITCH), ORK (orquestrador proprietário de um
agente de IA para chamadas telefônicas, que se conecta ao VPL) e VOCI (transcritor de áudio).
A arquitetura deve permitir a adição de novas aplicações no futuro sem alteração das aplicações
já suportadas.

Esta é a Fase 1 (estrutura). A Fase 2, futura, fornecerá logs reais de situações de sucesso e
de erro com causa-raiz conhecida, que serão usados para detalhar os padrões de detecção.

## Glossary

- **Analisador_de_Logs**: O sistema completo descrito por este documento, responsável por
  carregar, filtrar, interpretar e analisar arquivos de log.
- **Arquivo_de_Log**: Arquivo de texto contendo entradas de log produzidas por uma Aplicação.
- **Entrada_de_Log**: Uma linha ou bloco lógico individual dentro de um Arquivo_de_Log.
- **Identificador**: Cadeia de texto fornecida pelo usuário usada para selecionar as
  Entradas_de_Log relevantes (por exemplo, identificador de chamada, UUID de sessão).
- **Aplicação**: Origem dos logs com formato e semântica próprios. As Aplicações iniciais são
  VPL, ORK e VOCI.
- **VPL**: Aplicação cujos logs são gerados por um PBX FreeSWITCH.
- **ORK**: Aplicação proprietária que orquestra um agente de IA para chamadas telefônicas e que
  se conecta ao VPL.
- **VOCI**: Aplicação transcritora de áudio.
- **Parser_de_Aplicacao**: Componente responsável por converter o texto bruto de um
  Arquivo_de_Log de uma Aplicação específica em Entradas_de_Log estruturadas.
- **Padrao_de_Analise**: Conjunto de regras associado a uma Aplicação usado para classificar
  Entradas_de_Log e identificar situações de sucesso ou de erro.
- **Registro_de_Aplicacoes**: Componente que mantém o catálogo de Aplicações suportadas e
  associa cada Aplicação ao seu Parser_de_Aplicacao e ao seu Padrao_de_Analise.
- **Resultado_de_Analise**: Saída estruturada produzida pelo Analisador_de_Logs contendo as
  Entradas_de_Log relevantes e as classificações aplicadas.

## Requirements

### Requirement 1: Seleção de arquivos de log

**User Story:** Como usuário, quero selecionar um ou mais arquivos de log, para que eu possa
indicar quais dados serão analisados.

#### Acceptance Criteria

1. WHEN o usuário seleciona entre 1 e 100 Arquivos_de_Log, THE Analisador_de_Logs SHALL
   carregar cada Arquivo_de_Log selecionado, com tamanho de até 500 MB por arquivo, para
   processamento.
2. IF um Arquivo_de_Log selecionado não pode ser lido ou está vazio, THEN THE
   Analisador_de_Logs SHALL retornar uma mensagem de erro que identifica o Arquivo_de_Log
   afetado, preservar os demais Arquivos_de_Log já carregados e continuar o processamento dos
   demais Arquivos_de_Log selecionados.
3. WHEN o usuário seleciona múltiplos Arquivos_de_Log associados a Aplicações diferentes no
   Registro_de_Aplicacoes, THE Analisador_de_Logs SHALL processar cada Arquivo_de_Log de
   acordo com a Aplicação a ele associada.
4. IF um Arquivo_de_Log selecionado excede 500 MB, THEN THE Analisador_de_Logs SHALL rejeitar
   esse Arquivo_de_Log, retornar uma mensagem de erro que identifica o Arquivo_de_Log afetado
   e continuar o processamento dos demais Arquivos_de_Log selecionados.
5. IF um Arquivo_de_Log selecionado não possui Aplicação associada no Registro_de_Aplicacoes,
   THEN THE Analisador_de_Logs SHALL retornar uma mensagem de erro que identifica o
   Arquivo_de_Log afetado e continuar o processamento dos demais Arquivos_de_Log selecionados.

### Requirement 2: Associação de arquivo à Aplicação

**User Story:** Como usuário, quero indicar a qual aplicação cada arquivo pertence, para que a
ferramenta use o interpretador e os padrões corretos.

#### Acceptance Criteria

1. WHEN o usuário associa um Arquivo_de_Log a uma Aplicação registrada no
   Registro_de_Aplicacoes (VPL, ORK ou VOCI), THE Analisador_de_Logs SHALL utilizar o
   Parser_de_Aplicacao correspondente a essa Aplicação e SHALL confirmar a associação ao
   usuário em até 2 segundos.
2. IF um Arquivo_de_Log é associado a uma Aplicação não registrada no Registro_de_Aplicacoes,
   THEN THE Analisador_de_Logs SHALL rejeitar a associação, manter o Arquivo_de_Log sem
   Aplicação atribuída e retornar uma mensagem de erro indicando que a Aplicação não é
   suportada.
3. IF o usuário não informa a Aplicação de um Arquivo_de_Log, THEN THE Analisador_de_Logs SHALL
   impedir o início da análise desse Arquivo_de_Log e solicitar ao usuário a identificação da
   Aplicação.
4. IF o usuário não fornece a identificação da Aplicação solicitada dentro de 60 segundos, THEN
   THE Analisador_de_Logs SHALL cancelar a associação pendente e retornar uma mensagem de erro
   informando que a identificação não foi fornecida.
5. WHEN o usuário associa a uma Aplicação um Arquivo_de_Log que já possuía outra Aplicação
   atribuída, THE Analisador_de_Logs SHALL substituir a associação anterior pela nova Aplicação
   informada.

### Requirement 3: Busca por identificador

**User Story:** Como usuário, quero informar um identificador a ser buscado, para que eu
visualize apenas as entradas de log relacionadas a ele.

#### Acceptance Criteria

1. WHEN o usuário fornece um Identificador não vazio contendo de 1 a 256 caracteres, THE
   Analisador_de_Logs SHALL selecionar todas as Entradas_de_Log cujo conteúdo corresponda
   exatamente ao Identificador, sem diferenciar maiúsculas de minúsculas, nos Arquivos_de_Log
   carregados.
2. IF nenhuma Entrada_de_Log contém o Identificador fornecido, THEN THE Analisador_de_Logs
   SHALL retornar um Resultado_de_Analise vazio acompanhado de uma mensagem informando que
   nenhuma correspondência foi encontrada.
3. WHEN o Identificador é encontrado em Arquivos_de_Log de Aplicações diferentes, THE
   Analisador_de_Logs SHALL agrupar as Entradas_de_Log selecionadas por Aplicação.
4. WHEN o Analisador_de_Logs produz o Resultado_de_Analise, THE Analisador_de_Logs SHALL
   ordenar as Entradas_de_Log selecionadas por carimbo de tempo crescente, preservando a ordem
   original de leitura para Entradas_de_Log com carimbos de tempo idênticos.
5. IF o usuário fornece um Identificador vazio, composto apenas por espaços em branco, ou com
   mais de 256 caracteres, THEN THE Analisador_de_Logs SHALL rejeitar a busca, preservar o
   estado atual do Resultado_de_Analise, e exibir uma mensagem indicando que o Identificador
   fornecido é inválido.
6. IF nenhum Arquivo_de_Log está carregado quando o usuário fornece um Identificador, THEN THE
   Analisador_de_Logs SHALL retornar um Resultado_de_Analise vazio e exibir uma mensagem
   indicando que não há Arquivos_de_Log carregados.

### Requirement 4: Interpretação de logs por Aplicação

**User Story:** Como mantenedor, quero que cada aplicação tenha seu próprio interpretador de
logs, para que formatos distintos sejam corretamente estruturados.

#### Acceptance Criteria

1. WHEN um Arquivo_de_Log de uma Aplicação suportada (VPL, ORK ou VOCI) é processado, THE
   Parser_de_Aplicacao correspondente SHALL converter cada Entrada_de_Log em uma estrutura
   contendo, obrigatoriamente, os campos carimbo de tempo, nível de severidade e mensagem, sem
   deixar nenhum desses três campos vazio.
2. IF uma Entrada_de_Log processada não contém um carimbo de tempo válido segundo o formato
   esperado pela Aplicação, ou não contém um nível de severidade pertencente ao conjunto de
   níveis definido pela Aplicação, ou não contém uma mensagem, THEN THE Parser_de_Aplicacao
   SHALL classificar a Entrada_de_Log como não interpretada.
3. WHEN uma Entrada_de_Log é classificada como não interpretada, THE Parser_de_Aplicacao SHALL
   preservar integralmente o texto original da Entrada_de_Log, sem descartá-la nem alterá-la.
4. WHEN a impressão de uma Entrada_de_Log estruturada é solicitada, THE Parser_de_Aplicacao
   SHALL produzir uma representação textual contendo os campos carimbo de tempo, nível de
   severidade e mensagem.
5. FOR ALL Entradas_de_Log interpretadas com sucesso, WHEN a sequência interpretar, imprimir e
   interpretar novamente é executada, THE Parser_de_Aplicacao SHALL produzir uma Entrada_de_Log
   estruturada cujos campos carimbo de tempo, nível de severidade e mensagem sejam idênticos,
   campo a campo, aos da primeira interpretação (propriedade de ida e volta).

### Requirement 5: Padrões de análise por Aplicação

**User Story:** Como analista, quero que cada aplicação tenha padrões de análise próprios, para
que situações de sucesso e de erro sejam identificadas conforme a semântica da aplicação.

#### Acceptance Criteria

1. THE Registro_de_Aplicacoes SHALL associar cada Aplicação suportada a exatamente um
   Padrao_de_Analise.
2. WHEN as Entradas_de_Log de uma Aplicação são analisadas, THE Analisador_de_Logs SHALL
   aplicar o Padrao_de_Analise associado a essa Aplicação no Registro_de_Aplicacoes.
3. WHEN um Padrao_de_Analise classifica uma Entrada_de_Log, THE Analisador_de_Logs SHALL
   atribuir à Entrada_de_Log exatamente uma das categorias definidas pelo Padrao_de_Analise,
   contemplando no mínimo as categorias de sucesso e de erro.
4. IF uma Entrada_de_Log não corresponde a nenhuma regra do Padrao_de_Analise, THEN THE
   Analisador_de_Logs SHALL classificar a Entrada_de_Log como não classificada e preservar o
   conteúdo original da Entrada_de_Log.
5. IF uma Entrada_de_Log corresponde a mais de uma regra do Padrao_de_Analise, THEN THE
   Analisador_de_Logs SHALL aplicar a primeira regra correspondente na ordem definida pelo
   Padrao_de_Analise.
6. IF a Aplicação de uma Entrada_de_Log não possui Padrao_de_Analise associado no
   Registro_de_Aplicacoes, THEN THE Analisador_de_Logs SHALL registrar uma indicação de erro
   no Resultado_de_Analise identificando a Aplicação afetada.

### Requirement 6: Suporte às Aplicações iniciais VPL, ORK e VOCI

**User Story:** Como usuário, quero que a ferramenta já reconheça VPL, ORK e VOCI, para que eu
possa analisar essas aplicações desde a primeira versão.

#### Acceptance Criteria

1. WHEN o Analisador_de_Logs é iniciado pela primeira vez, THE Registro_de_Aplicacoes SHALL
   conter exatamente as três Aplicações VPL, ORK e VOCI, cada uma com um Identificador de
   Aplicação único.
2. THE Analisador_de_Logs SHALL fornecer um Parser_de_Aplicacao associado à Aplicação VPL no
   Registro_de_Aplicacoes.
3. THE Analisador_de_Logs SHALL fornecer um Parser_de_Aplicacao associado à Aplicação ORK no
   Registro_de_Aplicacoes.
4. THE Analisador_de_Logs SHALL fornecer um Parser_de_Aplicacao associado à Aplicação VOCI no
   Registro_de_Aplicacoes.
5. THE Registro_de_Aplicacoes SHALL associar exatamente um Padrao_de_Analise a cada uma das
   Aplicações VPL, ORK e VOCI.
6. WHERE os formatos detalhados de log das Aplicações ainda não foram definidos (Fase 1), THE
   Padrao_de_Analise de cada Aplicação SHALL classificar toda Entrada_de_Log como não
   classificada até que as regras sejam detalhadas na Fase 2.
7. IF uma Entrada_de_Log de VPL, ORK ou VOCI não corresponde ao formato esperado pelo
   respectivo Parser_de_Aplicacao, THEN THE Parser_de_Aplicacao SHALL classificá-la como não
   interpretada e preservar o texto original da Entrada_de_Log.
8. IF o usuário solicita a análise de uma Aplicação que não seja VPL, ORK ou VOCI e que não
   esteja registrada no Registro_de_Aplicacoes, THEN THE Analisador_de_Logs SHALL rejeitar a
   solicitação e apresentar uma indicação de erro de Aplicação não suportada.

### Requirement 7: Extensibilidade para novas Aplicações

**User Story:** Como mantenedor, quero adicionar novas aplicações no futuro, para que a
ferramenta evolua sem alterar as aplicações já suportadas.

#### Acceptance Criteria

1. WHERE uma nova Aplicação é adicionada com um Parser_de_Aplicacao que implementa a interface
   comum de Parser_de_Aplicacao e um Padrao_de_Analise que implementa a interface comum de
   Padrao_de_Analise, THE Registro_de_Aplicacoes SHALL passar a reconhecer a nova Aplicação
   mantendo inalterados os registros das Aplicações existentes.
2. WHEN uma nova Aplicação é registrada com sucesso, THE Analisador_de_Logs SHALL disponibilizar
   a nova Aplicação para seleção sem modificar os Parsers_de_Aplicacao e os Padroes_de_Analise
   das Aplicações existentes.
3. THE Analisador_de_Logs SHALL definir uma interface comum que todo Parser_de_Aplicacao SHALL
   implementar.
4. THE Analisador_de_Logs SHALL definir uma interface comum que todo Padrao_de_Analise SHALL
   implementar.
5. IF uma nova Aplicação é registrada com um Parser_de_Aplicacao ou um Padrao_de_Analise que
   não implementa a respectiva interface comum, THEN THE Registro_de_Aplicacoes SHALL rejeitar
   o registro, preservar inalterado o conjunto de Aplicações já reconhecidas e apresentar uma
   indicação de erro informando qual interface não foi implementada.
6. IF uma nova Aplicação é registrada com um Identificador de Aplicação igual ao de uma
   Aplicação já existente no Registro_de_Aplicacoes, THEN THE Registro_de_Aplicacoes SHALL
   rejeitar o registro, preservar inalterada a Aplicação existente e apresentar uma indicação
   de erro de Identificador duplicado.

### Requirement 8: Correlação entre VPL e ORK

**User Story:** Como analista, quero correlacionar os logs do ORK com os do VPL, para que eu
acompanhe uma chamada através das aplicações conectadas.

#### Acceptance Criteria

1. WHEN Arquivos_de_Log do ORK e do VPL são analisados para o mesmo Identificador, THE
   Analisador_de_Logs SHALL apresentar as Entradas_de_Log de ambas as Aplicações em uma linha
   do tempo única ordenada por carimbo de tempo crescente.
2. WHEN duas ou mais Entradas_de_Log possuem o mesmo carimbo de tempo na linha do tempo, THE
   Analisador_de_Logs SHALL ordená-las de forma determinística pelo nome da Aplicação em ordem
   alfabética crescente e, em caso de empate, pela ordem de leitura no Arquivo_de_Log.
3. WHERE uma Entrada_de_Log do ORK referencia um Identificador presente em uma Entrada_de_Log
   do VPL, THE Analisador_de_Logs SHALL marcar as Entradas_de_Log relacionadas como
   correlacionadas no Resultado_de_Analise.
4. IF nenhuma Entrada_de_Log do ORK e do VPL compartilha o mesmo Identificador durante a
   análise, THEN THE Analisador_de_Logs SHALL registrar no Resultado_de_Analise uma indicação
   de que nenhuma correlação foi encontrada e SHALL preservar as Entradas_de_Log originais de
   cada Aplicação sem alterá-las.
5. IF o Arquivo_de_Log do ORK ou do VPL está indisponível ou não pode ser interpretado pelo
   Parser_de_Aplicacao durante a correlação, THEN THE Analisador_de_Logs SHALL apresentar uma
   indicação de erro identificando a Aplicação afetada e SHALL preservar as Entradas_de_Log já
   interpretadas da outra Aplicação.

### Requirement 9: Apresentação do resultado da análise

**User Story:** Como usuário, quero visualizar o resultado da análise de forma estruturada,
para que eu compreenda o que ocorreu com o identificador buscado.

#### Acceptance Criteria

1. WHEN a análise é concluída com ao menos uma Entrada_de_Log selecionada, THE
   Analisador_de_Logs SHALL apresentar o Resultado_de_Analise contendo, para cada
   Entrada_de_Log selecionada, o seu conteúdo, a Aplicação de origem e a categoria atribuída.
2. WHEN a análise é concluída sem nenhuma Entrada_de_Log selecionada para o Identificador
   buscado, THE Analisador_de_Logs SHALL apresentar um Resultado_de_Analise vazio acompanhado
   de uma indicação de que nenhuma Entrada_de_Log foi encontrada para o Identificador.
3. WHEN o Resultado_de_Analise contém Entradas_de_Log classificadas como erro, THE
   Analisador_de_Logs SHALL exibir essas Entradas_de_Log com uma marcação visual distinta das
   demais categorias, de modo que sejam identificáveis sem inspeção do conteúdo.
4. THE Analisador_de_Logs SHALL incluir no Resultado_de_Analise a contagem de Entradas_de_Log
   por categoria e a contagem de Entradas_de_Log por Aplicação.
5. IF a apresentação do Resultado_de_Analise não puder ser concluída, THEN THE
   Analisador_de_Logs SHALL apresentar uma mensagem indicando a falha na exibição do resultado
   e preservar as Entradas_de_Log selecionadas sem descartá-las.

### Requirement 10: Tratamento de entradas inválidas

**User Story:** Como usuário, quero receber mensagens claras quando uma entrada for inválida,
para que eu possa corrigir e repetir a análise.

#### Acceptance Criteria

1. IF o usuário inicia uma análise sem selecionar nenhum Arquivo_de_Log, THEN THE
   Analisador_de_Logs SHALL interromper a análise e retornar uma mensagem de erro solicitando
   a seleção de ao menos um Arquivo_de_Log, preservando o Identificador já informado.
2. IF o usuário inicia uma análise com o campo Identificador vazio ou contendo apenas espaços
   em branco, THEN THE Analisador_de_Logs SHALL interromper a análise e retornar uma mensagem
   de erro solicitando o preenchimento do Identificador, preservando os Arquivos_de_Log já
   selecionados.
3. IF o usuário inicia uma análise com um Identificador que excede 256 caracteres, THEN THE
   Analisador_de_Logs SHALL interromper a análise e retornar uma mensagem de erro indicando que
   o Identificador deve conter entre 1 e 256 caracteres, preservando os Arquivos_de_Log já
   selecionados.
4. IF um Arquivo_de_Log selecionado não contém nenhuma Entrada_de_Log, THEN THE
   Analisador_de_Logs SHALL retornar uma mensagem informando que o Arquivo_de_Log está vazio e
   SHALL prosseguir a análise com os demais Arquivos_de_Log selecionados que contenham
   Entradas_de_Log.
5. IF o conteúdo de um Arquivo_de_Log selecionado não pode ser interpretado pelo
   Parser_de_Aplicacao por estar em formato não reconhecido, THEN THE Analisador_de_Logs SHALL
   retornar uma mensagem de erro indicando que o Arquivo_de_Log possui formato inválido,
   identificando o Arquivo_de_Log afetado, e SHALL preservar a seleção dos demais
   Arquivos_de_Log.
6. WHEN o Analisador_de_Logs retorna uma mensagem de erro de entrada inválida, THE
   Analisador_de_Logs SHALL exibir a mensagem em até 2 segundos após o início da análise e SHALL
   preservar todas as entradas válidas já informadas para permitir a correção sem reinício do
   fluxo.
