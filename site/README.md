# site/ — o dashboard em Quarto

Substitui o app Streamlit por um site estático pré-renderizado: sem
hibernação, sem processo Python vivo, sem microdado publicado.

```
site/
  _quarto.yml              projeto, navbar, tema
  index.qmd                Início — sobre a pesquisa, questionário, contato
  achados.qmd              Leitura interpretativa dos resultados
  atividades.qmd           Atividades de divulgação científica
  opinioes-ct.qmd          Opiniões sobre ciência e tecnologia
  opinioes-dc.qmd          Opiniões sobre divulgação científica
  motivacoes.qmd           Motivações e obstáculos
  perfil.qmd               Perfil sociodemográfico
  metodologia.qmd          Nota metodológica
  _explicacao-mosaico.qmd  trecho incluído em várias páginas
  assets/
    dashboard.js           todos os componentes de gráfico
    dashboard.css          estilo dos componentes
    tema.scss              tema do Quarto
  dados/                   agregados (gerados por ../build.py)
  vendor/plotly.min.js     Plotly 2.35.2, cópia local
  img/, questionario.pdf   recursos
  verificar_navegador.mjs  testes em navegador real
```

A saída vai para `../docs`, que é o que o GitHub Pages serve.

## Fluxo

Da **raiz do repositório**:

```bash
python build.py --conferir     # gera site/dados/*.json e confere os números
```

De dentro de **`site/`**:

```bash
quarto render                  # gera ../docs
quarto preview                 # desenvolvimento, recarrega sozinho
node verificar_navegador.mjs   # testa o site renderizado (opcional, ver abaixo)
```

⚠️ Repare no caminho do verificador: `node verificar_navegador.mjs` de dentro
de `site/`, ou `node site/verificar_navegador.mjs` da raiz. Ele resolve
`../docs` a partir da própria localização, então funciona dos dois lugares —
o que muda é só como você o chama.

`python build.py --conferir` compara o resultado com os números conhecidos
(165 testes no bloco de atividades, 41 significativos, CE14 com 223 e não 619)
e falha se algum divergir. Rode antes de comitar.

## Como uma página é montada

As `.qmd` são markdown com marcadores vazios; `assets/dashboard.js` preenche.

| Marcador | Vira |
|---|---|
| `<div data-pq="distribuicao" data-bloco="octs6">` | gráfico univariado do bloco + tabela |
| `<div data-pq="mosaico" data-bloco="octs6">` | dois seletores + mosaico + resumo + tabela + CSV |
| `<div data-pq="perfil">` | seletor de característica + distribuição |
| `<div data-pq="exemplo" data-chave="adc1[SQ007]\|CE11">` | mosaico fixo, para a explicação |
| `<div data-pq="efeitos">` | histograma + tabela filtrável dos 1.012 tamanhos de efeito |
| `<span data-pq-num="meta.n_total">` | número lido do build |

`data-pq-num` existe para que **nenhum número apareça escrito à mão no texto**.
Se a estatística mudar, o texto muda junto; um número digitado no markdown
viraria mentira silenciosa na primeira vez que o build fosse refeito.

Cada página declara sua seção com
`<script>document.body.dataset.pqSecao = "atividades"</script>`, que decide
qual `dados/cruz-*.json` é baixado.

## Estrutura dos dados

`../blocos.py` guarda a estrutura editorial — quais perguntas existem, em que
aba aparecem, com que enunciado e rótulo. `../build.py` faz o cálculo e a
serialização. A separação é proposital: revisar redação não deveria parecer
alteração de método no `git diff`.

```jsonc
// dados/base.json
{ "meta": {...}, "secoes": [...], "blocos": [...], "resumo_blocos": {...},
  "ordem_socio": [...], "variaveis": {...}, "marginais": {...} }

// dados/efeitos.json — todos os cruzamentos numa tabela colunar, para a
// seção "Tamanhos de efeito" da nota metodológica. Formato colunar porque
// repetir oito nomes de campo em 1.012 linhas quase triplicaria o arquivo.
{ "colunas": [...], "linhas": [[linha, coluna, secao, v, p_aj, sig, n], ...],
  "bloco_de": {...}, "resumo": {...} }

// dados/cruz-<secao>.json
{ "cruzamentos": { "adc1[SQ001]|CE11": {
    "cat_linha": [...],        // categorias da variável temática
    "cat_coluna": [...],       // categorias da sociodemográfica
    "observado": [[...]],      // observado[i][j]: i sobre cat_linha
    "esperado": [[...]], "residuos": [[...]],
    "chi2","gl","p","p_ajustado","significativo",
    "v_cramer","classificacao","n","n_excluidos",
    "esperado_minimo","prop_celulas_esperado_baixo" } } }
```

**Orientação do mosaico** — a única coisa fácil de errar aqui: as *colunas*
vão para o eixo x (a largura de cada faixa é a marginal da variável
sociodemográfica) e as *linhas* se empilham dentro de cada faixa. É a mesma
orientação do app Streamlit.

