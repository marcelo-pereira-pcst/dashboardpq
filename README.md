# Cientistas e divulgação científica — survey com bolsistas PQ do CNPq

Dashboard estático dos resultados de um *survey* com **1.934 bolsistas de
Produtividade em Pesquisa (PQ) do CNPq**, coletado entre janeiro e março de
2023, sobre percepções e práticas de divulgação científica.

**Site:** <https://marcelo-pereira-pcst.github.io/dashboardpq/>

---

## O que este repositório é

O site é **pré-renderizado**: todos os números são calculados uma vez, no
build, e servidos como arquivos estáticos. Não há processo Python vivo, não há
banco, e o site não hiberna.

Isso é possível porque o espaço de estados é finito e enumerável — o dado está
congelado desde 2023 e não há entrada de usuário. São 87 variáveis temáticas ×
11 sociodemográficas, mais os 55 pares entre as próprias sociodemográficas:
**1.012 cruzamentos**, cada um com tabela de contingência, esperados, resíduos
de Pearson, qui-quadrado, *p* ajustado, V de Cramér e *n*.

> **Este repositório não contém microdados.** O site consome apenas agregados.
> Se em algum momento parecer necessário publicar o microdado para o site
> funcionar, a arquitetura está errada.

## Estrutura

```
build.py              gera os agregados a partir do microdado (local)
blocos.py             estrutura editorial: perguntas, abas, rótulos, agregações
data_process.py       carga e preparação dos dados
graphs.py             estatística de associação e semântica do mosaico
ponderacao.py         pesos de pós-estratificação (raking/IPF)
categories.json       ordem canônica das categorias
varmap.json           código → enunciado
dados/                agregados comitados (tabela de associações, pesos)
site/                 projeto Quarto — ver site/README.md
docs/                 site renderizado, servido pelo GitHub Pages
```

## Reproduzir

```bash
pip install -r requirements.txt
python build.py --conferir      # gera site/dados/*.json e confere os números
cd site
quarto render                   # gera ../docs
node verificar_navegador.mjs    # opcional: testa o site em Chromium
```

O verificador precisa de Node.js e Playwright e **não é necessário para
publicar** — ver `site/README.md`.

`build.py` precisa de `data_tratado.csv`, que **não está aqui**. Sem ele, o
site continua funcionando: os agregados em `site/dados/` já estão comitados.

`--conferir` compara o resultado com números conhecidos (165 testes no bloco de
atividades, CE14 com 223 em "acima de 35 anos" e não 619) e falha se algum
divergir. Rode antes de comitar.

## Método, em uma tela

- **Amostra**: convite estratificado por grande área, sexo, região e categoria
  da bolsa; 1.934 respostas, ~12% da população.
- **Ponderação**: pós-estratificação por ajuste proporcional iterativo. *n*
  efetivo 1.440, efeito de desenho 1,037. Os gráficos mostram percentuais
  brutos; o ponderado vai nos agregados.
- **Testes**: qui-quadrado; V de Cramér com correção de Bergsma (2013);
  Benjamini–Hochberg **por bloco temático**.
- **Controle de divulgação**: categorias raras de quatro variáveis sensíveis
  são agregadas antes de qualquer cruzamento.
- **Escala de cor dos mosaicos**: fixa de −4 a +4, com banda neutra para
  |resíduo| < 2, igual em todas as páginas.

Detalhamento e limites de interpretação:
<https://marcelo-pereira-pcst.github.io/dashboardpq/metodologia.html>

**Advertência que atravessa tudo:** com *n* ≈ 1.500 por cruzamento, quase tudo
dá significativo. A mediana do V de Cramér é 0,04 e apenas 11 dos 1.012
cruzamentos passam de 0,20. Significativo aqui quase nunca quer dizer
importante — o site publica o tamanho de efeito ao lado de cada teste, e uma
[tabela com todos eles](https://marcelo-pereira-pcst.github.io/dashboardpq/metodologia.html#tamanhos-de-efeito).

## Dados e citação

PEREIRA, M. *Cientistas brasileiros e divulgação científica: agregados do
survey com bolsistas PQ do CNPq (2023)*. Zenodo, 2026.
<https://doi.org/10.5281/zenodo.21807142>

PEREIRA, M.; CASTELFRANCHI, Y.; MASSARANI, L. Cientistas brasileiros e
divulgação científica: uma proposta de classificação. *Revista Iberoamericana
de Ciencia, Tecnología y Sociedad — CTS*, v. 20, n. 59, p. 249-273, 2025.
<https://doi.org/10.52712/issn.1850-0013-779>

PEREIRA, M. *Ciência, sociedade, divulgação científica: a visão dos
cientistas*. Dissertação (Mestrado em Sociologia) — Universidade Federal de
Minas Gerais, Belo Horizonte, 2023. <http://hdl.handle.net/1843/55328>

## Licença

Código sob MIT; agregados sob CC BY 4.0. Ver [LICENSE](LICENSE).

## Contato

Marcelo Pereira — [mapereira@ufmg.br](mailto:mapereira@ufmg.br) ·
<https://marcelo-pereira-pcst.github.io/>
