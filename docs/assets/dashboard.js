/* ==========================================================================
 * dashboard.js — componentes de gráfico do site
 *
 * As páginas `.qmd` são markdown com marcadores vazios; tudo o que desenha
 * está aqui. Um `<div data-pq="mosaico" data-bloco="adc1">` vira o par de
 * seletores + mosaico + resumo + tabela; um `data-pq="distribuicao"` vira o
 * gráfico univariado do bloco. O texto fica no Quarto, o desenho fica no JS,
 * e nenhuma página precisa repetir código.
 *
 * DECISÕES DE COR — as duas que importam
 * --------------------------------------
 * 1. A escala DIVERGENTE (azul↔vermelho, coolwarm de −4 a +4) é reservada em
 *    todo o site para os resíduos de Pearson dos mosaicos. Os parâmetros vêm
 *    de `meta`, calculados por `graphs.py`, e não de constantes locais: se a
 *    escala mudar no build, o gráfico acompanha.
 *
 * 2. Por causa disso, as escalas ordinais (concordância, importância,
 *    preocupação) usam uma rampa de UM tom, e não a barra empilhada
 *    divergente que seria o padrão para Likert. Com as duas convenções na
 *    mesma página, o vermelho significaria "discorda" no gráfico de cima e
 *    "acima do esperado" no de baixo — e o leitor não tem como saber qual é
 *    qual. A leitura "quanto concorda" é recuperada pelo rótulo direto no fim
 *    de cada barra e pela ordenação das linhas.
 *
 * A rampa foi validada (monotônica em L, gaps ≥ 0,06, ponta clara ≥ 2:1 sobre
 * a superfície, tom único). Não troque um passo sem revalidar.
 * ========================================================================== */

"use strict";

