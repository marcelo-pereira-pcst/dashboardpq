"""
Gráfico de mosaico com resíduos de Pearson.

Correções em relação à versão anterior
--------------------------------------
1. As cores agora são normalizadas antes de passarem pelo colormap.
   Antes: `plt.cm.coolwarm(residuo)` recebia o resíduo cru. Colormaps do
   matplotlib esperam valores em [0, 1] e fazem clipping fora disso, então
   resíduo 0 (neutro) era pintado com o azul mais intenso, o branco do
   colormap caía sobre resíduo +0,5 e tudo acima de +1 virava o mesmo
   vermelho saturado. A barra de cores usava ainda outra normalização, de
   modo que a legenda não descrevia o gráfico.

2. A ordenação das categorias volta a valer.
   Antes, `df_clean` era criado com `dropna()` ANTES das conversões para
   `pd.Categorical`, mas a tabela de contingência era montada a partir de
   `df_clean` — então os eixos saíam em ordem alfabética e toda a ordem
   definida em `categories.pkl` era descartada.

3. Nenhuma mutação do DataFrame de origem.
   As conversões acontecem em uma cópia local. Antes, `df[var] = ...`
   escrevia no objeto de módulo compartilhado entre reruns, páginas e
   usuários do mesmo processo — e o ramo MO01/MO02 podia transformar
   respostas em NaN permanentemente.

4. Tamanho de efeito (V de Cramér) e N explícito, porque com n ≈ 1.900 o
   valor de p sozinho quase não discrimina.
"""

from __future__ import annotations

import json
import pickle
from functools import lru_cache
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from scipy.stats import chi2_contingency
from statsmodels.graphics.mosaicplot import mosaic

BASE_DIR = Path(__file__).resolve().parent

# Escala de cor fixa para TODOS os mosaicos do site. Sem isso cada gráfico se
# renormaliza pelo próprio máximo e um vermelho forte em uma tela representa
# uma magnitude diferente de um vermelho forte em outra — o leitor não
# consegue comparar duas páginas. Use None para normalizar por gráfico.
ESCALA_RESIDUO_FIXA = 4.0

# Abaixo deste |resíduo| a célula é tratada como "dentro do esperado".
LIMIAR_NEUTRO = 2.0

CE14_FAIXAS = [
    "Até 5 anos",
    "6 a 10 anos",
    "11 a 20 anos",
    "21 a 35 anos",
    "Acima de 35 anos",
]

SIM_NAO = ["Sim", "Não"]


# --------------------------------------------------------------------------- #
# Metadados de categorias
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def carregar_categorias() -> dict[str, list[str]]:
    """Ordem canônica das categorias de cada variável.

    Prefere `categories.json` (legível no GitHub, versionável com diff útil,
    sem execução arbitrária) e cai para `categories.pkl` enquanto a migração
    não acontece.
    """
    caminho_json = BASE_DIR / "categories.json"
    if caminho_json.exists():
        with open(caminho_json, encoding="utf-8") as f:
            categorias = json.load(f)
    else:
        with open(BASE_DIR / "categories.pkl", "rb") as f:
            categorias = dict(pickle.load(f))

    categorias["CE14"] = list(CE14_FAIXAS)
    return categorias


def categorias_de(var: str, serie: pd.Series | None = None) -> list[str] | None:
    """Ordem das categorias de `var`, ou None se não houver ordem definida."""
    if var.startswith(("MO01", "MO02")):
        return list(SIM_NAO)

    categorias = carregar_categorias()
    # `categories.pkl` é um defaultdict: chaves ausentes devolvem [] em vez de
    # levantar KeyError. Passar [] para `pd.Categorical` transforma a coluna
    # inteira em NaN silenciosamente — daí o teste explícito por lista vazia.
    # Hoje ficam nessa situação: hab2, adc4, adc5, CE01, CE09, CE14, CE15.
    if categorias.get(var):
        return list(categorias[var])

    # Sem ordem canônica: preserva a ordem de aparição em vez de alfabetar.
    if serie is not None:
        return list(pd.unique(serie.dropna()))
    return None