Os 55 pares sociodemográficos são gravados **uma vez cada**; o site transpõe
quando o leitor pede a ordem inversa.

## Decisões que não são cosméticas

**Escala de cor.** Definida uma vez em `graphs.py`
(`ESCALA_RESIDUO_FIXA = 4`, `LIMIAR_NEUTRO = 2`), exportada em `meta` e lida de
lá pelo JavaScript. A página não tem constantes próprias, de propósito.

**Azul↔vermelho é reservado aos resíduos.** Por isso as escalas ordinais
(concordância, importância, preocupação) usam barras empilhadas de **um só
tom**, e não a barra divergente que seria o padrão para Likert: com as duas
convenções na mesma página, o vermelho significaria "discorda" em cima e
"acima do esperado" embaixo. A leitura de relance é recuperada pelo rótulo
direto no fim de cada barra e pela ordenação das linhas. A rampa foi validada
(monotônica em luminosidade, degraus ≥ 0,06, ponta clara acima de 2:1 sobre a
superfície); não troque um passo sem revalidar.

**A tabela de tamanhos de efeito não é enfeite.** Um site com 1.012 mosaicos
clicáveis convida o leitor a navegar até algo ficar vermelho, e a correção de
FDR não protege contra isso — ela controla a taxa de falsas descobertas sobre
os testes calculados, não sobre a busca visual de quem navega. O histograma da
distribuição inteira é o antídoto, e a página de achados faz o trabalho
interpretativo que a navegação livre não faz. Se um dia alguém propuser tirar
qualquer um dos dois para "simplificar", é isto que se perde.

**FDR por bloco temático.** Cada bloco de perguntas é uma família de testes,
corrigida pelo número de testes que ela realiza contra as 11 variáveis
sociodemográficas. Preserva os números conhecidos da página de atividades. O
FDR global também é calculado e aparece na nota metodológica.

**Gráficos em abas fechadas.** Uma aba fechada mede zero de largura, e o
Plotly desenha contra a largura do container — um gráfico criado ali nasce com
o layout calculado para zero pixel. `dashboard.js` redimensiona no evento
`shown.bs.tab` e num `IntersectionObserver`. Se você mover gráficos para
dentro de outro componente colapsável, confira que ele dispara um desses.

## Dependências

Plotly é servido de `vendor/plotly.min.js` — cópia versionada, 4,5 MB. A tag
`<script>` cai no CDN se o arquivo local faltar, mas o caminho normal é o
local: um artefato acadêmico precisa continuar abrindo daqui a dez anos, e um
CDN é um terceiro que pode parar de servir a URL. Com a cópia no repositório,
o site é reproduzível a partir de um clone e funciona offline ou atrás de
proxy. Para atualizar:

```bash
curl -L -o site/vendor/plotly.min.js https://cdn.plot.ly/plotly-2.35.2.min.js
```

O tema não carrega fontes do Google — um site acadêmico não deveria fazer o
navegador de cada leitor pedir arquivo a um terceiro só para escolher a fonte.

### O verificador é opcional

`verificar_navegador.mjs` abre as 8 páginas em Chromium, percorre os 1.067
cruzamentos, mede a geometria de cada retângulo do SVG contra o JSON e falha
se aparecer qualquer coisa no console. É a rede de segurança **para quando
você mexer em alguma coisa** — publicar não depende dele.

Precisa de Node.js e Playwright:

```powershell
winget install OpenJS.NodeJS.LTS     # Windows; reabra o terminal depois
npm install playwright
npx playwright install chromium
```

Sem Node instalado, a verificação equivalente e suficiente é abrir o site,
clicar em duas ou três páginas e conferir que o console do navegador (F12)
está limpo.

## O que vai para o repositório público

`site/`, `docs/`, `build.py`, `blocos.py`, os módulos de cálculo e os
metadados. **Nunca `data_tratado.csv`.** `build.py` lê o microdado; o site
não. Se em algum momento o site precisar dele, a arquitetura está errada.

`python build.py --auditar` relata as células de contagem 1 ou 2 publicadas —
uma tabela bivariada não reidentifica ninguém do jeito que o microdado
reidentificava, mas vale olhar antes de publicar.

## Pendências

- `ponderacao.MARGENS_POPULACAO` está vazio: os pesos vêm de
  `dados/pesos_pos_estratificacao.csv` e **não são reproduzíveis a partir do
  código** até as margens do CNPq serem transcritas para o módulo.
- Os percentuais exibidos são brutos; `pct_ponderado` vai no JSON.
- `img/exemplo_mosaico.png` (cores antigas) não é mais usado — a explicação
  agora desenha um mosaico real a partir do `dados/`. O PNG pode ser removido.
- `quarto render` emite um aviso sobre `output-dir: ../docs` apontar para fora
  do projeto. É esperado e inofensivo; some se um dia o projeto Quarto for
  movido para a raiz do repositório.
