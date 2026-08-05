"""
Carregamento e preparação dos dados do survey PQ.

Mudanças em relação à versão anterior
-------------------------------------
1. Caminhos resolvidos a partir do próprio arquivo (`pathlib`), não do
   diretório de trabalho do processo. Antes, `pd.read_csv("data_tratado.csv")`
   só funcionava se o app fosse iniciado exatamente na raiz do repositório.

2. `@st.cache_data` e carregamento preguiçoso. Antes, o módulo lia o CSV e
   calculava as 165 tabelas de contingência NO IMPORT — inclusive para quem
   abria só a página inicial. Isso entrava direto no tempo de despertar do
   app. Agora a tabela de associações só é calculada quando alguém a acessa,
   e é lida de um CSV pré-computado quando ele existe (veja `precompute.py`).

3. Correção de Benjamini–Hochberg (FDR) nos 165 testes simultâneos
   (15 atividades × 11 variáveis). Com α = 0,05 e sem correção, o esperado sob
   a hipótese nula é ~8 resultados "significativos" por puro acaso — e eram
   exatamente esses que a tabela destacava em amarelo. Nos dados reais a
   correção leva de 60 para 57 cruzamentos significativos.

4. V de Cramér ao lado de cada p. Com n ≈ 1.500 por cruzamento, quase tudo dá
   significativo: 57 dos 165 cruzamentos são significativos, mas 48 deles têm
   efeito desprezível (V < 0,10) e o mais forte de todo o survey chega a
   V = 0,154. O que o leitor precisa saber é o tamanho do efeito, não a
   existência dele.

5. `classificar_vinculo` passou a tratar ausentes — veja o comentário na
   função. Esse era o defeito mais grave do arquivo.

As variáveis de módulo (`df`, `varmap`, `tabela_p`, `tabela_estilizada`, ...)
continuam disponíveis com os mesmos nomes, então nenhuma página precisa mudar.
"""

from __future__ import annotations

import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from statsmodels.stats.multitest import multipletests

BASE_DIR = Path(__file__).resolve().parent
CAMINHO_DADOS = BASE_DIR / "data_tratado.csv"
CAMINHO_CACHE_ASSOC = BASE_DIR / "dados" / "tabela_associacoes.csv"

ALFA = 0.05

# --------------------------------------------------------------------------- #
# Cache: usa o do Streamlit quando disponível, e um no-op fora dele, para que
# este módulo continue importável em scripts, notebooks e no build estático.
# --------------------------------------------------------------------------- #
try:
    import streamlit as st

    _cache = st.cache_data(show_spinner=False)
except Exception:  # pragma: no cover

    def _cache(func):
        from functools import lru_cache

        return lru_cache(maxsize=1)(func)


# --------------------------------------------------------------------------- #
# Metadados
# --------------------------------------------------------------------------- #
def _carregar_mapa(nome: str) -> dict:
    """Lê `nome.json` se existir, senão `nome.pkl`.

    Metadados de um artefato de pesquisa público deveriam ser legíveis no
    GitHub e versionáveis com diff útil. Rode `precompute.py --exportar-json`
    para gerar os JSON e depois aposente os pickles.
    """
    caminho_json = BASE_DIR / f"{nome}.json"
    if caminho_json.exists():
        with open(caminho_json, encoding="utf-8") as f:
            return json.load(f)
    with open(BASE_DIR / f"{nome}.pkl", "rb") as f:
        return dict(pickle.load(f))


varmap = _carregar_mapa("varmap")
categories = _carregar_mapa("categories")
categories["CE14"] = [
    "Até 5 anos",
    "6 a 10 anos",
    "11 a 20 anos",
    "21 a 35 anos",
    "Acima de 35 anos",
]

ordered_categories = [
    "Nenhuma vez",
    "1 vez",
    "2 vezes",
    "3 vezes",
    "4 vezes",
    "5 vezes",
    "mais de 5 vezes",
]