# --------------------------------------------------------------------------- #
# Estatística
# --------------------------------------------------------------------------- #
def v_de_cramer(chi2: float, tabela: pd.DataFrame) -> float:
    """V de Cramér com correção de viés de Bergsma (2013).

    Varia de 0 a 1 e é comparável entre tabelas de dimensões diferentes, ao
    contrário do qui-quadrado e do valor de p.
    """
    n = float(tabela.to_numpy().sum())
    if n <= 1:
        return float("nan")

    r, k = tabela.shape
    phi2 = chi2 / n
    phi2_corr = max(0.0, phi2 - ((k - 1) * (r - 1)) / (n - 1))
    r_corr = r - ((r - 1) ** 2) / (n - 1)
    k_corr = k - ((k - 1) ** 2) / (n - 1)
    denom = min(k_corr - 1, r_corr - 1)
    if denom <= 0:
        return float("nan")
    return float(np.sqrt(phi2_corr / denom))


def classificar_v(v: float) -> str:
    """Rótulo verbal para o V de Cramér (referência: Cohen, 1988)."""
    if not np.isfinite(v):
        return "indeterminada"
    if v < 0.10:
        return "desprezível"
    if v < 0.20:
        return "fraca"
    if v < 0.30:
        return "moderada"
    if v < 0.50:
        return "forte"
    return "muito forte"


def analisar_associacao(df: pd.DataFrame, var1: str, var2: str) -> dict:
    """Tabela de contingência, resíduos de Pearson e estatísticas de associação.

    Aplica as categóricas ordenadas ANTES de remover ausentes, em uma cópia
    local — as duas correções centrais desta versão.
    """
    faltando = [v for v in (var1, var2) if v not in df.columns]
    if faltando:
        raise ValueError(f"Variáveis ausentes no DataFrame: {', '.join(faltando)}")

    d = df[[var1, var2]].copy()
    n_bruto = len(d)

    for var in (var1, var2):
        # Se o chamador já definiu uma ordem explícita, ela vence. Algumas
        # páginas invertem de propósito a ordem de `categories.pkl`
        # (`octs1`, `odc2` usam `[::-1]`), e sobrescrever isso aqui inverteria
        # os eixos desses gráficos.
        dtype = d[var].dtype
        if isinstance(dtype, pd.CategoricalDtype) and dtype.ordered:
            continue

        cats = categorias_de(var, d[var])
        if cats is not None:
            observadas = set(d[var].dropna().astype(str))
            desconhecidas = observadas - set(map(str, cats))
            if desconhecidas:
                # Não descarta silenciosamente respostas fora da lista canônica.
                cats = list(cats) + sorted(desconhecidas)
            d[var] = pd.Categorical(d[var], categories=cats, ordered=True)

    d = d.dropna()
    if d.empty:
        raise ValueError("Não há dados suficientes após a remoção de valores ausentes.")

    tabela = pd.crosstab(d[var1], d[var2])
    if tabela.size == 0 or tabela.to_numpy().sum() < 2:
        raise ValueError("Dados insuficientes para o teste qui-quadrado.")

    chi2, p, gl, esperado = chi2_contingency(tabela)
    residuos = (tabela - esperado) / np.sqrt(esperado)

    n_usado = int(tabela.to_numpy().sum())
    esperado_min = float(np.min(esperado))
    celulas_pequenas = float(np.mean(esperado < 5))

    return {
        "tabela": tabela,
        "esperado": pd.DataFrame(esperado, index=tabela.index, columns=tabela.columns),
        "residuos": residuos,
        "chi2": float(chi2),
        "p": float(p),
        "gl": int(gl),
        "v_cramer": v_de_cramer(float(chi2), tabela),
        "n": n_usado,
        "n_excluidos": n_bruto - n_usado,
        "n_bruto": n_bruto,
        # Diagnóstico de validade: o qui-quadrado assume esperados >= 5 na
        # maioria das células.
        "esperado_minimo": esperado_min,
        "prop_celulas_esperado_baixo": celulas_pequenas,
    }


def formatar_resumo(stats: dict, p_ajustado: float | None = None) -> str:
    """Linha de leitura para exibir acima do gráfico.

    Substitui o `p = 0.0001` solto por algo que o leitor consegue usar.
    """
    v = stats["v_cramer"]
    p = stats["p"] if p_ajustado is None else p_ajustado
    sufixo_p = "" if p_ajustado is None else " (ajustado, FDR)"

    texto_p = "p < 0,001" if p < 0.001 else f"p = {p:.3f}".replace(".", ",")
    texto_v = f"V de Cramér = {v:.2f}".replace(".", ",")
    texto_n = f"n = {stats['n']:,}".replace(",", ".")

    partes = [
        f"**Associação {classificar_v(v)}**",
        texto_v,
        f"{texto_p}{sufixo_p}",
        f"{texto_n} de {stats['n_bruto']:,}".replace(",", "."),
    ]
    linha = " · ".join(partes)

    if stats["n_excluidos"]:
        linha += f" ({stats['n_excluidos']} sem resposta em uma das variáveis)"
    if stats["prop_celulas_esperado_baixo"] > 0.2:
        linha += "  \n⚠️ Mais de 20% das células têm frequência esperada abaixo de 5 — o teste qui-quadrado perde confiabilidade aqui."
    return linha