const PQ = (function () {

  /* ------------------------------------------------------------- tokens */

  const COR = {
    superficie: "#fcfcfb",
    tinta: "#0b0b0b",
    tinta2: "#52514e",
    tinta3: "#898781",
    grade: "#e1e0d9",
    eixo: "#c3c2b7",
    serie: "#2a78d6",     // slot categórico 1 — série única
    neutro: "#898781",    // "Não sei" / "Não se aplica": fora da escala
  };

  // Rampa ordinal azul, do mais claro ao mais escuro. Os subconjuntos de 3, 4
  // e 5 passos abaixo são os validados; não interpole passos novos.
  const RAMPA = {
    3: ["#86b6ef", "#3987e5", "#184f95"],
    4: ["#86b6ef", "#3987e5", "#256abf", "#0d366b"],
    5: ["#86b6ef", "#5598e7", "#2a78d6", "#184f95", "#0d366b"],
  };

  function rampa(k) {
    if (RAMPA[k]) return RAMPA[k].slice();
    if (k <= 2) return RAMPA[3].slice(0, k);
    // Acima de 5 passos os degraus deixam de ser distinguíveis; a forma certa
    // não é gerar mais tons, e sim não empilhar tanta categoria de uma vez.
    return RAMPA[5].concat(Array(k - 5).fill(RAMPA[5][4]));
  }

  // Escala divergente dos resíduos: coolwarm do matplotlib, os mesmos passos
  // que `graphs.py` usa para os mosaicos estáticos da dissertação.
  const COOLWARM = [
    [0.0000, "#3b4cc0"], [0.0625, "#4e68d8"], [0.1250, "#6282ea"],
    [0.1875, "#779af7"], [0.2500, "#8db0fe"], [0.3125, "#a3c2fe"],
    [0.3750, "#b9d0f9"], [0.4375, "#ccd9ed"], [0.5000, "#dddcdc"],
    [0.5625, "#ecd3c5"], [0.6250, "#f5c4ac"], [0.6875, "#f7b093"],
    [0.7500, "#f4987a"], [0.8125, "#eb7d62"], [0.8750, "#dd5f4b"],
    [0.9375, "#ca3b37"], [1.0000, "#b40426"],
  ];
  const NEUTRO_MOSAICO = "#f0f0f0";

  function hexRgb(h) { return [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); }

  function corResiduo(t) {
    t = Math.min(1, Math.max(0, t));
    for (let i = 1; i < COOLWARM.length; i++) {
      if (t <= COOLWARM[i][0]) {
        const [t0, c0] = COOLWARM[i - 1], [t1, c1] = COOLWARM[i];
        const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
        const a = hexRgb(c0), b = hexRgb(c1);
        return "rgb(" + a.map((v, k) => Math.round(v + f * (b[k] - v))).join(",") + ")";
      }
    }
    return COOLWARM[COOLWARM.length - 1][1];
  }

  /* --------------------------------------------------------- formatação */

  const nf = c => new Intl.NumberFormat("pt-BR",
    { minimumFractionDigits: c, maximumFractionDigits: c });
  const n0 = nf(0), n1 = nf(1), n2 = nf(2);

  function formatarP(p) {
    if (p === null || p === undefined) return "—";
    return p < 0.001 ? "p < 0,001" : "p = " + n2.format(p);
  }

  function encurtar(t, lim) {
    t = String(t);
    return t.length <= lim ? t : t.slice(0, lim - 1).trimEnd() + "…";
  }

  function quebrar(texto, limite) {
    const palavras = String(texto).split(" ");
    const linhas = [];
    let atual = "";
    for (const p of palavras) {
      if (atual && (atual + " " + p).length > limite) { linhas.push(atual); atual = p; }
      else { atual = atual ? atual + " " + p : p; }
    }
    if (atual) linhas.push(atual);
    return linhas.join("<br>");
  }

  const escapar = s => String(s).replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const estreito = () => window.innerWidth < 640;

  /* ------------------------------------------------------------- estado */

  let BASE = null;
  const CRUZ = {};          // chave "linha|coluna" -> cruzamento
  let EFEITOS = null;       // tabela achatada de tamanhos de efeito
  let SECAO = null;

  const rotulo = cod => (BASE.variaveis[cod] || {}).rotulo || cod;
  const bloco = id => BASE.blocos.find(b => b.id === id);

  /**
   * Cruzamento pela chave, tentando as duas ordens.
   *
   * A página de perfil cruza variáveis sociodemográficas entre si, e o build
   * guarda cada par UMA vez (55 pares, não 110): o par simétrico é o mesmo
   * teste com os eixos trocados. Quando o leitor pede a ordem que não foi
   * gravada, transpomos aqui em vez de duplicar o arquivo.
   */
  function obterCruzamento(linha, coluna) {
    const direto = CRUZ[linha + "|" + coluna];
    if (direto) return direto;
    const inverso = CRUZ[coluna + "|" + linha];
    return inverso ? transpor(inverso) : null;
  }

  function transpor(c) {
    const t = (m) => m[0].map((_, j) => m.map(l => l[j]));
    return Object.assign({}, c, {
      linha: c.coluna, coluna: c.linha,
      cat_linha: c.cat_coluna, cat_coluna: c.cat_linha,
      observado: t(c.observado), esperado: t(c.esperado), residuos: t(c.residuos),
    });
  }

  /* ================================================================== */
  /* Mosaico                                                            */
  /* ================================================================== */

  const VAO_X = 0.006, VAO_Y = 0.004;

  /**
   * Geometria do mosaico.
   *
   * Faixas verticais = categorias da COLUNA (largura ∝ marginal). Dentro de
   * cada faixa, blocos empilhados = categorias da LINHA (altura ∝ proporção
   * condicional).
   *
   * Os vãos são descontados do espaço útil ANTES de distribuir as proporções.
   * Somá-los depois faria as áreas deixarem de ser proporcionais às
   * frequências — a única coisa que um mosaico promete.
   */
  function geometria(observado, nL, nC) {
    const totaisColuna = [];
    let total = 0;
    for (let j = 0; j < nC; j++) {
      let s = 0;
      for (let i = 0; i < nL; i++) s += observado[i][j];
      totaisColuna.push(s); total += s;
    }
    const larguraUtil = 1 - VAO_X * Math.max(0, nC - 1);
    const alturaUtil = 1 - VAO_Y * Math.max(0, nL - 1);
    const colunas = [];
    let x = 0;
    for (let j = 0; j < nC; j++) {
      const largura = total ? (totaisColuna[j] / total) * larguraUtil : 0;
      const blocos = [];
      let y = 1;
      for (let i = 0; i < nL; i++) {
        const altura = totaisColuna[j]
          ? (observado[i][j] / totaisColuna[j]) * alturaUtil : 0;
        blocos.push({ y0: y - altura, y1: y, altura });
        y -= altura + VAO_Y;
      }
      colunas.push({ x0: x, x1: x + largura, largura, blocos, total: totaisColuna[j] });
      x += largura + VAO_X;
    }
    return { colunas, total, totaisColuna };
  }

  function desenharMosaico(el, cruz, opts) {
    opts = opts || {};
    const escala = BASE.meta.escala_residuo, limiar = BASE.meta.limiar_neutro;
    const catL = cruz.cat_linha, catC = cruz.cat_coluna;
    const nL = catL.length, nC = catC.length;
    const geo = geometria(cruz.observado, nL, nC);
    const peq = estreito();
    const tracos = [];

    for (let j = 0; j < nC; j++) {
      const col = geo.colunas[j];
      for (let i = 0; i < nL; i++) {
        const b = col.blocos[i];
        if (b.altura <= 0 || col.largura <= 0) continue;
        const obs = cruz.observado[i][j], esp = cruz.esperado[i][j], res = cruz.residuos[i][j];
        const cor = (res === null || Math.abs(res) < limiar)
          ? NEUTRO_MOSAICO : corResiduo((res + escala) / (2 * escala));
        let somaLinha = 0;
        for (let k = 0; k < nC; k++) somaLinha += cruz.observado[i][k];
        tracos.push({
          type: "scatter", mode: "lines",
          x: [col.x0, col.x1, col.x1, col.x0, col.x0],
          y: [b.y0, b.y0, b.y1, b.y1, b.y0],
          fill: "toself", fillcolor: cor,
          line: { color: COR.superficie, width: 1 },
          hoveron: "fills", hoverinfo: "text",
          text: "<b>" + escapar(catC[j]) + "</b> × <b>" + escapar(catL[i]) + "</b><br>" +
                "observado: " + n0.format(obs) + "<br>" +
                "esperado: " + n1.format(esp) + "<br>" +
                "resíduo: " + (res === null ? "—" : n2.format(res)) + "<br>" +
                n1.format(col.total ? obs / col.total * 100 : 0) + "% desta coluna<br>" +
                n1.format(somaLinha ? obs / somaLinha * 100 : 0) + "% desta linha",
          showlegend: false,
          hoverlabel: { bgcolor: "#fff", bordercolor: COR.eixo,
                        font: { color: COR.tinta, size: 12 } },
        });
      }
    }

    tracos.push({
      type: "scatter", mode: "markers", x: [null], y: [null],
      hoverinfo: "skip", showlegend: false,
      marker: {
        color: [0], colorscale: COOLWARM, cmin: -escala, cmax: escala,
        showscale: true,
        colorbar: {
          title: { text: "Resíduo de<br>Pearson", side: "right", font: { size: 11 } },
          thickness: 12, len: 0.9, x: 1.005, xpad: 0, outlinewidth: 0,
          tickvals: [-escala, -limiar, 0, limiar, escala], tickfont: { size: 10 },
        },
      },
    });

    // Rótulos das linhas: alinhados à PRIMEIRA faixa. Um mosaico não tem eixo
    // y global — a divisão vertical muda de faixa para faixa —, então
    // qualquer eixo é o de uma coluna de referência.
    const primeira = geo.colunas[0];
    const ticksY = [], rotulosY = [];
    for (let i = 0; i < nL; i++) {
      const b = primeira.blocos[i];
      if (b.altura > 0.018) { ticksY.push((b.y0 + b.y1) / 2); rotulosY.push(catL[i]); }
    }

    // O espaço para rótulo é medido em PIXELS, não em fração da largura: uma
    // faixa de 1,2% tem 12 px num monitor e 2,7 px num celular.
    // Margem esquerda proporcional ao maior rótulo que vai aparecer. Um valor
    // fixo deixa um vão enorme quando os rótulos são curtos ("Sim"/"Não") e
    // corta quando são longos.
    const maiorRotulo = rotulosY.reduce((m, t) => Math.max(m, String(t).length), 0);
    const margemL = Math.min(peq ? 110 : 190,
                             Math.max(peq ? 56 : 70, maiorRotulo * (peq ? 5.2 : 6.4)));
    const margemR = 72;
    const larguraPlot = Math.max(120, (el.clientWidth || 900) - margemL - margemR);
    const minimoPx = peq ? 13 : 20;

    const ticksX = [], rotulosX = [], omitidos = [];
    let menorLargura = 1;
    for (let j = 0; j < nC; j++) {
      const c = geo.colunas[j];
      if (c.largura <= 0) continue;
      if (c.largura * larguraPlot >= minimoPx) {
        ticksX.push((c.x0 + c.x1) / 2);
        rotulosX.push(peq ? encurtar(catC[j], 20) : quebrar(catC[j], 20));
        menorLargura = Math.min(menorLargura, c.largura);
      } else omitidos.push(catC[j]);
    }
    const apertado = peq || menorLargura < 0.09;

    Plotly.react(el, tracos, {
      margin: { l: margemL, r: margemR, t: 8,
                b: peq ? 132 : (apertado ? 118 : 76) },
      height: (peq ? 500 : 540) + (apertado && !peq ? 40 : 0),
      xaxis: {
        range: [-0.005, 1.005], tickvals: ticksX, ticktext: rotulosX,
        tickangle: peq ? -90 : (apertado ? -35 : 0),
        tickfont: { size: peq ? 9 : 11, color: COR.tinta2 },
        showgrid: false, zeroline: false, showline: false, fixedrange: true,
      },
      yaxis: {
        range: [-0.005, 1.005], tickvals: ticksY, ticktext: rotulosY,
        tickfont: { size: peq ? 9 : 11, color: COR.tinta2 },
        showgrid: false, zeroline: false, showline: false, fixedrange: true,
      },
      plot_bgcolor: "rgba(0,0,0,0)", paper_bgcolor: "rgba(0,0,0,0)",
      hovermode: "closest", dragmode: false,
    }, {
      responsive: true, displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "zoom2d",
                               "pan2d", "zoomIn2d", "zoomOut2d"],
      toImageButtonOptions: {
        filename: (cruz.linha + "_x_" + cruz.coluna).replace(/[^\w]+/g, "_"),
        scale: 2,
      },
    });

    el.setAttribute("aria-label",
      "Mosaico de " + rotulo(cruz.linha) + " por " + rotulo(cruz.coluna));
    return omitidos;
  }

  function textoResumo(cruz) {
    const v = cruz.v_cramer;
    let html = [
      "<b>Associação " + cruz.classificacao + "</b>",
      "V de Cramér = " + n2.format(v),
      formatarP(cruz.p_ajustado) + " (ajustado, FDR)",
      "n = " + n0.format(cruz.n),
    ].join('<span class="pq-sep">·</span>');

    if (cruz.n_excluidos) {
      html += ' <span class="pq-fraco">(' + n0.format(cruz.n_excluidos) +
              " sem resposta em uma das perguntas)</span>";
    }
    if (cruz.significativo === false) {
      html += '<span class="pq-alerta">Após a correção para os testes do bloco, ' +
              "esta associação não é distinguível do acaso.</span>";
    } else if (v < 0.10) {
      html += '<span class="pq-alerta">Estatisticamente distinguível de zero, mas ' +
              "o tamanho do efeito é desprezível: o padrão existe e é pequeno.</span>";
    }
    if (cruz.prop_celulas_esperado_baixo > 0.2) {
      html += '<span class="pq-alerta">Mais de 20% das células têm frequência ' +
              "esperada abaixo de 5 — o teste qui-quadrado perde confiabilidade aqui." +
              "</span>";
    }
    return html;
  }

  function tabelaContingencia(cruz) {
    const cl = cruz.cat_linha, cc = cruz.cat_coluna;
    let h = "<thead><tr><th></th>";
    for (const c of cc) h += "<th>" + escapar(c) + "</th>";
    h += "<th>Total</th></tr></thead><tbody>";
    const totais = cc.map((_, j) => cruz.observado.reduce((s, l) => s + l[j], 0));
    cl.forEach((r, i) => {
      h += "<tr><th scope='row'>" + escapar(r) + "</th>";
      let soma = 0;
      cc.forEach((_, j) => { h += "<td>" + n0.format(cruz.observado[i][j]) + "</td>";
                             soma += cruz.observado[i][j]; });
      h += "<td>" + n0.format(soma) + "</td></tr>";
    });
    h += "<tr class='pq-total'><th scope='row'>Total</th>";
    totais.forEach(t => { h += "<td>" + n0.format(t) + "</td>"; });
    return h + "<td>" + n0.format(cruz.n) + "</td></tr></tbody>";
  }

  function csvCruzamento(cruz) {
    const q = s => '"' + String(s).replace(/"/g, '""') + '"';
    const linhas = [[""].concat(cruz.cat_coluna).map(q).join(",")];
    cruz.cat_linha.forEach((r, i) =>
      linhas.push([q(r)].concat(cruz.observado[i]).join(",")));
    return linhas.join("\r\n") + "\r\n";
  }

  function baixar(nome, texto, tipo) {
    const blob = new Blob(["﻿" + texto], { type: tipo });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nome;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ------------------------------------------------- seletores (pílulas) */

  function grupoPilulas(rotuloGrupo, itens, selecionado, aoEscolher) {
    const caixa = document.createElement("div");
    caixa.className = "pq-controles";
    caixa.innerHTML = '<div class="pq-controles__rotulo">' +
                      escapar(rotuloGrupo) + "</div>";
    const linha = document.createElement("div");
    linha.className = "pq-pilulas";
    linha.setAttribute("role", "group");
    linha.setAttribute("aria-label", rotuloGrupo);
    for (const it of itens) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = it.texto;
      if (it.titulo) b.title = it.titulo;
      b.dataset.valor = it.valor;
      b.setAttribute("aria-pressed", String(it.valor === selecionado));
      b.addEventListener("click", () => aoEscolher(it.valor));
      linha.appendChild(b);
    }
    caixa.appendChild(linha);
    caixa.marcar = valor => {
      for (const b of linha.querySelectorAll("button")) {
        b.setAttribute("aria-pressed", String(b.dataset.valor === valor));
      }
    };
    return caixa;
  }

  /* ------------------------------------------ componente: mosaico completo */

  function montarMosaico(el) {
    const idBloco = el.dataset.bloco;
    const b = idBloco === "socio"
      ? { variaveis: BASE.ordem_socio, rotulo_item: "Primeira variável" }
      : bloco(idBloco);
    if (!b) { el.innerHTML = '<p class="pq-erro">Bloco desconhecido: ' +
                             escapar(idBloco) + "</p>"; return; }

    const itens = b.variaveis;
    const socios = BASE.ordem_socio;
    const nomeSegundo = idBloco === "socio" ? "Segunda variável"
                                            : "Variável sociodemográfica";

    let atualItem = el.dataset.item || itens[0];
    let atualSocio = el.dataset.socio ||
                     (idBloco === "socio" ? socios[1] : socios[0]);

    el.innerHTML = "";
    // Um bloco de uma pergunta só não ganha seletor: uma pílula solitária com
    // o enunciado inteiro não é um controle, é um parágrafo que parece
    // clicável.
    const umItem = itens.length === 1;
    const selItem = umItem ? null : grupoPilulas(b.rotulo_item || "Pergunta",
      itens.map(c => ({ valor: c, texto: rotulo(c),
                        titulo: (BASE.variaveis[c] || {}).descricao })),
      atualItem, v => { atualItem = v; render(); });
    const selSocio = grupoPilulas(nomeSegundo,
      socios.map(c => ({ valor: c, texto: rotulo(c),
                         titulo: (BASE.variaveis[c] || {}).pergunta })),
      atualSocio, v => { atualSocio = v; render(); });

    const resumo = document.createElement("p");
    resumo.className = "pq-resumo";
    resumo.setAttribute("aria-live", "polite");

    const grafico = document.createElement("div");
    grafico.className = "pq-grafico";
    grafico.setAttribute("role", "img");

    const nota = document.createElement("p");
    nota.className = "pq-nota";

    const detalhes = document.createElement("details");
    detalhes.className = "pq-tabela";
    detalhes.innerHTML = "<summary>Ver a tabela de contingência</summary>" +
                         '<div class="pq-rolagem"><table></table></div>';
    const botao = document.createElement("button");
    botao.className = "pq-botao";
    botao.type = "button";
    botao.textContent = "Baixar em CSV";
    detalhes.appendChild(botao);

    if (selItem) el.append(selItem);
    el.append(selSocio, resumo, grafico, nota, detalhes);

    function render() {
      if (selItem) selItem.marcar(atualItem);
      selSocio.marcar(atualSocio);

      if (atualItem === atualSocio) {
        resumo.innerHTML = "Selecione duas variáveis diferentes.";
        Plotly.purge(grafico);
        nota.textContent = "";
        return;
      }
      const cruz = obterCruzamento(atualItem, atualSocio);
      if (!cruz) {
        resumo.innerHTML = "Este cruzamento não está disponível.";
        Plotly.purge(grafico);
        return;
      }
      resumo.innerHTML = textoResumo(cruz);
      detalhes.querySelector("table").innerHTML = tabelaContingencia(cruz);
      const omitidos = desenharMosaico(grafico, cruz);
      let txt = "Largura das faixas: " + rotulo(cruz.coluna) +
                ". Altura dos blocos, dentro de cada faixa: " + rotulo(cruz.linha) + ".";
      if (omitidos.length) {
        txt += " Sem espaço para rótulo no eixo, da esquerda para a direita: " +
               omitidos.join(", ") + " — passe o cursor sobre a faixa, ou abra a " +
               "tabela de contingência.";
      }
      nota.textContent = txt;
      botao.onclick = () => baixar(
        (atualItem + "_x_" + atualSocio).replace(/[^\w]+/g, "_") + ".csv",
        csvCruzamento(cruz), "text/csv;charset=utf-8");
    }

    render();
    aoRedimensionar(render);
  }

  /* ================================================================== */
  /* Gráficos de distribuição                                           */
  /* ================================================================== */

  const LAYOUT_BARRAS = {
    plot_bgcolor: "rgba(0,0,0,0)", paper_bgcolor: "rgba(0,0,0,0)",
    bargap: 0.42, dragmode: false, hovermode: "closest",
    hoverlabel: { bgcolor: "#fff", bordercolor: COR.eixo,
                  font: { color: COR.tinta, size: 12 } },
  };
  const CONFIG_BARRAS = {
    responsive: true, displaylogo: false, displayModeBar: false,
    staticPlot: false,
  };

  const eixoValor = titulo => ({
    title: { text: titulo, font: { size: 11, color: COR.tinta2 } },
    gridcolor: COR.grade, griddash: "solid", gridwidth: 1,
    zeroline: false, showline: false, fixedrange: true,
    tickfont: { size: 11, color: COR.tinta2 }, ticksuffix: "%",
  });
  const eixoCategoria = () => ({
    automargin: true, showgrid: false, zeroline: false, showline: false,
    fixedrange: true, tickfont: { size: 11, color: COR.tinta2 },
  });

  /** Altura do gráfico a partir do número de linhas E de quantas linhas de
   *  texto cada rótulo ocupa. Uma altura fixa por barra corta os rótulos
   *  longos no meio da frase — o Plotly trunca com "…" quando o texto não cabe
   *  na faixa, e a reticência cai no meio de uma palavra. */
  function alturaBarras(n, rotulos) {
    const linhasTexto = (rotulos || []).reduce(
      (m, t) => Math.max(m, String(t).split("<br>").length), 1);
    const alturaLinha = Math.max(34, 15 * linhasTexto + 14);
    return Math.max(180, alturaLinha * n + 70);
  }

  /** Ordena as categorias de um bloco: substantivas primeiro (da mais alta
   *  para a mais baixa), com a categoria neutra sempre por último. */
  function categoriasOrdenadas(b, cats) {
    const neutro = b.neutro;
    let subst = cats.filter(c => c !== neutro);
    if (b.sentido === "asc") subst = subst.slice().reverse();
    return { substantivas: subst, neutro: cats.includes(neutro) ? neutro : null };
  }

  function tabelaDistribuicao(itens, cats, matriz, totais) {
    let h = "<thead><tr><th>Item</th>";
    for (const c of cats) h += "<th>" + escapar(c) + "</th>";
    h += "<th>Total</th></tr></thead><tbody>";
    itens.forEach((it, i) => {
      h += "<tr><th scope='row'>" + escapar(it) + "</th>";
      cats.forEach((_, j) => { h += "<td>" + n0.format(matriz[i][j]) + "</td>"; });
      h += "<td>" + n0.format(totais[i]) + "</td></tr>";
    });
    return h + "</tbody>";
  }

  function blocoTabela(html, legenda) {
    const d = document.createElement("details");
    d.className = "pq-tabela";
    d.innerHTML = "<summary>" + escapar(legenda || "Ver os números") +
                  '</summary><div class="pq-rolagem"><table>' + html + "</table></div>";
    return d;
  }

  function legendaHtml(cats, cores) {
    return '<div class="pq-legenda">' + cats.map((c, i) =>
      '<span><i style="background:' + cores[i] + '"></i>' + escapar(c) + "</span>"
    ).join("") + "</div>";
  }

  /* -------------------------------- empilhadas (likert / frequência) */

  function barrasEmpilhadas(el, b, opts) {
    opts = opts || {};
    const itens = b.variaveis;
    const cats = BASE.variaveis[itens[0]].categorias;
    const { substantivas, neutro } = categoriasOrdenadas(b, cats);
    const ordem = substantivas.concat(neutro ? [neutro] : []);
    const cores = rampa(substantivas.length).slice().reverse()
                    .concat(neutro ? [COR.neutro] : []);

    // Quantas categorias do topo entram no rótulo direto. Com 4 ou mais
    // degraus, uma só ("Concordo totalmente") subestima o que o leitor
    // entende por concordar.
    const nDestaque = substantivas.length >= 4 ? 2 : 1;
    const destaque = substantivas.slice(0, nDestaque);

    const linhas = itens.map(cod => {
      const m = BASE.marginais[cod];
      const pct = c => {
        const k = m.categorias.indexOf(c);
        return k < 0 || !m.n ? 0 : m.contagens[k] / m.n * 100;
      };
      const cont = c => {
        const k = m.categorias.indexOf(c);
        return k < 0 ? 0 : m.contagens[k];
      };
      return {
        cod, rotulo: rotulo(cod), n: m.n,
        pct: ordem.map(pct), contagens: ordem.map(cont),
        score: destaque.reduce((s, c) => s + pct(c), 0),
      };
    }).sort((a, b2) => a.score - b2.score);   // maior no topo do gráfico

    const tracos = ordem.map((cat, k) => ({
      type: "bar", orientation: "h", name: cat,
      x: linhas.map(l => l.pct[k]),
      y: linhas.map(l => quebrar(encurtar(l.rotulo, 76), estreito() ? 24 : 38)),
      marker: { color: cores[k], line: { color: COR.superficie, width: 1.5 } },
      // `text` seria desenhado DENTRO do segmento pelo Plotly, sobrepondo o
      // rótulo direto e estourando os segmentos estreitos. Para conteúdo de
      // tooltip o campo é `hovertext`.
      textposition: "none",
      hoverinfo: "text",
      hovertext: linhas.map(l => "<b>" + escapar(encurtar(l.rotulo, 70)) + "</b><br>" +
        escapar(cat) + ": " + n0.format(l.contagens[k]) +
        " (" + n1.format(l.pct[k]) + "%)<br>n = " + n0.format(l.n)),
      showlegend: false,
    }));

    // Rótulo direto no fim da barra — a leitura de relance que uma barra
    // divergente daria de graça, e que a rampa de um tom sozinha não dá.
    tracos.push({
      type: "scatter", mode: "text",
      x: linhas.map(() => 101), y: tracos[0].y,
      text: linhas.map(l => n0.format(l.score) + "%"),
      textposition: "middle right",
      textfont: { size: 11, color: COR.tinta2 },
      hoverinfo: "skip", showlegend: false, cliponaxis: false,
    });

    const legenda = document.createElement("div");
    legenda.innerHTML = legendaHtml(ordem, cores);

    const grafico = document.createElement("div");
    grafico.className = "pq-grafico";
    grafico.setAttribute("role", "img");
    grafico.setAttribute("aria-label",
      "Distribuição das respostas de " + (b.titulo || b.id));

    const nota = document.createElement("p");
    nota.className = "pq-nota";
    nota.textContent = "Percentual de quem respondeu cada item. O número à "
      + "direita soma " + destaque.join(" e ") + "; as linhas estão ordenadas "
      + "por ele.";

    el.append(legenda, grafico, nota,
      blocoTabela(tabelaDistribuicao(linhas.map(l => l.rotulo), ordem,
        linhas.map(l => l.contagens), linhas.map(l => l.n)),
        "Ver os números"));

    function desenhar() {
      Plotly.react(grafico, tracos, Object.assign({}, LAYOUT_BARRAS, {
        barmode: "stack",
        height: alturaBarras(linhas.length, tracos[0].y),
        margin: { l: 4, r: 52, t: 4, b: 42 },
        xaxis: Object.assign(eixoValor("% das respostas"), { range: [0, 108] }),
        yaxis: eixoCategoria(),
      }), CONFIG_BARRAS);
    }
    desenhar();
    aoRedimensionar(desenhar);
  }

  /* ------------------------------------- barras de série única (contagem) */

  function barrasSerieUnica(el, cfg) {
    // cfg: {linhas:[{rotulo,valor,contagem,n,titulo}], eixo, nota, ordenar}
    const linhas = cfg.ordenar
      ? cfg.linhas.slice().sort((a, b) => a.valor - b.valor)
      : cfg.linhas.slice().reverse();  // Plotly desenha de baixo para cima

    const grafico = document.createElement("div");
    grafico.className = "pq-grafico";
    grafico.setAttribute("role", "img");
    grafico.setAttribute("aria-label", cfg.aria || cfg.eixo);

    const nota = document.createElement("p");
    nota.className = "pq-nota";
    if (cfg.nota) nota.textContent = cfg.nota;

    let tab = "<thead><tr><th>Item</th><th>%</th><th>Contagem</th>" +
              "<th>n</th></tr></thead><tbody>";
    cfg.linhas.forEach(l => {
      tab += "<tr><th scope='row'>" + escapar(l.rotulo) + "</th><td>" +
             n1.format(l.valor) + "</td><td>" + n0.format(l.contagem) +
             "</td><td>" + n0.format(l.n) + "</td></tr>";
    });
    tab += "</tbody>";

    el.append(grafico, nota, blocoTabela(tab, "Ver os números"));

    function desenhar() {
      const traco = {
        type: "bar", orientation: "h",
        x: linhas.map(l => l.valor),
        y: linhas.map(l => quebrar(encurtar(l.rotulo, 90), estreito() ? 26 : 46)),
        marker: { color: COR.serie, cornerradius: 4 },
        textposition: "none",
        hoverinfo: "text",
        hovertext: linhas.map(l => "<b>" + escapar(encurtar(l.rotulo, 70)) + "</b><br>" +
          n1.format(l.valor) + "% · " + n0.format(l.contagem) + " de " +
          n0.format(l.n)),
        showlegend: false,
      };
      const rotulos = {
        type: "scatter", mode: "text",
        x: linhas.map(l => l.valor), y: traco.y,
        text: linhas.map(l => n1.format(l.valor) + "%"),
        textposition: "middle right",
        textfont: { size: 11, color: COR.tinta2 },
        hoverinfo: "skip", showlegend: false, cliponaxis: false,
      };
      const maximo = Math.max(10, ...linhas.map(l => l.valor));
      Plotly.react(grafico, [traco, rotulos], Object.assign({}, LAYOUT_BARRAS, {
        height: alturaBarras(linhas.length, traco.y),
        margin: { l: 4, r: 56, t: 4, b: 42 },
        xaxis: Object.assign(eixoValor(cfg.eixo), { range: [0, maximo * 1.14] }),
        yaxis: eixoCategoria(),
      }), CONFIG_BARRAS);
    }
    desenhar();
    aoRedimensionar(desenhar);
  }

  /* ------------------------------------------- distribuição por bloco */

  function montarDistribuicao(el) {
    const b = bloco(el.dataset.bloco);
    if (!b) { el.innerHTML = '<p class="pq-erro">Bloco desconhecido.</p>'; return; }
    el.innerHTML = "";

    if (b.forma === "likert") return barrasEmpilhadas(el, b);

    if (b.forma === "simnao") {
      // MO01/MO02: múltipla escolha marcada. O que interessa é quantos
      // marcaram cada item, não a divisão Sim/Não de cada um.
      const linhas = b.variaveis.map(cod => {
        const m = BASE.marginais[cod];
        const k = m.categorias.indexOf("Sim");
        const c = k < 0 ? 0 : m.contagens[k];
        return { rotulo: rotulo(cod), contagem: c, n: m.n,
                 valor: m.n ? c / m.n * 100 : 0 };
      });
      return barrasSerieUnica(el, {
        linhas, ordenar: true, eixo: "% dos respondentes",
        aria: "Percentual que marcou cada " + (b.rotulo_item || "item"),
        nota: "Cada respondente podia marcar até três opções, então a soma "
            + "passa de 100%.",
      });
    }

    if (b.forma === "frequencia") {
      // Visão geral: quem realizou a atividade ao menos uma vez. A
      // distribuição completa das 7 frequências fica no seletor abaixo — sete
      // degraus empilhados não se distinguem, e o mosaico já mostra a escala
      // inteira.
      const linhas = b.variaveis.map(cod => {
        const m = BASE.marginais[cod];
        const k = m.categorias.indexOf("Nenhuma vez");
        const nunca = k < 0 ? 0 : m.contagens[k];
        return { rotulo: rotulo(cod), contagem: m.n - nunca, n: m.n,
                 valor: m.n ? (m.n - nunca) / m.n * 100 : 0 };
      });
      barrasSerieUnica(el, {
        linhas, ordenar: true, eixo: "% que realizou ao menos uma vez",
        aria: "Percentual que realizou cada atividade ao menos uma vez",
        nota: "Percentual de quem respondeu a pergunta e realizou a atividade "
            + "ao menos uma vez nos 12 meses anteriores à coleta.",
      });
      return montarDetalheFrequencia(el, b);
    }

    // "unica": uma pergunta só, escala ordinal. A ordem do eixo é a da
    // escala, não a do tamanho — reordenar por frequência destruiria a
    // informação de que a escala é ordenada.
    const cod = b.variaveis[0];
    const m = BASE.marginais[cod];
    const linhas = m.categorias.map((c, i) => ({
      rotulo: c, contagem: m.contagens[i], n: m.n,
      valor: m.n ? m.contagens[i] / m.n * 100 : 0,
    }));
    barrasSerieUnica(el, {
      linhas, ordenar: false, eixo: "% das respostas",
      aria: "Distribuição de " + rotulo(cod),
      nota: n0.format(m.n) + " respostas · " + n0.format(m.n_ausentes) +
            " sem resposta.",
    });
  }

  /** Seletor de atividade + distribuição completa das sete frequências. */
  function montarDetalheFrequencia(el, b) {
    let atual = b.variaveis[0];
    const sel = grupoPilulas("Ver a distribuição completa de uma atividade",
      b.variaveis.map(c => ({ valor: c, texto: rotulo(c),
                              titulo: (BASE.variaveis[c] || {}).descricao })),
      atual, v => { atual = v; sel.marcar(v); render(); });
    const alvo = document.createElement("div");
    el.append(sel, alvo);

    function render() {
      alvo.innerHTML = "";
      const m = BASE.marginais[atual];
      barrasSerieUnica(alvo, {
        linhas: m.categorias.map((c, i) => ({
          rotulo: c, contagem: m.contagens[i], n: m.n,
          valor: m.n ? m.contagens[i] / m.n * 100 : 0,
        })),
        ordenar: false, eixo: "% das respostas",
        aria: "Distribuição de frequência de " + rotulo(atual),
        nota: (BASE.variaveis[atual] || {}).descricao + " · " +
              n0.format(m.n) + " respostas.",
      });
    }
    render();
  }

  /** Perfil: seletor de variável + distribuição, uma de cada vez. */
  function montarPerfil(el) {
    let atual = BASE.ordem_socio[0];
    el.innerHTML = "";
    const sel = grupoPilulas("Característica",
      BASE.ordem_socio.map(c => ({ valor: c, texto: rotulo(c),
                                   titulo: (BASE.variaveis[c] || {}).pergunta })),
      atual, v => { atual = v; sel.marcar(v); render(); });
    const pergunta = document.createElement("p");
    pergunta.className = "pq-pergunta";
    const alvo = document.createElement("div");
    el.append(sel, pergunta, alvo);

    function render() {
      const m = BASE.marginais[atual];
      pergunta.textContent = (BASE.variaveis[atual] || {}).pergunta || rotulo(atual);
      alvo.innerHTML = "";
      barrasSerieUnica(alvo, {
        linhas: m.categorias.map((c, i) => ({
          rotulo: c, contagem: m.contagens[i], n: m.n,
          valor: m.n ? m.contagens[i] / m.n * 100 : 0,
        })),
        ordenar: false, eixo: "% das respostas",
        aria: "Distribuição de " + rotulo(atual),
        nota: n0.format(m.n) + " responderam · " + n0.format(m.n_ausentes) +
              " deixaram em branco. Percentual ponderado disponível nos dados " +
              "publicados; os gráficos mostram valores brutos.",
      });
    }
    render();
  }

  /* ================================================================== */
  /* Tabela de tamanhos de efeito                                       */
  /* ================================================================== */

  /**
   * Todos os cruzamentos do site em uma tela, ordenáveis por V de Cramér.
   *
   * Existe para contrapor a afordância do resto do site. Um dashboard com
   * 1.012 mosaicos clicáveis convida o leitor a navegar até algo ficar
   * vermelho — e a correção de FDR controla a taxa de falsas descobertas
   * sobre os testes CALCULADOS, não sobre a busca visual de quem navega. Ver a
   * distribuição inteira dos tamanhos de efeito de uma vez é o antídoto: fica
   * imediatamente visível que a massa está perto de zero.
   */
  function montarEfeitos(el) {
    const dados = EFEITOS;
    if (!dados) { el.innerHTML = '<p class="pq-erro">Tabela indisponível.</p>'; return; }

    const R = dados.resumo;
    const idx = Object.fromEntries(dados.colunas.map((c, i) => [c, i]));
    const blocoDe = dados.bloco_de;
    const nomeBloco = id => {
      const b = BASE.blocos.find(x => x.id === id);
      return b ? (b.titulo || id) : id;
    };

    let filtroBloco = "";
    let soSignificativos = false;
    let busca = "";
    let limite = 40;
    let ordem = "v";

    el.innerHTML = "";

    /* ---------- histograma da distribuição inteira ---------- */
    const hist = document.createElement("div");
    hist.className = "pq-grafico";
    hist.setAttribute("role", "img");
    hist.setAttribute("aria-label",
      "Distribuição dos " + R.total + " tamanhos de efeito");

    const resumo = document.createElement("p");
    resumo.className = "pq-resumo";
    resumo.innerHTML =
      "<b>" + n0.format(R.total) + " cruzamentos</b>" +
      '<span class="pq-sep">·</span>mediana V = ' + n2.format(R.mediana) +
      '<span class="pq-sep">·</span>' + n0.format(R.acima_010) + " acima de 0,10" +
      '<span class="pq-sep">·</span>' + n0.format(R.acima_020) + " acima de 0,20" +
      '<span class="pq-alerta">Pela referência usual (Cohen), V abaixo de 0,10 é ' +
      "efeito desprezível. É onde está a maior parte deste survey.</span>";

    /* ---------- controles ---------- */
    const ctrl = document.createElement("div");
    ctrl.className = "pq-controles";
    ctrl.innerHTML =
      '<div class="pq-controles__rotulo">Filtrar</div>' +
      '<div class="pq-filtros">' +
      '<label>Bloco <select data-f="bloco"><option value="">todos</option>' +
      BASE.blocos.map(b => '<option value="' + b.id + '">' +
        escapar(b.titulo || b.id) + "</option>").join("") +
      "</select></label>" +
      '<label>Buscar <input type="search" data-f="busca" placeholder="variável…"></label>' +
      '<label class="pq-check"><input type="checkbox" data-f="sig"> ' +
      "só os significativos após FDR</label>" +
      "</div>";

    const contagem = document.createElement("p");
    contagem.className = "pq-nota";

    const caixa = document.createElement("div");
    caixa.className = "pq-rolagem";
    const tabela = document.createElement("table");
    tabela.className = "pq-efeitos";
    caixa.appendChild(tabela);

    const maisBtn = document.createElement("button");
    maisBtn.className = "pq-botao";
    maisBtn.type = "button";
    maisBtn.textContent = "Mostrar mais 40";

    const csvBtn = document.createElement("button");
    csvBtn.className = "pq-botao";
    csvBtn.type = "button";
    csvBtn.textContent = "Baixar tudo em CSV";
    csvBtn.style.marginLeft = "0.5rem";

    el.append(resumo, hist, ctrl, contagem, caixa, maisBtn, csvBtn);

    function filtradas() {
      const q = busca.trim().toLowerCase();
      return dados.linhas.filter(r => {
        if (soSignificativos && !r[idx.significativo]) return false;
        if (filtroBloco && blocoDe[r[idx.linha]] !== filtroBloco) return false;
        if (q) {
          const texto = (rotulo(r[idx.linha]) + " " + rotulo(r[idx.coluna]) + " " +
            ((BASE.variaveis[r[idx.linha]] || {}).descricao || "")).toLowerCase();
          if (!texto.includes(q)) return false;
        }
        return true;
      }).sort((a, b) => ordem === "v"
        ? (b[idx.v_cramer] || 0) - (a[idx.v_cramer] || 0)
        : (a[idx.p_ajustado] ?? 1) - (b[idx.p_ajustado] ?? 1));
    }

    function desenharHist(linhas) {
      const vs = linhas.map(r => r[idx.v_cramer]).filter(v => v !== null);
      Plotly.react(hist, [{
        type: "histogram", x: vs, xbins: { start: 0, end: 0.55, size: 0.01 },
        marker: { color: COR.serie }, hoverinfo: "x+y", name: "",
      }], Object.assign({}, LAYOUT_BARRAS, {
        height: 205,
        // As faixas de Cohen ficam ANOTADAS acima do plot: sem folga no topo,
        // o Plotly as corta pela metade.
        margin: { l: 46, r: 16, t: 26, b: 46 },
        bargap: 0.06,
        xaxis: {
          title: { text: "V de Cramér", font: { size: 11, color: COR.tinta2 } },
          gridcolor: COR.grade, zeroline: false, showline: false,
          fixedrange: true, tickfont: { size: 11, color: COR.tinta2 },
          range: [0, 0.55],
        },
        yaxis: {
          title: { text: "cruzamentos", font: { size: 11, color: COR.tinta2 } },
          gridcolor: COR.grade, zeroline: false, showline: false,
          fixedrange: true, tickfont: { size: 11, color: COR.tinta2 },
        },
        // As faixas de Cohen, para o leitor não ter de decorá-las.
        shapes: [0.10, 0.20, 0.30].map(x => ({
          type: "line", x0: x, x1: x, y0: 0, y1: 1, yref: "paper",
          line: { color: COR.eixo, width: 1 },
        })),
        annotations: [
          { x: 0.10, y: 1, yref: "paper", yanchor: "bottom", text: "desprezível ↤",
            showarrow: false, xanchor: "right",
            font: { size: 9, color: COR.tinta3 } },
          { x: 0.20, y: 1, yref: "paper", yanchor: "bottom", text: "fraca",
            showarrow: false, font: { size: 9, color: COR.tinta3 } },
          { x: 0.30, y: 1, yref: "paper", yanchor: "bottom", text: "moderada",
            showarrow: false, font: { size: 9, color: COR.tinta3 } },
        ],
      }), CONFIG_BARRAS);
    }

    function desenharTabela() {
      const linhas = filtradas();
      desenharHist(linhas);

      contagem.textContent = n0.format(linhas.length) + " de " +
        n0.format(dados.linhas.length) + " cruzamentos" +
        (linhas.length > limite ? " · mostrando os " + limite + " maiores" : "");

      let h = "<thead><tr>" +
        '<th>Variável temática</th><th>Cruzada com</th>' +
        '<th class="pq-ord" data-ord="v">V de Cramér</th>' +
        '<th class="pq-ord" data-ord="p">p ajustado</th>' +
        "<th>n</th></tr></thead><tbody>";
      for (const r of linhas.slice(0, limite)) {
        const v = r[idx.v_cramer], p = r[idx.p_ajustado];
        const sig = r[idx.significativo];
        h += "<tr" + (sig ? "" : ' class="pq-nao-sig"') + ">" +
          "<th scope='row'>" + escapar(rotulo(r[idx.linha])) +
          '<span class="pq-bloco">' + escapar(nomeBloco(blocoDe[r[idx.linha]])) +
          "</span></th>" +
          "<td>" + escapar(rotulo(r[idx.coluna])) + "</td>" +
          "<td>" + (v === null ? "—" : n2.format(v)) + "</td>" +
          "<td>" + (p === null ? "—" : (p < 0.001 ? "< 0,001" : n2.format(p))) +
          (sig ? "" : " <abbr title='não significativo após correção FDR'>n.s.</abbr>") +
          "</td>" +
          "<td>" + n0.format(r[idx.n]) + "</td></tr>";
      }
      tabela.innerHTML = h + "</tbody>";
      maisBtn.style.display = linhas.length > limite ? "" : "none";

      for (const th of tabela.querySelectorAll(".pq-ord")) {
        th.addEventListener("click", () => {
          ordem = th.dataset.ord; limite = 40; desenharTabela();
        });
      }
    }

    ctrl.querySelector('[data-f="bloco"]').addEventListener("change", e => {
      filtroBloco = e.target.value; limite = 40; desenharTabela();
    });
    ctrl.querySelector('[data-f="busca"]').addEventListener("input", e => {
      busca = e.target.value; limite = 40; desenharTabela();
    });
    ctrl.querySelector('[data-f="sig"]').addEventListener("change", e => {
      soSignificativos = e.target.checked; limite = 40; desenharTabela();
    });
    maisBtn.addEventListener("click", () => { limite += 40; desenharTabela(); });
    csvBtn.addEventListener("click", () => {
      const q = s => '"' + String(s).replace(/"/g, '""') + '"';
      const linhas = [["variavel", "rotulo", "cruzada_com", "rotulo_cruzada",
                       "bloco", "v_cramer", "p_ajustado", "significativo", "n"]
                      .map(q).join(",")];
      for (const r of dados.linhas) {
        linhas.push([q(r[idx.linha]), q(rotulo(r[idx.linha])),
                     q(r[idx.coluna]), q(rotulo(r[idx.coluna])),
                     q(blocoDe[r[idx.linha]] || ""),
                     r[idx.v_cramer] ?? "", r[idx.p_ajustado] ?? "",
                     r[idx.significativo], r[idx.n]].join(","));
      }
      baixar("tamanhos_de_efeito.csv", linhas.join("\r\n") + "\r\n",
             "text/csv;charset=utf-8");
    });

    desenharTabela();
    aoRedimensionar(desenharTabela);
  }

  /**
   * Distribuições univariadas completas das variáveis que foram agregadas.
   *
   * O risco de divulgação está no CRUZAMENTO de dois atributos protegidos, não
   * na contagem de um deles. Por isso os cruzamentos usam a versão agregada e
   * a contagem simples continua publicada inteira: esconder que um respondente
   * declarou islamismo não protegeria ninguém e empobreceria o registro.
   */
  function montarDetalhadas(el) {
    const det = BASE.marginais_detalhadas || {};
    const codigos = Object.keys(det);
    if (!codigos.length) { el.innerHTML = ""; return; }
    el.innerHTML = "";
    for (const cod of codigos) {
      const m = det[cod];
      let h = "<thead><tr><th>" + escapar(rotulo(cod)) +
              "</th><th>n</th><th>%</th></tr></thead><tbody>";
      m.categorias.forEach((c, i) => {
        h += "<tr><th scope='row'>" + escapar(c) + "</th><td>" +
             n0.format(m.contagens[i]) + "</td><td>" +
             n1.format(m.pct[i]) + "</td></tr>";
      });
      h += "<tr class='pq-total'><th scope='row'>Total</th><td>" +
           n0.format(m.n) + "</td><td>100,0</td></tr></tbody>";
      el.appendChild(blocoTabela(h,
        rotulo(cod) + " — todas as categorias, sem agregação"));
    }
  }

  /** Mosaico fixo, usado na explicação do gráfico. */
  function montarExemplo(el) {
    const [linha, coluna] = (el.dataset.chave || "").split("|");
    const cruz = obterCruzamento(linha, coluna);
    if (!cruz) { el.innerHTML = '<p class="pq-erro">Exemplo indisponível.</p>'; return; }
    el.innerHTML = "";
    const resumo = document.createElement("p");
    resumo.className = "pq-resumo";
    resumo.innerHTML = textoResumo(cruz);
    const g = document.createElement("div");
    g.className = "pq-grafico";
    g.setAttribute("role", "img");
    el.append(resumo, g);
    const desenhar = () => desenharMosaico(g, cruz);
    desenhar();
    aoRedimensionar(desenhar);
  }

  /* ------------------------------------------------------- redimensionar */

  const aRedesenhar = [];
  let eraEstreito = estreito();
  window.addEventListener("resize", () => {
    const agora = estreito();
    if (agora !== eraEstreito) { eraEstreito = agora; aRedesenhar.forEach(f => f()); }
  });
  function aoRedimensionar(f) { aRedesenhar.push(f); }

  /**
   * Gráficos em abas inativas.
   *
   * Uma aba fechada tem `display:none`, e um elemento assim mede zero de
   * largura. O Plotly desenha contra a largura do container: os componentes
   * criados na carga da página, dentro de abas que ainda não foram abertas,
   * nascem com layout calculado para zero pixel — eixos espremidos, rótulos
   * sobrepostos, margens negativas. O gráfico "existe" e está errado, que é
   * o pior dos dois mundos, porque nenhum teste de geometria pega (as
   * PROPORÇÕES continuam certas; só o tamanho está errado).
   *
   * A correção é redimensionar quando a aba aparece. `shown.bs.tab` é o
   * evento do Bootstrap que o Quarto usa nos `.panel-tabset`; o
   * IntersectionObserver cobre o caso de um gráfico que entra em tela por
   * outro motivo (âncora, `details` aberto, impressão).
   */
  function redimensionarSeguro(g) {
    // Um gráfico purgado (o estado "selecione duas variáveis diferentes")
    // perde `_fullLayout` mas continua no DOM e continua sendo observado.
    // Redimensioná-lo estoura dentro do Plotly, e o erro sobe como
    // `pageerror` — barulho que esconde falhas de verdade no console.
    if (!g || !g._fullLayout || !g.clientWidth) return;
    try { Plotly.Plots.resize(g); } catch (e) { /* corrida com purge */ }
  }

  function redimensionarDentro(raiz) {
    for (const g of raiz.querySelectorAll(".pq-grafico")) redimensionarSeguro(g);
  }

  function observarVisibilidade() {
    document.addEventListener("shown.bs.tab", (e) => {
      const alvo = e.target && e.target.getAttribute("data-bs-target");
      const painel = alvo ? document.querySelector(alvo) : null;
      redimensionarDentro(painel || document);
    });

    if (!("IntersectionObserver" in window)) return;
    const obs = new IntersectionObserver((entradas) => {
      for (const en of entradas) {
        if (en.isIntersecting) redimensionarSeguro(en.target);
      }
    }, { threshold: 0.01 });
    // Observa também os que ainda vão ser criados.
    const registrar = () => document.querySelectorAll(".pq-grafico")
      .forEach(g => obs.observe(g));
    registrar();
    new MutationObserver(registrar).observe(document.body,
      { childList: true, subtree: true });
  }

  /* ------------------------------------------------------------- números */

  /** Preenche `<span data-pq-num="meta.n_total">` etc. com valores do build.
   *  Assim o texto das páginas nunca repete um número à mão — e nunca
   *  contradiz o que o gráfico ao lado mostra. */
  function preencherNumeros() {
    for (const el of document.querySelectorAll("[data-pq-num]")) {
      const caminho = el.dataset.pqNum.split(".");
      let v = BASE;
      for (const p of caminho) v = v == null ? null : v[p];
      if (v === null || v === undefined) continue;
      const casas = el.dataset.casas ? parseInt(el.dataset.casas, 10) : null;
      el.textContent = typeof v === "number"
        ? (casas === null ? n0.format(v) : nf(casas).format(v))
        : String(v);
    }
  }

  /* --------------------------------------------------------------- boot */

  function aguardarPlotly(limite) {
    limite = limite || 15000;
    return new Promise((ok, falha) => {
      if (window.Plotly) return ok();
      const inicio = Date.now();
      const t = setInterval(() => {
        if (window.Plotly) { clearInterval(t); ok(); }
        else if (window.__plotlyFalhou || Date.now() - inicio > limite) {
          clearInterval(t);
          falha(new Error("a biblioteca de gráficos não carregou"));
        }
      }, 50);
    });
  }

  const CONSTRUTORES = {
    mosaico: montarMosaico,
    distribuicao: montarDistribuicao,
    perfil: montarPerfil,
    exemplo: montarExemplo,
    efeitos: montarEfeitos,
    detalhadas: montarDetalhadas,
  };

  async function iniciar() {
    const alvos = Array.from(document.querySelectorAll("[data-pq]"));
    // Páginas sem gráfico nenhum ainda podem citar números no texto
    // (`data-pq-num`). A nota metodológica é inteira assim: se ela não
    // carregasse o `base.json`, os números apareceriam como lacunas — que é
    // pior do que tê-los escritos à mão, porque parece defeito.
    const numeros = document.querySelectorAll("[data-pq-num]").length;
    if (!alvos.length && !numeros) return;

    const precisaCruz = alvos.some(
      el => ["mosaico", "exemplo"].includes(el.dataset.pq));
    const precisaEfeitos = alvos.some(el => el.dataset.pq === "efeitos");
    SECAO = document.body.dataset.pqSecao || null;

    alvos.forEach(el => { el.innerHTML = '<p class="pq-carregando">Carregando…</p>'; });

    try {
      await aguardarPlotly();
      const raiz = document.body.dataset.pqRaiz || "";
      BASE = await (await fetch(raiz + "dados/base.json")).json();
      if (precisaCruz && SECAO) {
        const pacote = await (await fetch(raiz + "dados/cruz-" + SECAO + ".json")).json();
        Object.assign(CRUZ, pacote.cruzamentos);
      }
      if (precisaEfeitos) {
        EFEITOS = await (await fetch(raiz + "dados/efeitos.json")).json();
      }
    } catch (erro) {
      alvos.forEach(el => {
        el.innerHTML = '<p class="pq-erro"><b>Não foi possível carregar os ' +
          "dados.</b><br>" + escapar(erro.message) + "<br><br>Se você abriu o " +
          "arquivo direto do disco, o navegador bloqueia o <code>fetch</code>: " +
          "rode <code>quarto preview</code> ou sirva a pasta por HTTP.</p>";
      });
      return;
    }

    preencherNumeros();
    for (const el of alvos) {
      const f = CONSTRUTORES[el.dataset.pq];
      if (f) { el.innerHTML = ""; try { f(el); } catch (e) {
        el.innerHTML = '<p class="pq-erro">Falha ao desenhar: ' +
                       escapar(e.message) + "</p>";
        console.error(e);
      } }
    }
    observarVisibilidade();
    document.body.dataset.pqPronto = "1";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  return { iniciar, obterCruzamento, geometria, corResiduo, rampa,
           get base() { return BASE; }, get cruzamentos() { return CRUZ; } };
})();
