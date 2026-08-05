"""
Pesos de pós-estratificação para o survey PQ.

Por que ponderar
----------------
A amostra foi desenhada de forma estratificada e proporcional à população de
bolsistas PQ por grande área, sexo, região e nível da bolsa. Mas o que se
observa no fim não é a amostra desenhada: é a amostra que respondeu. A taxa de
resposta caiu ao longo do questionário (96% no consentimento, 77% no bloco
sociodemográfico, que é o último), e 366 pessoas abandonaram antes de declarar
qualquer característica. Se essa evasão não foi igual entre estratos — e
raramente é — as frequências marginais do dashboard estão enviesadas.

A pós-estratificação corrige isso reponderando os respondentes para que suas
margens reproduzam as margens conhecidas da população.

Método
------
Ajuste proporcional iterativo (raking / IPF). Usa apenas as margens de cada
variável, não a distribuição conjunta — que é o caso aqui, já que o CNPq
publica totais por área, por sexo, por região e por nível, mas não a tabela
cruzada das quatro.

Limitações que precisam estar na nota metodológica
--------------------------------------------------
1. Os 366 respondentes que não declararam NENHUMA das quatro variáveis não
   podem receber peso e ficam de fora de qualquer estimativa ponderada. O peso
   dos demais os representa apenas sob a hipótese de que, dentro de cada
   célula de margem, quem abandonou se parece com quem ficou (MAR). Isso é uma
   hipótese, não um resultado.
2. Ponderar corrige as margens, não corrige viés de seleção em dimensões não
   observadas. Um bolsista mais engajado com divulgação científica pode ter
   sido mais propenso a responder a um questionário sobre divulgação
   científica, e nenhuma das quatro variáveis captura isso.
3. Com pesos, o n nominal deixa de valer para inferência: use o n efetivo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Margens populacionais
#
# ⚠️ PREENCHER com os totais da população de bolsistas PQ vigentes no período
# da coleta (jan–mar/2023) — a mesma tabela usada para desenhar a amostra
# estratificada. Podem ser contagens absolutas ou proporções; o módulo
# normaliza.
#
# As chaves de cada variável precisam bater exatamente com os valores que
# aparecem em `data_tratado.csv`. Rode `python ponderacao.py --conferir` para
# checar as categorias antes de calcular qualquer coisa.
# --------------------------------------------------------------------------- #
MARGENS_POPULACAO: dict[str, dict[str, float]] = {
    # "CE11": {  # Grande área do conhecimento
    #     "Ciências Exatas e da Terra": ...,
    #     "Ciências Biológicas": ...,
    #     "Engenharias": ...,
    #     "Ciências da Saúde": ...,
    #     "Ciências Agrárias": ...,
    #     "Ciências Sociais Aplicadas": ...,
    #     "Ciências Humanas": ...,
    #     "Linguística, Letras e Artes": ...,
    # },
    # "CE02": {"Feminino": ..., "Masculino": ...},
    # "CE13": {"Norte": ..., "Nordeste": ..., "Centro-Oeste": ...,
    #          "Sudeste": ..., "Sul": ...},
    # "CE08": {"1A": ..., "1B": ..., "1C": ..., "1D": ..., "2": ..., "Sênior": ...},
}

VARIAVEIS_ESTRATIFICACAO = ["CE11", "CE02", "CE13", "CE08"]

# Aparagem: pesos extremos inflam a variância mais do que corrigem viés.
PESO_MINIMO = 0.25
PESO_MAXIMO = 4.0


def conferir_categorias(df: pd.DataFrame, margens: dict | None = None) -> pd.DataFrame:
    """Compara as categorias da amostra com as declaradas nas margens.

    Um erro de digitação ("Sênior" vs "Senior", "Linguística, Letras e Artes"
    vs "Linguistica, Letras e Artes") faz o raking divergir silenciosamente ou
    zerar um estrato inteiro. Rode isto antes de confiar em qualquer peso.
    """
    margens = MARGENS_POPULACAO if margens is None else margens
    linhas = []
    for var in VARIAVEIS_ESTRATIFICACAO:
        na_amostra = set(df[var].dropna().unique())
        nas_margens = set(margens.get(var, {}))
        for cat in sorted(na_amostra | nas_margens):
            linhas.append(
                {
                    "variavel": var,
                    "categoria": cat,
                    "na_amostra": cat in na_amostra,
                    "nas_margens": cat in nas_margens,
                    "n_amostra": int((df[var] == cat).sum()),
                }
            )
    tabela = pd.DataFrame(linhas)
    tabela["problema"] = np.where(
        tabela["na_amostra"] & ~tabela["nas_margens"],
        "falta nas margens",
        np.where(~tabela["na_amostra"] & tabela["nas_margens"], "ausente na amostra", ""),
    )
    return tabela


# --------------------------------------------------------------------------- #
# Margens conjuntas
#
# As Tabelas 3, 4 e 5 da dissertação cruzam cada variável de estratificação com
# sexo. Isso permite ir além do raking por margens isoladas: em vez de exigir
# apenas "x% são mulheres" e "y% são das Engenharias", exige-se diretamente
# "z% são mulheres nas Engenharias". Corrige desequilíbrios que a ponderação
# marginal não enxerga — por exemplo, mulheres sub-representadas especificamente
# em uma grande área.
#
# Formato: chave = tupla de variáveis, valor = dict com tupla de categorias.
#     MARGENS_CONJUNTAS = {
#         ("CE11", "CE02"): {("Engenharias", "Feminino"): 412, ...},
#         ("CE08", "CE02"): {("1A", "Feminino"): 233, ...},
#         ("CE13", "CE02"): {("Sudeste", "Feminino"): 1890, ...},
#     }
#
# Os valores abaixo vêm das Tabelas 2 a 5 da dissertação (PEREIRA, 2023,
# p. 74-76), que descrevem as 15.835 bolsas PQ vigentes em agosto de 2022 —
# a mesma base fornecida pelo CNPq (COCHS/CGCHS/DEHS) para o envio dos convites.
#
# Duas decisões que precisam constar da nota metodológica:
#
# 1. A categoria "Outra" da Tabela 2 (350 bolsas, 2,2% da população) não existe
#    no questionário e foi excluída. As proporções de categoria e região seguem
#    calculadas sobre as 15.835, o que equivale a supor que esses 350 bolsistas
#    se distribuem por nível e região como os demais.
# 2. As três tabelas implicavam percentuais de mulheres levemente diferentes
#    (35,235%, 35,179% e 35,198%), por arredondamento a uma casa decimal. Foram
#    reconciliadas para a média das três (35,204%) por IPF de duas vias,
#    preservando os totais de linha. O maior ajuste em qualquer célula foi de
#    0,91 bolsa em 15.485 — ou seja, ruído de arredondamento, não uma escolha
#    substantiva. Sem essa etapa o raking não converge, porque nenhum conjunto
#    de pesos satisfaz três alvos que se contradizem.
# --------------------------------------------------------------------------- #
MARGENS_CONJUNTAS: dict[tuple[str, ...], dict[tuple[str, ...], float]] = {
    ("CE11", "CE02"): {  # Tabela 2 + Tabela 3 (grande área × sexo), excluindo 'Outra'
        ("Ciências Exatas e da Terra", "Feminino"): 637.4926,
        ("Ciências Exatas e da Terra", "Masculino"): 2669.5074,
        ("Ciências Biológicas", "Feminino"): 1092.8446,
        ("Ciências Biológicas", "Masculino"): 1433.1554,
        ("Engenharias", "Feminino"): 425.4528,
        ("Engenharias", "Masculino"): 1662.5472,
        ("Ciências Agrárias", "Feminino"): 563.3221,
        ("Ciências Agrárias", "Masculino"): 1450.6779,
        ("Ciências Humanas", "Feminino"): 996.1884,
        ("Ciências Humanas", "Masculino"): 1017.8116,
        ("Ciências da Saúde", "Feminino"): 859.2475,
        ("Ciências da Saúde", "Masculino"): 836.7525,
        ("Ciências Sociais Aplicadas", "Feminino"): 497.2347,
        ("Ciências Sociais Aplicadas", "Masculino"): 707.7653,
        ("Linguística, Letras e Artes", "Feminino"): 379.5051,
        ("Linguística, Letras e Artes", "Masculino"): 255.4949,
    },
    ("CE08", "CE02"): {  # Tabela 4 do texto, rotulada '3' (categoria da bolsa × sexo)
        ("2", "Feminino"): 3389.7579,
        ("2", "Masculino"): 5716.2421,
        ("1D", "Feminino"): 846.8253,
        ("1D", "Masculino"): 1679.1747,
        ("1C", "Feminino"): 521.5204,
        ("1C", "Masculino"): 967.4796,
        ("1B", "Feminino"): 419.886,
        ("1B", "Masculino"): 840.114,
        ("1A", "Feminino"): 331.5597,
        ("1A", "Masculino"): 886.4403,
        ("Sênior", "Feminino"): 64.9514,
        ("Sênior", "Masculino"): 171.0486,
    },
    ("CE13", "CE02"): {  # Tabela 5 do texto, rotulada '4' (região × sexo)
        ("Sudeste", "Feminino"): 3292.2287,
        ("Sudeste", "Masculino"): 5800.7713,
        ("Sul", "Feminino"): 1167.7134,
        ("Sul", "Masculino"): 1996.2866,
        ("Nordeste", "Feminino"): 686.1927,
        ("Nordeste", "Masculino"): 1519.8073,
        ("Centro-Oeste", "Feminino"): 309.614,
        ("Centro-Oeste", "Masculino"): 679.386,
        ("Norte", "Feminino"): 118.752,
        ("Norte", "Masculino"): 264.248,
    },
}


def _preparar_alvos(d: pd.DataFrame, margens, conjuntas):
    """Normaliza margens simples e conjuntas em uma lista uniforme de alvos."""
    alvos = []
    for var, valores in (margens or {}).items():
        if var not in d.columns:
            continue
        s = pd.Series(valores, dtype=float)
        desconhecidas = set(d[var].unique()) - set(s.index)
        if desconhecidas:
            raise ValueError(
                f"{var}: categorias na amostra sem alvo nas margens: "
                f"{sorted(desconhecidas)}. Rode conferir_categorias()."
            )
        alvos.append(([var], s / s.sum()))

    for chave, valores in (conjuntas or {}).items():
        vs = list(chave)
        if any(v not in d.columns for v in vs):
            continue
        s = pd.Series(
            {tuple(k) if isinstance(k, tuple) else (k,): v for k, v in valores.items()},
            dtype=float,
        )
        s.index = pd.MultiIndex.from_tuples(s.index, names=vs)
        observadas = set(map(tuple, d[vs].drop_duplicates().to_numpy()))
        desconhecidas = observadas - set(s.index)
        if desconhecidas:
            raise ValueError(
                f"{'×'.join(vs)}: células na amostra sem alvo: {sorted(desconhecidas)}"
            )
        alvos.append((vs, s / s.sum()))

    if not alvos:
        raise ValueError(
            "Nenhuma margem informada. Preencha MARGENS_POPULACAO e/ou "
            "MARGENS_CONJUNTAS em ponderacao.py."
        )
    return alvos


def verificar_consistencia(alvos, tol: float = 1e-4):
    """Checa se alvos que compartilham variáveis implicam a mesma distribuição.

    O IPF só converge para margens mutuamente compatíveis. Se a Tabela 3
    (área × sexo) e a Tabela 4 (categoria × sexo) implicarem percentuais de
    mulheres diferentes, não existe conjunto de pesos que satisfaça as duas — e
    o algoritmo oscila indefinidamente sem avisar. Detectar isso antes é bem
    melhor do que publicar pesos que não fazem o que dizem fazer.

    Devolve uma lista de `(alvo_a, alvo_b, variavel, erro_maximo)`.
    """
    problemas = []
    for i, (vs_a, alvo_a) in enumerate(alvos):
        for vs_b, alvo_b in alvos[i + 1:]:
            for var in set(vs_a) & set(vs_b):
                ma = alvo_a.groupby(level=var).sum() if len(vs_a) > 1 else alvo_a
                mb = alvo_b.groupby(level=var).sum() if len(vs_b) > 1 else alvo_b
                comum = ma.index.intersection(mb.index)
                if len(comum) == 0:
                    continue
                erro = float((ma[comum] - mb[comum]).abs().max())
                if erro > tol:
                    problemas.append(
                        ("×".join(vs_a), "×".join(vs_b), var, erro)
                    )
    return problemas


def calcular_pesos(
    df: pd.DataFrame,
    margens: dict[str, dict[str, float]] | None = None,
    variaveis: list[str] | None = None,
    max_iter: int = 100,
    tol: float = 1e-7,
    aparar: bool = True,
    conjuntas: dict | None = None,
) -> pd.Series:
    """Pesos de pós-estratificação por raking (IPF).

    Devolve uma Series alinhada ao índice de `df`, com `NaN` para quem não
    declarou alguma das variáveis de estratificação — esses casos não entram em
    estimativas ponderadas. Os pesos são normalizados para somar ao número de
    casos ponderáveis, de modo que o "n" continue legível como pessoas.
    """
    margens = MARGENS_POPULACAO if margens is None else margens
    conjuntas = MARGENS_CONJUNTAS if conjuntas is None else conjuntas
    variaveis = VARIAVEIS_ESTRATIFICACAO if variaveis is None else variaveis

    completos = df[variaveis].notna().all(axis=1)
    d = df.loc[completos, variaveis]
    if d.empty:
        raise ValueError("Nenhum caso com as quatro variáveis de estratificação.")

    alvos = _preparar_alvos(d, margens, conjuntas)

    inconsistencias = verificar_consistencia(alvos)
    if inconsistencias:
        detalhe = "; ".join(
            f"{a} vs {b} discordam em {v!r} (dif. máx. {e:.4f})"
            for a, b, v, e in inconsistencias
        )
        raise ValueError(
            "Margens mutuamente inconsistentes — o IPF não converge para alvos "
            "que se contradizem, ele fica oscilando entre eles e devolve pesos "
            f"que não satisfazem nenhum: {detalhe}. "
            "Isso costuma vir de tabelas publicadas com arredondamentos ou "
            "recortes diferentes (ex.: uma tabela exclui bolsas Sênior e outra "
            "não). Reconcilie os totais antes de ponderar."
        )

    pesos = pd.Series(1.0, index=d.index)
    convergiu = False
    for _ in range(max_iter):
        maior_ajuste = 0.0
        for vs, alvo in alvos:
            # Agrupar por uma LISTA de Series preserva os nomes dos níveis.
            # Passar um MultiIndex pronto faz o pandas tratá-lo como um grupo
            # plano de tuplas, o índice resultante sai com nome None, e o
            # alinhamento com o alvo falha ou — pior — casa errado.
            atual = pesos.groupby([d[v] for v in vs], observed=True).sum()
            atual = atual / atual.sum()

            fator = (alvo / atual).replace([np.inf, -np.inf], np.nan).fillna(1.0)

            if len(vs) == 1:
                ajuste = d[vs[0]].map(fator)
            else:
                chave = pd.MultiIndex.from_frame(d[vs])
                ajuste = pd.Series(fator.reindex(chave).to_numpy(), index=d.index)

            pesos = pesos * ajuste.astype(float).fillna(1.0)
            maior_ajuste = max(maior_ajuste, float((fator - 1).abs().max()))
        if maior_ajuste < tol:
            convergiu = True
            break

    if not convergiu:
        import warnings

        warnings.warn(
            f"O raking não convergiu em {max_iter} iterações (ajuste residual "
            f"{maior_ajuste:.2e}). Os pesos reproduzem as margens apenas de "
            "forma aproximada — verifique-os antes de publicar qualquer número.",
            RuntimeWarning,
            stacklevel=2,
        )

    if aparar:
        pesos = pesos / pesos.mean()
        pesos = pesos.clip(PESO_MINIMO, PESO_MAXIMO)

    pesos = pesos / pesos.sum() * len(pesos)
    return pesos.reindex(df.index)


def diagnostico(pesos: pd.Series) -> dict:
    """Qualidade dos pesos: quanto de precisão a ponderação custou.

    `deff` é o efeito de desenho de Kish; `n_efetivo` é o tamanho de amostra
    que uma amostra aleatória simples precisaria ter para a mesma precisão. É
    ele, e não o n nominal, que deve aparecer em qualquer teste.
    """
    w = pesos.dropna()
    if w.empty:
        return {}
    deff = 1.0 + (w.std(ddof=0) / w.mean()) ** 2
    return {
        "n_ponderavel": int(len(w)),
        "n_efetivo": float(w.sum() ** 2 / (w**2).sum()),
        "deff": float(deff),
        "peso_min": float(w.min()),
        "peso_max": float(w.max()),
        "cv": float(w.std(ddof=0) / w.mean()),
    }


def tabela_ponderada(
    df: pd.DataFrame, var1: str, var2: str, pesos: pd.Series
) -> pd.DataFrame:
    """Tabela de contingência ponderada, reescalada ao n efetivo.

    O qui-quadrado aplicado a contagens ponderadas brutas é anticonservador:
    ele trata a soma dos pesos como se fossem observações independentes. Aqui a
    tabela é reescalada para somar o n efetivo, que é a correção de primeira
    ordem usual (na linha do ajuste de Rao–Scott) e mantém o teste honesto.
    """
    validos = pesos.notna() & df[var1].notna() & df[var2].notna()
    d = df.loc[validos]
    w = pesos.loc[validos]

    tabela = pd.crosstab(d[var1], d[var2], values=w, aggfunc="sum").fillna(0.0)
    n_ef = float(w.sum() ** 2 / (w**2).sum())
    total = tabela.to_numpy().sum()
    if total > 0:
        tabela = tabela * (n_ef / total)
    return tabela


def _cli() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Diagnóstico da ponderação.")
    parser.add_argument("--conferir", action="store_true",
                        help="lista as categorias da amostra vs. as margens")
    args = parser.parse_args()

    import data_process as dp

    df = dp.carregar_dados()

    if args.conferir or not MARGENS_POPULACAO:
        print("Categorias observadas na amostra (use-as como chaves em MARGENS_POPULACAO):\n")
        for var in VARIAVEIS_ESTRATIFICACAO:
            print(f"  {var}:")
            for cat, n in df[var].value_counts().items():
                print(f'      "{cat}": ...,   # amostra: {n}')
            print(f"      # sem resposta: {int(df[var].isna().sum())}\n")
        if not MARGENS_POPULACAO:
            print("MARGENS_POPULACAO ainda está vazio — preencha antes de calcular pesos.")
        return

    pesos = calcular_pesos(df)
    d = diagnostico(pesos)
    print("Diagnóstico dos pesos")
    print(f"  casos ponderáveis : {d['n_ponderavel']}")
    print(f"  n efetivo         : {d['n_efetivo']:.0f}")
    print(f"  efeito de desenho : {d['deff']:.3f}")
    print(f"  pesos             : {d['peso_min']:.2f} a {d['peso_max']:.2f} (CV {d['cv']:.3f})")


if __name__ == "__main__":
    _cli()
