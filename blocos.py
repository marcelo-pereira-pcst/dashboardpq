"""
Estrutura editorial do site: quais perguntas existem, em que seção aparecem,
sob qual aba e com que texto.

Por que este arquivo existe separado
------------------------------------
`build.py` faz o cálculo e a serialização; aqui fica o que é decisão de
publicação — títulos, ordem das abas, enunciado de cada pergunta, rótulos
legíveis. São coisas que mudam por motivos diferentes e em ritmos diferentes:
o cálculo muda quando a estatística muda, isto muda quando o texto do site
muda. Misturar os dois faria toda revisão de redação parecer uma alteração de
método no `git diff`.

Os enunciados foram transcritos das páginas do app Streamlit, que por sua vez
vieram do questionário. Não invente texto novo aqui — se um enunciado estiver
errado, ele está errado no questionário também, e a correção é outra conversa.

Cada BLOCO é também uma FAMÍLIA DE TESTES para a correção de Benjamini–
Hochberg: o FDR é aplicado sobre os cruzamentos daquele bloco com as 11
variáveis sociodemográficas, e não sobre o site inteiro. Ver a nota
metodológica; a consequência prática é que a página de atividades mantém
exatamente os mesmos números de sempre (165 testes, 41 significativos).
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Ordens que contrariam `categories.json` de propósito
#
# ⚠️ Armadilha documentada no handoff (§6): `octs1` e `odc2` aparecem
# invertidos em relação à ordem canônica nas páginas do Streamlit. Não é bug.
# A ordem canônica desses dois vai do melhor para o pior; o site exibe do pior
# para o melhor, que é a mesma direção de todas as outras escalas do
# questionário (`adc1` começa em "Nenhuma vez", `octs6` em "Nada preocupado"
# depois da inversão de leitura). Manter as duas direções misturadas obrigaria
# o leitor a reaprender o eixo a cada gráfico.
# --------------------------------------------------------------------------- #
ORDENS_SOBRESCRITAS: dict[str, list[str]] = {
    "octs1": ["Atrasado", "Intermediário", "Avançado"],
    "odc2": [
        "Não sei",
        "Nada importante",
        "Pouco importante",
        "Importante",
        "Muito importante",
    ],
}

# --------------------------------------------------------------------------- #
# Agregação de categorias raras
#
# A população de bolsistas PQ é pública e enumerável — o CNPq divulga a lista.
# Num cruzamento em que AS DUAS variáveis são sensíveis (cor/raça × religião,
# religião × orientação política), uma célula de contagem 1 revela uma
# combinação de atributos protegidos que, somada a conhecimento externo, pode
# apontar para uma pessoa. Os cruzamentos de atividade × sociodemográfica não
# têm esse problema: saber quantas palestras alguém deu não é atributo
# protegido.
#
# A resposta aqui é agregar as categorias raras ANTES de qualquer cruzamento,
# e não suprimir células depois. Agregar preserva o fechamento das tabelas —
# os totais continuam batendo — e não obriga o leitor a entender uma regra de
# supressão. A distribuição univariada COMPLETA continua publicada em
# `marginais_detalhadas`, porque a contagem de uma variável sozinha não
# revela combinação nenhuma.
#
# Os agrupamentos seguem convenções da área sempre que existem: preta + parda
# = "preta ou parda" é o padrão da literatura brasileira sobre desigualdade
# racial; a escolaridade da mãe colapsa para os quatro níveis usuais.
# --------------------------------------------------------------------------- #
AGREGACOES: dict[str, dict[str, str]] = {
    "CE04": {  # Cor ou raça
        "Preta": "Preta ou parda",
        "Parda": "Preta ou parda",
        "Amarela": "Amarela ou indígena",
        "Indígena": "Amarela ou indígena",
    },
    "CE05": {  # Religião — 11 categorias, várias com menos de 30 casos
        "Cristã Protestantes históricas": "Cristã protestante ou evangélica",
        "Cristã evangélica Pentecostal e Neopentecostal":
            "Cristã protestante ou evangélica",
        "Judaísmo": "Outras religiões",
        "Matrizes africanas": "Outras religiões",
        "Religiões Orientais": "Outras religiões",
        "Islamismo": "Outras religiões",
        "Outros": "Outras religiões",
    },
    "CE07": {  # Orientação política
        "Conservador": "Conservador ou de direita",
        "De direita": "Conservador ou de direita",
    },
    "CE03": {  # Escolaridade da mãe
        "Não frequentou escola": "Fundamental incompleto ou menos",
        "Ensino Fundamental Incompleto": "Fundamental incompleto ou menos",
        "Ensino Fundamental": "Ensino fundamental",
        "Ensino Médio Incompleto": "Ensino médio",
        "Ensino Médio": "Ensino médio",
        "Ensino Superior Incompleto": "Ensino superior",
        "Ensino Superior": "Ensino superior",
    },
}

# Ordem de exibição das categorias agregadas.
ORDEM_AGREGADA: dict[str, list[str]] = {
    "CE04": ["Branca", "Preta ou parda", "Amarela ou indígena"],
    "CE05": ["Cristã católica", "Cristã protestante ou evangélica", "Espírita",
             "Outras religiões", "Não tenho religião", "Ateu ou agnóstico"],
    "CE07": ["De esquerda", "De centro", "Liberal", "Conservador ou de direita",
             "Nenhuma dessas"],
    "CE03": ["Fundamental incompleto ou menos", "Ensino fundamental",
             "Ensino médio", "Ensino superior"],
}

# --------------------------------------------------------------------------- #
# Rótulos de exibição das variáveis sociodemográficas
#
# `data_process.codigo_variaveis` traz nomes de identificador — "Cor_Raca",
# "GdeArea_CNPq" — que servem para indexar um DataFrame, não para aparecer na
# tela de um leitor. Trocar lá dentro quebraria as páginas do Streamlit, então
# a tradução mora aqui, no limite entre o cálculo e a publicação.
# --------------------------------------------------------------------------- #
ROTULOS_SOCIO: dict[str, str] = {
    "CE02": "Sexo",
    "CE03": "Escolaridade da mãe",
    "CE04": "Cor ou raça",
    "CE05": "Religião",
    "CE06": "Importância da religião",
    "CE07": "Orientação política",
    "CE08": "Nível da bolsa PQ",
    "CE10": "Ciência básica ou aplicada",
    "CE11": "Grande área do conhecimento",
    "CE13": "Região da instituição",
    "CE14": "Tempo de vínculo",
}

# Enunciado completo de cada atividade de divulgação. `varmap` guarda só o
# apelido curto ("palestra público geral"), que serve de rótulo de eixo mas
# não diz ao leitor o que exatamente foi perguntado.
DESCRICAO_ATIVIDADES: dict[str, str] = {
    "adc1[SQ001]": "Deu uma palestra pública num debate para o público em geral",
    "adc1[SQ002]": "Participou de curso de formação a um público externo à sua "
                   "Universidade ou instituto de pesquisa",
    "adc1[SQ003]": "Deu uma aula ou oficina numa escola da Educação Básica",
    "adc1[SQ004]": "Participou em evento numa comissão técnica ou conselho "
                   "profissional (exterior à Universidade ou instituto de pesquisa)",
    "adc1[SQ005]": "Participou de uma atividade do “Pint of Science”",
    "adc1[SQ006]": "Participou de uma atividade do Dia da Ciência ou da Semana "
                   "Nacional de Ciência e Tecnologia",
    "adc1[SQ007]": "Participou em evento numa associação, ONG ou movimento social",
    "adc1[SQ008]": "Escreveu um artigo numa revista para o público em geral",
    "adc1[SQ009]": "Foi entrevistado para um jornal ou revista para o público em geral",
    "adc1[SQ010]": "Escreveu um livro ou capítulo de livro de divulgação científica",
    "adc1[SQ011]": "Escreveu um release para a imprensa ou participou de um "
                   "programa de TV ou rádio",
    "adc1[SQ012]": "Participou de uma audiência pública no poder legislativo "
                   "(Câmara, Assembleia, Congresso Nacional)",
    "adc1[SQ013]": "Conduziu uma visita guiada num (ou em colaboração com um) museu",
    "adc1[SQ014]": "Participou de um programa em mídias digitais (blog, YouTube, "
                   "podcast, live no Instagram, etc.)",
    "adc1[SQ015]": "Produziu conteúdo para seu canal próprio em mídias digitais "
                   "(blog, YouTube, podcast, live no Instagram, etc.)",
}

# --------------------------------------------------------------------------- #
# Seções, abas e blocos
#
# `forma` diz ao site como desenhar a distribuição univariada do bloco:
#   "frequencia" — escala ordinal de contagem (adc1). Barras empilhadas.
#   "likert"     — escala ordinal de concordância/importância/preocupação.
#                  Barras empilhadas divergentes, centradas no ponto neutro.
#   "unica"      — uma pergunta só, escala ordinal. Barras simples.
#   "simnao"     — múltipla escolha marcada (MO01/MO02). Barras de contagem
#                  de "Sim", ordenadas.
#
#   "sentido" diz para que lado a ordem canônica aponta: "desc" quando ela
#   começa no extremo mais alto ("Concordo totalmente", "Muito importante") e
#   "asc" quando começa no mais baixo ("Nunca", "Não conheço"). O site sempre
#   desenha do mais alto para o mais baixo; sem esta marcação, metade dos
#   blocos sairia com a rampa de cor invertida em relação à outra metade.
#
# `neutro` marca a categoria que não entra em nenhum dos lados de uma escala
# divergente ("Não sei"). Sem isso ela seria empilhada como se fosse o extremo
# negativo, inflando um dos lados do gráfico com quem não respondeu à escala.
# --------------------------------------------------------------------------- #
SECOES = [
    {
        "id": "atividades",
        "titulo": "Atividades de divulgação científica",
        "arquivo": "atividades.qmd",
        "resumo": "O que os bolsistas PQ efetivamente fizeram nos 12 meses "
                  "anteriores à coleta, e como isso varia entre grupos.",
        "abas": [
            {
                "titulo": "Frequência por atividade",
                "blocos": ["adc1"],
            },
            {
                "titulo": "Relação com a mídia",
                "blocos": ["adc2", "adc3", "adc6"],
            },
        ],
    },
    {
        "id": "opinioes-ct",
        "titulo": "Opiniões sobre ciência e tecnologia",
        "arquivo": "opinioes-ct.qmd",
        "resumo": "Como os cientistas veem a ciência brasileira, seus riscos e "
                  "benefícios, e quem deveria participar da política de C&T.",
        "abas": [
            {"titulo": "Visão da ciência brasileira", "blocos": ["octs1"]},
            {"titulo": "Riscos e benefícios", "blocos": ["octs2", "octs3"]},
            {"titulo": "Temas de preocupação", "blocos": ["octs6"]},
            {"titulo": "Gestão da política de C&T", "blocos": ["octs4", "octs5"]},
        ],
    },
    {
        "id": "opinioes-dc",
        "titulo": "Opiniões sobre divulgação científica",
        "arquivo": "opinioes-dc.qmd",
        "resumo": "O que os cientistas pensam que a divulgação científica é, "
                  "quanto ela importa e para quem.",
        "abas": [
            {"titulo": "Modelos de divulgação", "blocos": ["odc1"]},
            {"titulo": "Importância", "blocos": ["odc2"]},
            {"titulo": "Públicos", "blocos": ["odc3"]},
        ],
    },
    {
        "id": "motivacoes",
        "titulo": "Motivações e obstáculos",
        "arquivo": "motivacoes.qmd",
        "resumo": "O que empurra e o que trava a comunicação com o público "
                  "não-especialista.",
        "abas": [
            {"titulo": "Motivações", "blocos": ["MO01"]},
            {"titulo": "Obstáculos", "blocos": ["MO02"]},
            {"titulo": "Formação", "blocos": ["MO04"]},
        ],
    },
    {
        "id": "perfil",
        "titulo": "Perfil sociodemográfico",
        "arquivo": "perfil.qmd",
        "resumo": "Quem respondeu, e como as próprias características se "
                  "cruzam entre si.",
        "abas": [
            {"titulo": "Distribuições", "blocos": ["socio"]},
            {"titulo": "Cruzamentos", "blocos": []},
        ],
    },
]

BLOCOS = [
    # ---------------------------------------------------------------- atividades
    {
        "id": "adc1",
        "secao": "atividades",
        "prefixo": "adc1[SQ",
        "titulo": "Atividades realizadas nos últimos 12 meses",
        "pergunta": "Entre as seguintes atividades de divulgação científica, "
                    "nos últimos 12 meses quantas vezes você…",
        "forma": "frequencia",
        "rotulo_item": "Atividade",
    },
    {
        "id": "adc2",
        "secao": "atividades",
        "colunas": ["adc2"],
        "titulo": "Contato com a mídia ao concluir uma pesquisa",
        "pergunta": "Quando você conclui uma pesquisa, você entra em contato "
                    "com a mídia para comunicar os resultados?",
        "forma": "unica",
        "rotulo_item": "Resposta",
    },
    {
        "id": "adc3",
        "secao": "atividades",
        "prefixo": "adc3[SQ",
        "titulo": "Importância dos profissionais de comunicação",
        "pergunta": "No seu caso, qual importância tem os seguintes "
                    "profissionais para a sua comunicação com o público "
                    "não-especialista:",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Profissional",
    },
    {
        "id": "adc6",
        "secao": "atividades",
        "prefixo": "adc6[SQ",
        "titulo": "Como a mídia procura o cientista",
        "pergunta": "Em geral, de que modo você é solicitado/a pela mídia?",
        "forma": "likert",
        "sentido": "asc",
        "neutro": "Não se aplica a mim",
        "rotulo_item": "Via",
    },
    # -------------------------------------------------------------- opiniões C&T
    {
        "id": "octs1",
        "secao": "opinioes-ct",
        "colunas": ["octs1"],
        "titulo": "A ciência brasileira no cenário mundial",
        "pergunta": "Se você fosse colocar a ciência brasileira num cenário "
                    "mundial, você diria que ela se encontra atualmente em um "
                    "nível…",
        "forma": "unica",
        "rotulo_item": "Nível",
    },
    {
        "id": "octs2",
        "secao": "opinioes-ct",
        "colunas": ["octs2"],
        "titulo": "Benefícios da ciência",
        "pergunta": "Vamos agora falar sobre os riscos e os benefícios da "
                    "pesquisa científica. Em sua opinião, a ciência traz para "
                    "a humanidade…",
        "forma": "unica",
        "rotulo_item": "Benefícios",
    },
    {
        "id": "octs3",
        "secao": "opinioes-ct",
        "colunas": ["octs3"],
        "titulo": "Riscos da ciência",
        "pergunta": "E em sua opinião, a ciência traz para a humanidade…",
        "forma": "unica",
        "rotulo_item": "Riscos",
    },
    {
        "id": "octs6",
        "secao": "opinioes-ct",
        "prefixo": "octs6[SQ",
        "titulo": "Temas de preocupação",
        "pergunta": "Entre os temas a seguir, que despertaram algum grau de "
                    "preocupação na opinião pública, o quanto você está "
                    "preocupado, como cidadão, com…",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Tema",
    },
    {
        "id": "octs4",
        "secao": "opinioes-ct",
        "prefixo": "octs4[SQ",
        "titulo": "Quem deve participar da regulação da C&T",
        "pergunta": "Na sua opinião, a regulação e gestão da ciência e da "
                    "tecnologia deveriam ter a participação de…",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Participante",
    },
    {
        "id": "octs5",
        "secao": "opinioes-ct",
        "prefixo": "octs5[SQ",
        "titulo": "Afirmações sobre ciência e tecnologia",
        "pergunta": "Marque por favor sua concordância ou discordância com "
                    "estas afirmações sobre ciência e tecnologia.",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Afirmação",
    },
    # --------------------------------------------------------------- opiniões DC
    {
        "id": "odc1",
        "secao": "opinioes-dc",
        "prefixo": "odc1[SQ",
        "titulo": "Modelos de comunicação entre ciência e público",
        "pergunta": "As afirmações que seguem contêm várias posições que podem "
                    "ter consequências para a comunicação entre a ciência e o "
                    "público. Qual a sua opinião sobre cada afirmação?",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Afirmação",
    },
    {
        "id": "odc2",
        "secao": "opinioes-dc",
        "colunas": ["odc2"],
        "titulo": "Importância da comunicação com o público",
        "pergunta": "Considerando todas as atividades do seu trabalho, que "
                    "importância você atribui à comunicação com o público "
                    "não-especialista?",
        "forma": "unica",
        "rotulo_item": "Importância",
    },
    {
        "id": "odc3",
        "secao": "opinioes-dc",
        "prefixo": "odc3[SQ",
        "titulo": "Importância de cada público",
        "pergunta": "Considerando o seu trabalho atual, qual importância você "
                    "atribui à comunicação com os seguintes públicos não "
                    "especialistas:",
        "forma": "likert",
        "sentido": "desc",
        "neutro": "Não sei",
        "rotulo_item": "Público",
    },
    # -------------------------------------------------------------- motivações
    {
        "id": "MO01",
        "secao": "motivacoes",
        "prefixo": "MO01",
        "titulo": "Motivações para divulgar",
        "pergunta": "Marque os elementos mais importantes que, para você "
                    "pessoalmente, são uma motivação para comunicar seu "
                    "trabalho a um público não-especialista (no máximo 3).",
        "forma": "simnao",
        "rotulo_item": "Motivação",
    },
    {
        "id": "MO02",
        "secao": "motivacoes",
        "prefixo": "MO02",
        "titulo": "Obstáculos para divulgar",
        "pergunta": "Marque os elementos mais importantes que, para você "
                    "pessoalmente, são um obstáculo para comunicar seu "
                    "trabalho a um público não-especialista (no máximo 3).",
        "forma": "simnao",
        "rotulo_item": "Obstáculo",
    },
    {
        "id": "MO04",
        "secao": "motivacoes",
        "prefixo": "MO04",
        "titulo": "Formação em divulgação científica",
        "pergunta": "Você conhece ou participou de alguma destas iniciativas "
                    "de formação em divulgação científica?",
        "forma": "likert",
        "sentido": "asc",
        "neutro": "Não conheço",
        "rotulo_item": "Iniciativa",
    },
]

# O bloco sociodemográfico não cruza com as 11 variáveis: ELE é as 11
# variáveis. Sua família de testes são os 55 pares distintos entre si.
BLOCO_SOCIO = {
    "id": "socio",
    "secao": "perfil",
    "titulo": "Perfil dos respondentes",
    "pergunta": "Distribuição dos respondentes em cada característica "
                "sociodemográfica, e associação entre elas.",
    "forma": "unica",
    "rotulo_item": "Característica",
}