codigo_atividades = {k: v for k, v in varmap.items() if "adc1[SQ" in k}
atividades = list(codigo_atividades.values())
variaveis_demograficas = {k: v for k, v in varmap.items() if "CE" in k}

codigo_variaveis = {
    "CE02": "Sexo",
    "CE03": "Escolaridade_Mae",
    "CE04": "Cor_Raca",
    "CE05": "Religiao",
    "CE06": "Importancia_Religiao",
    "CE10": "Ciencia_BasicaXAplicada",
    "CE07": "Orientacao_Politica",
    "CE08": "Nivel_Bolsa_CNPq",
    "CE11": "GdeArea_CNPq",
    "CE13": "Regiao_Geografica",
    "CE14": "Tempo_Vinculo",
}

perguntas_socio = {
    "CE02": "Qual é o seu sexo?",
    "CE03": "Até qual série a sua mãe estudou na escola, ou seja, qual a escolaridade dela?",
    "CE04": "Qual é a sua cor ou raça?",
    "CE05": "Você pertence a alguma religião ou grupo religioso/espiritualista?",
    "CE06": "Você diria que a religião, em sua vida pessoal, é...",
    "CE10": "A ciência que você desenvolve hoje é melhor identificada como:",
    "CE07": (
        "Do ponto de vista do posicionamento político, você considera que a "
        "expressão que mais se aproxima de sua orientação é..."
    ),
    "CE08": "Em qual nível de Bolsa Produtividade do CNPq você se enquadra?",
    "CE11": "Qual é a grande área do conhecimento de sua atuação?",
    "CE13": "Em qual região do Brasil sua instituição se encontra?",
    "CE14": "Há quantos anos você está vinculado a esta universidade ou instituto de pesquisa?",
}


# --------------------------------------------------------------------------- #
# Tempo de vínculo (CE14)
# --------------------------------------------------------------------------- #
def extrair_dois_primeiros_numeros(entrada):
    """Extrai o número de anos declarado em texto livre.

    Se houver caracteres não numéricos entre os dígitos, devolve só o primeiro
    número (ex.: "10 anos e 5 meses" -> 10; "1 5" -> 15).
    """
    if pd.isna(entrada):
        return None

    numeros = re.findall(r"\d+", str(entrada))
    if not numeros:
        return None
    if len(numeros) == 1:
        return int(numeros[0])

    primeiro, segundo = numeros[0], numeros[1]
    pos_primeiro = str(entrada).find(primeiro)
    pos_segundo = str(entrada).find(segundo, pos_primeiro + len(primeiro))
    if pos_segundo > pos_primeiro + len(primeiro):
        return int(primeiro)
    return int(primeiro + segundo)


ANO_DA_COLETA = 2023


def classificar_vinculo(idade):
    """Converte anos de vínculo em faixa.

    ⚠️ A versão anterior desta função não tratava ausentes. Como
    `pd.Series.apply` transforma `None` em `NaN`, e toda comparação com `NaN`
    é False, os ausentes caíam no `else` final e viravam "Acima de 35 anos".
    Nos dados reais isso classificava 387 pessoas que deixaram a pergunta em
    branco — 20% da amostra — como o grupo de maior tempo de vínculo, inflando
    essa faixa de 221 para 619 respondentes.
    """
    if idade is None or (isinstance(idade, float) and np.isnan(idade)):
        return None

    idade = int(idade)

    # Quem respondeu o ANO de ingresso em vez da duração ("Desde 2006",
    # "Na UnB desde 1986"). Antes viravam 2006 e 1986 "anos de vínculo".
    if 1900 <= idade <= ANO_DA_COLETA:
        idade = ANO_DA_COLETA - idade
    elif idade > 100:
        return None

    if idade <= 5:
        return "Até 5 anos"
    if idade <= 10:
        return "6 a 10 anos"
    if idade <= 20:
        return "11 a 20 anos"
    if idade <= 35:
        return "21 a 35 anos"
    return "Acima de 35 anos"


