#!/usr/bin/env python
"""
Gera os agregados que alimentam o site estático em Quarto.

Por que este script existe
--------------------------
O espaço de estados do dashboard é finito e enumerável: o dado está congelado
desde 2023, não há entrada do usuário e não há banco. São 87 variáveis
temáticas × 11 sociodemográficas, mais os 55 pares entre as próprias
sociodemográficas — 1.012 cruzamentos, cada um com tabela de contingência,
esperados, resíduos, qui-quadrado, p ajustado, V de Cramér e n. Tudo é
calculado uma vez, aqui, e servido como arquivo estático. Não existe razão
para manter um processo Python vivo.

O que este script NÃO faz
-------------------------
Nenhum cálculo estatístico novo. `graphs.analisar_associacao()` já devolve
tudo o que o site precisa de cada cruzamento; a correção de Benjamini–Hochberg
vem de `statsmodels`. Se você sentir vontade de reimplementar uma estatística
aqui, provavelmente há um bug em outro lugar.

Famílias de teste
-----------------
O FDR é aplicado POR BLOCO TEMÁTICO, não sobre o site inteiro: cada bloco de
perguntas do questionário (as 15 atividades, as 6 afirmações sobre riscos, as
13 motivações…) é corrigido pelo número de testes que ele de fato realiza
contra as 11 variáveis sociodemográficas. Os 55 pares sociodemográficos são
uma família à parte. A consequência prática é que a página de atividades
mantém 165 testes. O total global aparece em `meta` para quem quiser a leitura
mais conservadora.

Controle de divulgação
----------------------
Categorias raras de quatro variáveis sensíveis são agregadas antes de qualquer
cruzamento — ver `blocos.AGREGACOES`. Isso reduz de 355 para 43 as células com
1 a 4 pessoas nos pares sociodemográficos, que é o único bloco em que as duas
variáveis do cruzamento são atributos protegidos.

Privacidade
-----------
A saída contém apenas agregados: contagens de células de tabelas de
contingência bivariadas e estatísticas derivadas delas. Nenhuma linha de
`data_tratado.csv` sobrevive ao build. `--auditar` relata a menor contagem de
célula publicada.

Uso
---
    python build.py                  # escreve site/dados/*.json
    python build.py --auditar        # + relatório de células pequenas
    python build.py --conferir       # + confere contra os números conhecidos

Dependências: as mesmas do app (pandas, numpy, scipy, statsmodels).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

import data_process as dp
import graphs as gr
from blocos import (
    AGREGACOES,
    BLOCOS,
    BLOCO_SOCIO,
    DESCRICAO_ATIVIDADES,
    ORDEM_AGREGADA,
    ORDENS_SOBRESCRITAS,
    ROTULOS_SOCIO,
    SECOES,
)

BASE_DIR = Path(__file__).resolve().parent
PASTA_SAIDA = BASE_DIR / "site" / "dados"
CAMINHO_PESOS = BASE_DIR / "dados" / "pesos_pos_estratificacao.csv"

# Casas decimais na serialização. Resíduos e esperados são grandezas de
# leitura, não de reprocessamento: 3 casas preservam tudo o que o gráfico e o
# hover mostram e cortam o arquivo quase pela metade.
CASAS_ESPERADO = 2
CASAS_RESIDUO = 3
CASAS_PCT = 2

# Números conhecidos da página de atividades. `--conferir` falha se o build
# divergir deles: é a rede de segurança contra uma refatoração silenciosamente
# mudar a estatística publicada.
#
# ⚠️ Estes valores MUDARAM em 2026-08-05, e a mudança foi deliberada. Antes da
# agregação de categorias raras (`blocos.AGREGACOES`, controle de divulgação),
# eram 60 significativos sem correção e 41 após o FDR — os números do handoff e
# do `dados/tabela_associacoes.csv` comitado. Colapsar as categorias de
# escolaridade da mãe, cor/raça, religião e orientação política reduz os graus
# de liberdade das tabelas que envolvem essas quatro variáveis, e três
# cruzamentos deixam de cruzar o limiar. O V de Cramér mediano e o máximo não
# se movem, o que é o esperado: a agregação junta células raras, não altera a
# estrutura da associação.
#
# Se estes números voltarem a mudar sem que alguém tenha mexido em AGREGACOES,
# é bug.
ESPERADO_ADC1 = {
    "n_testes": 165,
    "sem_correcao": 57,
    "apos_fdr": 39,
    "v_mediana": 0.036,
    "v_maximo": 0.154,
}


# --------------------------------------------------------------------------- #
# Serialização
# --------------------------------------------------------------------------- #
def _num(valor, casas: int | None = None):
    """Número JSON, ou None se não for finito.

    `float('nan')` vira o literal `NaN`, que não é JSON válido e quebra
    `JSON.parse` no navegador — daí a conversão explícita para `null`.
    """
    if valor is None:
        return None
    f = float(valor)
    if not math.isfinite(f):
        return None
    return round(f, casas) if casas is not None else f


def _matriz(df: pd.DataFrame, casas: int | None = None) -> list[list]:
    return [[_num(v, casas) for v in linha] for linha in df.to_numpy()]


def escrever_json(caminho: Path, dados: dict) -> int:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dados, f, ensure_ascii=False, allow_nan=False,
                  separators=(",", ":"))
    return caminho.stat().st_size


# --------------------------------------------------------------------------- #
# Pesos
# --------------------------------------------------------------------------- #
def carregar_pesos(dados: pd.DataFrame) -> pd.Series | None:
    """Peso de pós-estratificação por respondente, ou None se indisponível.

    Prefere `dados/pesos_pos_estratificacao.csv`, que é o artefato comitado.
    `ponderacao.MARGENS_POPULACAO` está vazio no repositório (as margens do
    CNPq nunca foram transcritas para o módulo), então recalcular na hora
    levantaria erro — o CSV é a fonte de verdade hoje. Enquanto isso não for
    resolvido, os pesos existem mas não são reproduzíveis a partir do código.
    """
    if CAMINHO_PESOS.exists():
        try:
            serie = pd.read_csv(CAMINHO_PESOS, index_col=0)["peso"]
            serie.index = serie.index.astype(int)
            return serie.reindex(dados.index)
        except Exception as erro:  # pragma: no cover
            print(f"  aviso: não foi possível ler {CAMINHO_PESOS.name}: {erro}")

    try:
        return dp.pesos_pos_estratificacao()
    except Exception as erro:
        print(f"  aviso: pesos indisponíveis ({erro}); pct_ponderado ficará nulo")
        return None


def resumo_dos_pesos(pesos: pd.Series | None) -> dict:
    """n ponderável, n efetivo de Kish e efeito de desenho."""
    if pesos is None:
        return {"n_ponderavel": None, "n_efetivo": None, "deff": None}
    w = pesos.dropna().to_numpy(dtype=float)
    if w.size == 0:
        return {"n_ponderavel": 0, "n_efetivo": None, "deff": None}
    n_efetivo = w.sum() ** 2 / np.square(w).sum()
    return {
        "n_ponderavel": int(w.size),
        "n_efetivo": int(round(n_efetivo)),
        "deff": _num(w.size / n_efetivo, 3),
    }


# --------------------------------------------------------------------------- #
# Variáveis
# --------------------------------------------------------------------------- #
def agregar_categorias(dados: pd.DataFrame) -> pd.DataFrame:
    """Colapsa as categorias raras das variáveis sensíveis.

    Roda ANTES de qualquer cruzamento, para que célula pequena não chegue a
    ser calculada. Ver `blocos.AGREGACOES` para o porquê de cada agrupamento.
    """
    d = dados.copy()
    for var, mapa in AGREGACOES.items():
        if var in d.columns:
            d[var] = d[var].map(lambda v: mapa.get(v, v) if pd.notna(v) else v)
    return d


def categorias_da_variavel(dados: pd.DataFrame, var: str) -> list[str]:
    """Ordem canônica das categorias, com as observadas fora dela no fim.

    Delega a `graphs.categorias_de`, que já trata o `defaultdict` vazio de
    `categories.pkl` e as variáveis Sim/Não. Repetir a lógica aqui criaria uma
    segunda fonte de verdade para a ordem dos eixos — e a ordem dos eixos é
    justamente o que o handoff manda conferir.
    """
    if var in ORDEM_AGREGADA:
        cats = list(ORDEM_AGREGADA[var])
    elif var in ORDENS_SOBRESCRITAS:
        cats = list(ORDENS_SOBRESCRITAS[var])
    else:
        cats = gr.categorias_de(var, dados[var])
        cats = [] if cats is None else [str(c) for c in cats]

    observadas = [str(c) for c in pd.unique(dados[var].dropna())]
    faltando = [c for c in observadas if c not in cats]
    return cats + sorted(faltando)


def aplicar_ordem(dados: pd.DataFrame) -> pd.DataFrame:
    """Fixa as ordens sobrescritas como categóricas ordenadas.

    `analisar_associacao` respeita uma categórica ordenada já definida pelo
    chamador (é o mecanismo pelo qual as páginas do Streamlit invertiam
    `octs1` e `odc2`). Definir aqui, uma vez, garante que a ordem do eixo do
    mosaico seja a mesma da marginal e a mesma declarada em `variaveis`.
    """
    d = dados.copy()
    for var, cats in ORDENS_SOBRESCRITAS.items():
        if var in d.columns:
            d[var] = pd.Categorical(d[var], categories=cats, ordered=True)
    return d


def colunas_do_bloco(dados: pd.DataFrame, bloco: dict) -> list[str]:
    if "colunas" in bloco:
        return [c for c in bloco["colunas"] if c in dados.columns]
    return [c for c in dados.columns if c.startswith(bloco["prefixo"])]


# --------------------------------------------------------------------------- #
# Marginais
# --------------------------------------------------------------------------- #
def marginal(dados: pd.DataFrame, var: str, cats: list[str],
             pesos: pd.Series | None) -> dict:
    """Distribuição univariada, bruta e ponderada, na ordem canônica."""
    coluna = dados[var].astype("object").where(dados[var].notna())
    contagens = coluna.value_counts().reindex(cats).fillna(0).astype(int)
    n = int(contagens.sum())
    pct = (contagens / n * 100) if n else contagens.astype(float)

    pct_ponderado = None
    if pesos is not None:
        validos = pesos.notna() & coluna.notna()
        if validos.any():
            soma = pesos[validos].groupby(coluna[validos]).sum()
            soma = soma.reindex(cats).fillna(0.0)
            total = float(soma.sum())
            if total > 0:
                pct_ponderado = [_num(v, CASAS_PCT) for v in soma / total * 100]

    return {
        "categorias": cats,
        "contagens": [int(v) for v in contagens],
        "pct": [_num(v, CASAS_PCT) for v in pct],
        "pct_ponderado": pct_ponderado,
        "n": n,
        "n_ausentes": int(len(dados) - n),
    }


# --------------------------------------------------------------------------- #
# Cruzamentos
# --------------------------------------------------------------------------- #
def cruzamento(dados: pd.DataFrame, cod_linha: str, cod_coluna: str) -> dict:
    """Um cruzamento completo, pronto para o mosaico.

    Orientação: `observado[i][j]` tem i sobre as categorias da LINHA (a
    variável temática) e j sobre as da COLUNA (a sociodemográfica). O mosaico
    desenha a COLUNA no eixo x — a largura de cada faixa vertical é
    proporcional à marginal da variável sociodemográfica — e a LINHA no eixo y,
    dentro de cada faixa. É a mesma orientação do app Streamlit, onde
    `plot_mosaic_with_residuals` era chamado com var1 = sociodemográfica e
    var2 = temática.

    `p_ajustado` e `significativo` NÃO são preenchidos aqui: dependem da
    família inteira e são acrescentados depois, em `aplicar_fdr`.
    """
    stats = gr.analisar_associacao(dados, cod_linha, cod_coluna)
    tabela = stats["tabela"]

    return {
        "linha": cod_linha,
        "coluna": cod_coluna,
        "cat_linha": [str(c) for c in tabela.index],
        "cat_coluna": [str(c) for c in tabela.columns],
        "observado": [[int(v) for v in linha] for linha in tabela.to_numpy()],
        "esperado": _matriz(stats["esperado"], CASAS_ESPERADO),
        "residuos": _matriz(stats["residuos"], CASAS_RESIDUO),
        "chi2": _num(stats["chi2"], 3),
        "gl": int(stats["gl"]),
        "p": _num(stats["p"]),
        "v_cramer": _num(stats["v_cramer"], 4),
        "classificacao": gr.classificar_v(stats["v_cramer"]),
        "n": int(stats["n"]),
        "n_excluidos": int(stats["n_excluidos"]),
        "esperado_minimo": _num(stats["esperado_minimo"], 2),
        "prop_celulas_esperado_baixo": _num(stats["prop_celulas_esperado_baixo"], 3),
    }


def aplicar_fdr(cruzamentos: list[dict], alfa: float) -> dict:
    """Benjamini–Hochberg sobre uma família, escrevendo nos próprios dicts.

    A família é o conjunto de comparações efetivamente realizado naquele
    bloco. Corrigir sobre o site inteiro seria mais conservador; corrigir
    cruzamento a cruzamento (isto é, não corrigir) é o erro que a versão
    original cometia, com ~8 "significativos" esperados por puro acaso a cada
    165 testes.
    """
    ps = np.array([c["p"] if c["p"] is not None else np.nan for c in cruzamentos])
    validos = np.isfinite(ps)

    for c in cruzamentos:
        c["p_ajustado"] = None
        c["significativo"] = False

    if validos.any():
        rejeitado, p_adj, _, _ = multipletests(ps[validos], alpha=alfa,
                                               method="fdr_bh")
        for c, r, pa in zip(np.array(cruzamentos, dtype=object)[validos],
                            rejeitado, p_adj):
            c["p_ajustado"] = _num(pa)
            c["significativo"] = bool(r)

    return {
        "n_testes": int(validos.sum()),
        "sem_correcao": int((ps[validos] < alfa).sum()) if validos.any() else 0,
        "apos_fdr": sum(1 for c in cruzamentos if c["significativo"]),
        # Entre os significativos, quantos têm efeito desprezível (V < 0,10).
        # É o número que impede a leitura preguiçosa de "significativo, logo
        # importante" — e por isso ele é publicado ao lado do outro.
        "apos_fdr_desprezivel": sum(
            1 for c in cruzamentos
            if c["significativo"] and c["v_cramer"] is not None
            and c["v_cramer"] < 0.10
        ),
        "v_mediana": _num(np.nanmedian([c["v_cramer"] for c in cruzamentos
                                        if c["v_cramer"] is not None]), 4),
        "v_maximo": _num(np.nanmax([c["v_cramer"] for c in cruzamentos
                                    if c["v_cramer"] is not None]), 4),
    }


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def construir() -> tuple[dict, dict[str, dict]]:
    brutos = dp.carregar_dados()
    dados = aplicar_ordem(agregar_categorias(brutos))
    pesos = carregar_pesos(dados)

    socio = dict(dp.codigo_variaveis)

    # ------------------------------------------------------------ variáveis
    print("Montando variáveis e marginais…")
    variaveis: dict[str, dict] = {}
    marginais: dict[str, dict] = {}

    def registrar(cod: str, rotulo: str, descricao: str, pergunta: str | None):
        cats = categorias_da_variavel(dados, cod)
        variaveis[cod] = {
            "rotulo": rotulo,
            "descricao": descricao,
            "pergunta": pergunta,
            "categorias": cats,
        }
        marginais[cod] = marginal(dados, cod, cats, pesos)

    for cod, rotulo_interno in socio.items():
        registrar(cod, ROTULOS_SOCIO.get(cod, rotulo_interno),
                  dp.perguntas_socio.get(cod, rotulo_interno),
                  dp.perguntas_socio.get(cod))

    # Distribuição univariada COMPLETA das variáveis agregadas. Uma contagem
    # de uma variável sozinha não revela combinação de atributos, então não há
    # razão para esconder que um respondente declarou islamismo — o risco
    # estava no cruzamento, e o cruzamento usa a versão agregada.
    marginais_detalhadas = {}
    for cod in AGREGACOES:
        if cod not in brutos.columns:
            continue
        cats = [str(c) for c in
                brutos[cod].value_counts().index]
        marginais_detalhadas[cod] = marginal(brutos, cod, cats, pesos)

    blocos_saida: list[dict] = []
    for bloco in BLOCOS:
        cols = colunas_do_bloco(dados, bloco)
        if not cols:
            print(f"  ⚠️  bloco {bloco['id']} sem colunas — pulando")
            continue
        for cod in cols:
            rotulo = dp.varmap.get(cod, cod)
            registrar(cod, rotulo,
                      DESCRICAO_ATIVIDADES.get(cod, rotulo),
                      bloco["pergunta"])
        blocos_saida.append({**{k: v for k, v in bloco.items()
                                if k not in ("prefixo", "colunas")},
                             "variaveis": cols})

    # ---------------------------------------------------------- cruzamentos
    print("Calculando os cruzamentos (FDR por bloco temático)…")
    por_secao: dict[str, dict[str, dict]] = {s["id"]: {} for s in SECOES}
    resumo_blocos: dict[str, dict] = {}
    falhas: list[str] = []
    total = 0

    for bloco in blocos_saida:
        familia: list[dict] = []
        for cod in bloco["variaveis"]:
            for cod_socio in socio:
                try:
                    familia.append(cruzamento(dados, cod, cod_socio))
                except ValueError as erro:
                    falhas.append(f"{cod}|{cod_socio}: {erro}")
        resumo = aplicar_fdr(familia, dp.ALFA)
        resumo_blocos[bloco["id"]] = resumo
        for c in familia:
            por_secao[bloco["secao"]][f"{c['linha']}|{c['coluna']}"] = c
        total += len(familia)
        print(f"  {bloco['id']:6s} {resumo['n_testes']:4d} testes · "
              f"{resumo['sem_correcao']:3d} sem correção · "
              f"{resumo['apos_fdr']:3d} após FDR · "
              f"V máx {resumo['v_maximo']:.3f}")

    # Pares sociodemográficos: família própria, só os 55 distintos. A diagonal
    # (uma variável contra si mesma) seria associação perfeita e não informa
    # nada; o par simétrico é o mesmo teste com os eixos trocados.
    codigos_socio = list(socio)
    familia_socio: list[dict] = []
    for i, a in enumerate(codigos_socio):
        for b in codigos_socio[i + 1:]:
            try:
                familia_socio.append(cruzamento(dados, a, b))
            except ValueError as erro:
                falhas.append(f"{a}|{b}: {erro}")
    resumo = aplicar_fdr(familia_socio, dp.ALFA)
    resumo_blocos["socio"] = resumo
    for c in familia_socio:
        por_secao["perfil"][f"{c['linha']}|{c['coluna']}"] = c
    total += len(familia_socio)
    print(f"  {'socio':6s} {resumo['n_testes']:4d} testes · "
          f"{resumo['sem_correcao']:3d} sem correção · "
          f"{resumo['apos_fdr']:3d} após FDR · "
          f"V máx {resumo['v_maximo']:.3f}")

    blocos_saida.append({**BLOCO_SOCIO, "variaveis": codigos_socio})

    if falhas:
        print(f"  ⚠️  {len(falhas)} cruzamento(s) sem tabela válida:")
        for f in falhas[:10]:
            print(f"      {f}")

    # ------------------------------------------------------ leitura global
    # Além do FDR por bloco, uma correção sobre TODOS os testes do site, só
    # para registro na nota metodológica: é o número que um revisor cético vai
    # pedir, e é melhor publicá-lo do que ser perguntado por ele.
    todos = [c for secao in por_secao.values() for c in secao.values()]
    ps = np.array([c["p"] for c in todos if c["p"] is not None])
    rej_global, _, _, _ = multipletests(ps, alpha=dp.ALFA, method="fdr_bh")

    meta = {
        "titulo": "Cientistas e divulgação científica: opiniões e práticas",
        "descricao": (
            "Survey com bolsistas de Produtividade em Pesquisa (PQ) do CNPq "
            "sobre percepções e práticas de divulgação científica."
        ),
        "n_total": int(len(dados)),
        **resumo_dos_pesos(pesos),
        "coleta": "jan-mar/2023",
        "alfa": dp.ALFA,
        "metodo_correcao": "Benjamini–Hochberg (FDR), por bloco temático",
        "escala_residuo": gr.ESCALA_RESIDUO_FIXA,
        "limiar_neutro": gr.LIMIAR_NEUTRO,
        "n_cruzamentos": total,
        "n_significativos": sum(1 for c in todos if c["significativo"]),
        "n_significativos_sem_correcao": int((ps < dp.ALFA).sum()),
        "n_significativos_fdr_global": int(rej_global.sum()),
        "v_cramer_mediana": _num(np.nanmedian([c["v_cramer"] for c in todos
                                               if c["v_cramer"] is not None]), 4),
        "v_cramer_maximo": _num(np.nanmax([c["v_cramer"] for c in todos
                                           if c["v_cramer"] is not None]), 4),
        "orientacao_mosaico": (
            "observado[i][j]: i sobre cat_linha (variável temática, eixo y do "
            "mosaico), j sobre cat_coluna (variável sociodemográfica, eixo x — "
            "largura das faixas)."
        ),
        "fonte": (
            "PEREIRA, M. Ciência, sociedade, divulgação científica: a visão "
            "dos cientistas. Dissertação, UFMG, 2023. "
            "http://hdl.handle.net/1843/55328"
        ),
        "autor": "Marcelo Pereira",
        "autor_url": "https://marcelo-pereira-pcst.github.io/",
    }

    base = {
        "meta": meta,
        "secoes": SECOES,
        "blocos": blocos_saida,
        "resumo_blocos": resumo_blocos,
        "ordem_socio": codigos_socio,
        "variaveis": variaveis,
        "marginais": marginais,
        "marginais_detalhadas": marginais_detalhadas,
        "categorias_agregadas": {
            cod: sorted(set(mapa.values())) for cod, mapa in AGREGACOES.items()
        },
    }
    return base, por_secao


# --------------------------------------------------------------------------- #
# Conferência e auditoria
# --------------------------------------------------------------------------- #
def tabela_de_efeitos(base: dict, por_secao: dict[str, dict]) -> dict:
    """Todos os cruzamentos em uma tabela só, com o essencial de cada um.

    Por que este arquivo existe separado dos `cruz-*.json`: para responder de
    relance à pergunta que o site inteiro evita responder de relance — "quão
    grandes são essas associações, afinal?". Navegar por 1.012 mosaicos até
    achar um vermelho é o comportamento que a correção de FDR não protege; ter
    a distribuição inteira dos tamanhos de efeito em uma tela é o antídoto.

    Formato colunar em vez de uma lista de objetos: com 1.012 linhas, repetir
    oito nomes de campo em cada uma quase triplica o arquivo.
    """
    linhas = []
    for secao, cruzamentos in por_secao.items():
        for cruz in cruzamentos.values():
            linhas.append([
                cruz["linha"], cruz["coluna"], secao,
                cruz["v_cramer"], cruz["p_ajustado"],
                1 if cruz["significativo"] else 0, cruz["n"],
            ])

    # Do maior efeito para o menor: é a ordem em que a tabela é útil.
    linhas.sort(key=lambda r: -(r[3] if r[3] is not None else -1))

    # A que bloco cada variável temática pertence, para o filtro por bloco.
    bloco_de = {}
    for b in base["blocos"]:
        for v in b["variaveis"]:
            bloco_de.setdefault(v, b["id"])

    vs = [r[3] for r in linhas if r[3] is not None]
    return {
        "colunas": ["linha", "coluna", "secao", "v_cramer", "p_ajustado",
                    "significativo", "n"],
        "linhas": linhas,
        "bloco_de": bloco_de,
        "resumo": {
            "total": len(linhas),
            "mediana": _num(np.median(vs), 4),
            "acima_010": int(sum(1 for v in vs if v > 0.10)),
            "acima_015": int(sum(1 for v in vs if v > 0.15)),
            "acima_020": int(sum(1 for v in vs if v > 0.20)),
            "acima_030": int(sum(1 for v in vs if v > 0.30)),
        },
    }


def conferir(base: dict) -> int:
    """Compara o build com os números conhecidos. Devolve o nº de divergências."""
    print("\nConferência contra os números conhecidos (página de atividades)")
    obtido = base["resumo_blocos"]["adc1"]
    divergencias = 0
    for chave, esperado in ESPERADO_ADC1.items():
        atual = obtido[chave]
        ok = (abs(atual - esperado) < 0.001 if isinstance(esperado, float)
              else atual == esperado)
        print(f"  {'✓' if ok else '✗'} {chave:14s} esperado {esperado:>7} · "
              f"obtido {atual:>7}")
        if not ok:
            divergencias += 1

    m = base["meta"]
    for chave, esperado in [("n_total", 1934), ("n_ponderavel", 1493),
                            ("n_efetivo", 1440)]:
        ok = m[chave] == esperado
        print(f"  {'✓' if ok else '✗'} {chave:14s} esperado {esperado:>7} · "
              f"obtido {m[chave]:>7}")
        if not ok:
            divergencias += 1

    # CE14: o defeito mais grave que o handoff manda vigiar.
    faixa = base["marginais"]["CE14"]
    idx = faixa["categorias"].index("Acima de 35 anos")
    valor = faixa["contagens"][idx]
    ok = valor == 223
    print(f"  {'✓' if ok else '✗'} CE14 'Acima de 35 anos' esperado 223 · "
          f"obtido {valor}" + ("" if ok else "  ← código antigo devolve 619"))
    if not ok:
        divergencias += 1
    return divergencias


def auditar(por_secao: dict[str, dict]) -> None:
    """Quão pequena é a menor célula publicada.

    Uma tabela de contingência bivariada não reidentifica ninguém do jeito que
    o microdado reidentificava — não há como cruzar seis variáveis a partir
    daqui. Ainda assim, células de contagem 1 ou 2 merecem um olhar consciente
    antes da publicação.
    """
    pequenas = []
    for secao, cruzamentos in por_secao.items():
        for chave, cruz in cruzamentos.items():
            for i, linha in enumerate(cruz["observado"]):
                for j, valor in enumerate(linha):
                    if 0 < valor <= 2:
                        pequenas.append((valor, secao, chave,
                                         cruz["cat_linha"][i],
                                         cruz["cat_coluna"][j]))
    pequenas.sort()
    print("\nAuditoria de células pequenas")
    print(f"  células com contagem 1 ou 2: {len(pequenas)}")
    n_perfil = sum(1 for p in pequenas if p[1] == "perfil")
    print(f"    delas, no bloco sociodemográfico × sociodemográfico: {n_perfil}"
          "  ← o único onde as duas variáveis são sensíveis")
    for valor, secao, chave, cl, cc in pequenas[:8]:
        print(f"    n={valor}  [{secao}] {chave}  {cl} × {cc}")
    if len(pequenas) > 8:
        print(f"    … e mais {len(pequenas) - 8}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    parser.add_argument("--auditar", action="store_true")
    parser.add_argument("--conferir", action="store_true")
    args = parser.parse_args()

    base, por_secao = construir()

    total_bytes = escrever_json(args.saida / "base.json", base)
    print(f"\n{args.saida.name}/base.json — {total_bytes / 1024:.0f} KB")
    for secao, cruzamentos in por_secao.items():
        tamanho = escrever_json(args.saida / f"cruz-{secao}.json",
                                {"cruzamentos": cruzamentos})
        total_bytes += tamanho
        print(f"{args.saida.name}/cruz-{secao}.json — {tamanho / 1024:>5.0f} KB "
              f"· {len(cruzamentos):4d} cruzamentos")

    efeitos = tabela_de_efeitos(base, por_secao)
    tamanho = escrever_json(args.saida / "efeitos.json", efeitos)
    total_bytes += tamanho
    print(f"{args.saida.name}/efeitos.json — {tamanho / 1024:>5.0f} KB "
          f"· {efeitos['resumo']['total']:4d} linhas")

    m = base["meta"]
    print(f"\ntotal: {total_bytes / 1024:.0f} KB · {m['n_cruzamentos']} "
          f"cruzamentos · {len(base['variaveis'])} variáveis")
    print(f"  significativos: {m['n_significativos_sem_correcao']} sem correção · "
          f"{m['n_significativos']} com FDR por bloco · "
          f"{m['n_significativos_fdr_global']} com FDR global")
    print(f"  V de Cramér: mediana {m['v_cramer_mediana']:.3f} · "
          f"máximo {m['v_cramer_maximo']:.3f}")

    if args.auditar:
        auditar(por_secao)
    if args.conferir:
        if conferir(base):
            raise SystemExit("build divergiu dos números conhecidos")


if __name__ == "__main__":
    main()