# --------------------------------------------------------------------------- #
# Gráfico
# --------------------------------------------------------------------------- #
def _norma_residuos(residuos: pd.DataFrame) -> mpl.colors.Normalize:
    """Normalização SIMÉTRICA — garante que resíduo 0 caia no branco."""
    if ESCALA_RESIDUO_FIXA:
        vmax = float(ESCALA_RESIDUO_FIXA)
    else:
        vmax = float(np.nanmax(np.abs(residuos.to_numpy())))
        vmax = max(vmax, 1e-9)
    return mpl.colors.Normalize(vmin=-vmax, vmax=vmax)


def plot_mosaic_with_residuals(
    df,
    var1,
    var2,
    figsize=(14, 12),
    title=None,
    xlabel=None,
    ylabel=None,
    modo_cor="limiar",
    return_stats=False,
):
    """Mosaico colorido por resíduos de Pearson.

    Parâmetros novos
    ----------------
    modo_cor : {"limiar", "continuo", "significancia"}
        - "limiar" (padrão): gradiente contínuo, mas células com
          |resíduo| < LIMIAR_NEUTRO ficam neutras. O olho encontra o sinal
          sem que nada seja apagado.
        - "continuo": gradiente puro, sem banda neutra.
        - "significancia": comportamento antigo — tudo cinza se p >= 0,05.
          Mantido só para comparação; não recomendado, porque transforma um
          contínuo em interruptor e esconde o padrão da tabela.
    return_stats : bool
        Se True retorna (fig, n, stats). O padrão continua devolvendo
        (fig, n), então as chamadas existentes não quebram.
    """
    stats = analisar_associacao(df, var1, var2)
    tabela, residuos, p = stats["tabela"], stats["residuos"], stats["p"]

    norm = _norma_residuos(residuos)
    cmap = plt.get_cmap("coolwarm")
    neutro = "#f0f0f0"

    def cor_do_residuo(chave):
        try:
            valor = float(residuos.loc[chave[0], chave[1]])
        except (KeyError, IndexError):
            return {"color": neutro}

        if modo_cor == "significancia" and p >= 0.05:
            return {"color": "lightgray"}
        if modo_cor == "limiar" and abs(valor) < LIMIAR_NEUTRO:
            return {"color": neutro}
        return {"color": cmap(norm(valor))}

    fig, ax = plt.subplots(figsize=figsize)
    mosaic(
        tabela.stack(),
        properties=cor_do_residuo,
        ax=ax,
        gap=0.02,
        labelizer=lambda k: "",
    )

    mostrar_barra = not (modo_cor == "significancia" and p >= 0.05)
    if mostrar_barra:
        # MESMA `norm` usada para pintar as células: a legenda agora descreve
        # de fato o que está no gráfico.
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        axins = inset_axes(
            ax,
            width="2.5%",
            height="100%",
            loc="lower left",
            bbox_to_anchor=(1.05, 0.0, 1, 1),
            bbox_transform=ax.transAxes,
            borderpad=0,
        )
        cbar = fig.colorbar(sm, cax=axins, orientation="vertical")
        cbar.set_label("Resíduo de Pearson")
        if modo_cor == "limiar":
            for limite in (-LIMIAR_NEUTRO, LIMIAR_NEUTRO):
                cbar.ax.axhline(limite, color="0.35", lw=1.0, ls="--")
            cbar.ax.set_title("|r| < 2\nneutro", fontsize=8, pad=8)

    # Rótulos legíveis: quebra de linha em vez de rotação a 70°.
    ax.set_xticklabels(
        [t.get_text().replace(" ", "\n", 1) for t in ax.get_xticklabels()],
        rotation=45,
        ha="right",
        fontsize=10,
    )
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=10)

    if xlabel:
        ax.set_xlabel(xlabel, fontsize=14, labelpad=20)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=14)
    if title:
        ax.set_title(title, fontsize=16)

    fig.subplots_adjust(right=0.82, bottom=0.22, left=0.16)

    if return_stats:
        return fig, stats["n"], stats
    return fig, stats["n"]