# --------------------------------------------------------------------------- #
# Dados
# --------------------------------------------------------------------------- #
@_cache
def carregar_dados() -> pd.DataFrame:
    dados = pd.read_csv(CAMINHO_DADOS)
    dados["CE05"] = dados["CE05"].str.strip()
    dados["CE14"] = dados["CE14"].apply(extrair_dois_primeiros_numeros).apply(
        classificar_vinculo
    )
    return dados


@_cache
def frequencias_atividades() -> pd.DataFrame:
    """Contagem por atividade × frequência, com a frequência ordenada."""
    dados = carregar_dados()
    colunas = [c for c in dados.columns if c.startswith("adc1")]

    longo = dados.melt(
        value_vars=colunas, var_name="Atividade", value_name="Frequência"
    )
    longo["Atividade"] = longo["Atividade"].map(varmap)
    longo["Frequência"] = pd.Categorical(
        longo["Frequência"], categories=ordered_categories, ordered=True
    )

    freq = (
        longo.dropna(subset=["Frequência"])
        .groupby(["Atividade", "Frequência"], observed=True)
        .size()
        .reset_index(name="Contagem")
    )
    freq["Frequência"] = pd.Categorical(
        freq["Frequência"], categories=ordered_categories, ordered=True
    )
    return freq.sort_values(["Atividade", "Frequência"])


@_cache
def atividades_ordenadas() -> list[str]:
    """Atividades em ordem decrescente de 'Nenhuma vez'."""
    freq = frequencias_atividades()
    nunca = freq[freq["Frequência"] == "Nenhuma vez"]
    return (
        nunca.set_index("Atividade")["Contagem"]
        .sort_values(ascending=False)
        .index.tolist()
    )


# --------------------------------------------------------------------------- #
# Tabela de associações
# --------------------------------------------------------------------------- #
def _v_de_cramer(chi2: float, tabela: pd.DataFrame) -> float:
    """V de Cramér com correção de viés de Bergsma (2013)."""
    n = float(tabela.to_numpy().sum())
    if n <= 1:
        return float("nan")
    r, k = tabela.shape
    phi2 = chi2 / n
    phi2_corr = max(0.0, phi2 - ((k - 1) * (r - 1)) / (n - 1))
    r_corr = r - ((r - 1) ** 2) / (n - 1)
    k_corr = k - ((k - 1) ** 2) / (n - 1)
    denom = min(k_corr - 1, r_corr - 1)
    return float(np.sqrt(phi2_corr / denom)) if denom > 0 else float("nan")


def calcular_associacoes(
    dados: pd.DataFrame | None = None,
    linhas: dict[str, str] | None = None,
    colunas: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Tabela longa com p bruto, p ajustado (FDR), V de Cramér e n.

    A correção de Benjamini–Hochberg é aplicada sobre TODOS os testes de uma
    vez, que é o conjunto de comparações efetivamente realizado.
    """
    dados = carregar_dados() if dados is None else dados
    linhas = codigo_atividades if linhas is None else linhas
    colunas = codigo_variaveis if colunas is None else colunas

    registros = []
    for cod_linha, rot_linha in linhas.items():
        for cod_coluna, rot_coluna in colunas.items():
            tabela = pd.crosstab(dados[cod_linha], dados[cod_coluna])
            try:
                chi2, p, _, _ = chi2_contingency(tabela)
                v = _v_de_cramer(float(chi2), tabela)
                n = int(tabela.to_numpy().sum())
            except ValueError:
                chi2, p, v, n = np.nan, np.nan, np.nan, 0
            registros.append(
                {
                    "codigo_linha": cod_linha,
                    "linha": rot_linha,
                    "codigo_coluna": cod_coluna,
                    "coluna": rot_coluna,
                    "chi2": chi2,
                    "p": p,
                    "v_cramer": v,
                    "n": n,
                }
            )

    resultado = pd.DataFrame(registros)

    validos = resultado["p"].notna()
    resultado["p_ajustado"] = np.nan
    resultado["significativo"] = False
    if validos.any():
        rejeitado, p_adj, _, _ = multipletests(
            resultado.loc[validos, "p"].to_numpy(), alpha=ALFA, method="fdr_bh"
        )
        resultado.loc[validos, "p_ajustado"] = p_adj
        resultado.loc[validos, "significativo"] = rejeitado

    return resultado


@_cache
def associacoes() -> pd.DataFrame:
    """Lê o CSV pré-computado se houver; senão calcula (e é cacheado)."""
    if CAMINHO_CACHE_ASSOC.exists():
        try:
            return pd.read_csv(CAMINHO_CACHE_ASSOC)
        except Exception:
            pass
    return calcular_associacoes()


def matriz(valor: str = "v_cramer") -> pd.DataFrame:
    """Pivô atividades × variáveis para uma das métricas."""
    return associacoes().pivot(index="linha", columns="coluna", values=valor)


def estilizar_associacoes():
    """Tabela-resumo colorida por tamanho de efeito, não por p.

    Antes, o destaque amarelo marcava p < 0,05 sem correção — o que, com 176
    testes e n ≈ 1.900, pintava quase tudo e não distinguia nada. Aqui a cor
    é o V de Cramér (o que interessa) e o p ajustado entra como filtro:
    células não significativas após FDR ficam esmaecidas.
    """
    v = matriz("v_cramer")
    sig = matriz("significativo").reindex_like(v).fillna(False).astype(bool)

    def esmaecer(col):
        return ["" if s else "color: #bbbbbb;" for s in sig[col.name]]

    return (
        v.style.background_gradient(cmap="YlOrRd", vmin=0, vmax=0.35)
        .apply(esmaecer, axis=0)
        .format("{:.2f}", na_rep="—")
        .set_caption(
            "V de Cramér (0 = sem associação). Células esmaecidas não são "
            f"significativas a α = {ALFA} após correção FDR de Benjamini–Hochberg."
        )
    )


# --------------------------------------------------------------------------- #
# Compatibilidade com o código existente
#
# `df`, `dff_freq`, `tabela_p` etc. continuam funcionando com `from
# data_process import ...`, mas agora são resolvidos sob demanda (PEP 562):
# quem abre só a página inicial não paga o custo das 176 tabelas.
# --------------------------------------------------------------------------- #
_PREGUICOSOS = {
    "df": carregar_dados,
    "dff_freq": frequencias_atividades,
    "ordered_activities": atividades_ordenadas,
    "tabela_p": lambda: matriz("p_ajustado"),
    "tabela_p_bruto": lambda: matriz("p"),
    "tabela_v": lambda: matriz("v_cramer"),
    "tabela_estilizada": estilizar_associacoes,
}


def __getattr__(nome: str):
    if nome in _PREGUICOSOS:
        valor = _PREGUICOSOS[nome]()
        globals()[nome] = valor
        return valor
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")


def __dir__():
    return sorted(list(globals()) + list(_PREGUICOSOS))


# --------------------------------------------------------------------------- #
# Pesos de pós-estratificação
#
# Ficam aqui, e não em `ponderacao.py`, apenas para as páginas importarem do
# mesmo lugar que o resto. Ver a nota metodológica para o que os pesos corrigem
# — e para o que eles não corrigem.
# --------------------------------------------------------------------------- #
@_cache
def pesos_pos_estratificacao() -> pd.Series:
    """Peso de cada respondente, `NaN` para quem não é ponderável."""
    from ponderacao import calcular_pesos

    return calcular_pesos(carregar_dados())


def percentuais(coluna: str, ponderado: bool = True) -> pd.Series:
    """Distribuição percentual de uma coluna, ponderada por padrão."""
    dados = carregar_dados()
    if not ponderado:
        return dados[coluna].value_counts(normalize=True) * 100

    w = pesos_pos_estratificacao()
    validos = w.notna() & dados[coluna].notna()
    soma = w[validos].groupby(dados.loc[validos, coluna], observed=True).sum()
    return soma / soma.sum() * 100


_PREGUICOSOS["pesos"] = pesos_pos_estratificacao
