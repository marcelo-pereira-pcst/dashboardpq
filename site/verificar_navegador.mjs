/**
 * Verificação em navegador real do site renderizado (`../docs`).
 *
 * O que este arquivo testa, e o `verificar.mjs` não pode: que o Quarto gerou
 * as páginas, que o Plotly desenhou, que os rótulos couberam, que o hover
 * responde, que o CSV baixa e que o console fica limpo. Geometria correta não
 * garante página funcionando — as duas coisas já falharam separadamente neste
 * projeto.
 *
 * Percorre TODAS as combinações de todos os mosaicos de todas as páginas,
 * lendo a geometria real dos retângulos no SVG e comparando com o JSON.
 *
 * Uso:
 *   node site/verificar_navegador.mjs [--capturas pasta] [--amostra N]
 *
 * Precisa de Playwright: npm install playwright && npx playwright install chromium
 */

import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { readFileSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, extname, normalize, resolve } from "node:path";

const AQUI = dirname(fileURLToPath(import.meta.url));
const RAIZ = resolve(AQUI, "..", "docs");

if (!existsSync(join(RAIZ, "index.html"))) {
  console.error(`Nada em ${RAIZ}. Rode \`quarto render\` dentro de site/ primeiro.`);
  process.exit(1);
}

const dadosBase = JSON.parse(readFileSync(join(RAIZ, "dados", "base.json"), "utf-8"));

// Todos os cruzamentos de todas as seções num mapa só. O site carrega um
// arquivo por página; aqui interessa conferir tudo contra tudo.
const CRUZ = {};
for (const secao of dadosBase.secoes) {
  const caminho = join(RAIZ, "dados", `cruz-${secao.id}.json`);
  if (!existsSync(caminho)) {
    console.error(`  ✗ falta ${caminho}`);
    process.exit(1);
  }
  Object.assign(CRUZ, JSON.parse(readFileSync(caminho, "utf-8")).cruzamentos);
}

const args = process.argv.slice(2);
const opt = (nome) => args.includes(nome) ? args[args.indexOf(nome) + 1] : null;
const pastaCapturas = opt("--capturas");
const amostra = opt("--amostra") ? parseInt(opt("--amostra"), 10) : Infinity;
if (pastaCapturas) mkdirSync(pastaCapturas, { recursive: true });

/* ---------------------------------------------------------------- servidor */
const TIPOS = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript",
  ".json": "application/json", ".css": "text/css", ".png": "image/png",
  ".jpg": "image/jpeg", ".pdf": "application/pdf", ".svg": "image/svg+xml",
  ".woff": "font/woff", ".woff2": "font/woff2",
};
const servidor = createServer(async (req, res) => {
  const caminho = decodeURIComponent(req.url.split("?")[0]);
  const alvo = join(RAIZ, normalize(caminho === "/" ? "/index.html" : caminho));
  if (!alvo.startsWith(RAIZ)) { res.writeHead(403).end(); return; }
  try {
    const corpo = await readFile(alvo);
    res.writeHead(200, {
      "content-type": TIPOS[extname(alvo)] || "application/octet-stream",
    });
    res.end(corpo);
  } catch { res.writeHead(404).end("404"); }
});
await new Promise(r => servidor.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${servidor.address().port}/`;

/* -------------------------------------------------------------- navegador */
const navegador = await chromium.launch();
const contexto = await navegador.newContext({ viewport: { width: 1280, height: 900 } });

let falhas = 0;
const erro = (onde, msg) => { falhas++; console.error(`  ✗ ${onde}: ${msg}`); };

const PAGINAS = [
  { arquivo: "index.html", titulo: "Início" },
  { arquivo: "achados.html", titulo: "Achados" },
  { arquivo: "atividades.html", titulo: "Atividades" },
  { arquivo: "opinioes-ct.html", titulo: "Opiniões C&T" },
  { arquivo: "opinioes-dc.html", titulo: "Opiniões DC" },
  { arquivo: "motivacoes.html", titulo: "Motivações" },
  { arquivo: "perfil.html", titulo: "Perfil" },
  { arquivo: "metodologia.html", titulo: "Metodologia" },
];

let totalCombos = 0, totalBlocos = 0, piorErroArea = 0;
let totalDistribuicoes = 0;
const ruidoGlobal = [];

/** Abre a aba (`.panel-tabset`) que contém o seletor dado, se houver. */
async function ativarAbaDe(pagina, seletor) {
  const abriu = await pagina.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const painel = el.closest(".tab-pane");
    if (!painel) return true;              // não está em aba nenhuma
    const gatilho = document.querySelector(
      `[data-bs-target="#${CSS.escape(painel.id)}"], a[href="#${CSS.escape(painel.id)}"]`);
    if (gatilho) { gatilho.click(); return true; }
    return false;
  }, seletor);
  if (abriu) await pagina.waitForTimeout(180);
  return abriu;
}

async function retangulos(pagina, seletorId) {
  return pagina.evaluate((id) => {
    const gd = document.getElementById(id);
    if (!gd || !gd._fullLayout) return null;
    const xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis;
    const saida = [];
    for (const traco of gd.querySelectorAll(".scatterlayer .trace")) {
      const p = traco.querySelector("path.js-fill");
      if (!p) continue;
      const c = p.getBBox();
      saida.push({
        x0: xa.p2d(c.x), x1: xa.p2d(c.x + c.width),
        y0: ya.p2d(c.y + c.height), y1: ya.p2d(c.y),
      });
    }
    return saida;
  }, seletorId);
}

for (const info of PAGINAS) {
  const pagina = await contexto.newPage();
  const problemas = [];
  pagina.on("console", m => {
    if (m.type() === "error" || m.type() === "warning") {
      problemas.push(`[${m.type()}] ${m.text()}`);
    }
  });
  pagina.on("pageerror", e => problemas.push(`[pageerror] ${e.message}`));
  pagina.on("requestfailed", r =>
    problemas.push(`[requestfailed] ${r.url()} — ${r.failure()?.errorText}`));

  await pagina.goto(base + info.arquivo, { waitUntil: "networkidle" });

  // Navbar: as sete entradas precisam existir e apontar para páginas reais.
  const links = await pagina.$$eval(".navbar a.nav-link",
    as => as.map(a => ({ texto: a.textContent.trim(), href: a.getAttribute("href") })));
  if (links.length < 6) {
    erro(info.arquivo, `navbar com ${links.length} itens, esperados 7`);
  }
  for (const l of links) {
    if (!l.href || l.href.startsWith("#")) continue;
    const r = await pagina.request.get(new URL(l.href, base + info.arquivo).href);
    if (!r.ok()) erro(info.arquivo, `link da navbar quebrado: ${l.href}`);
  }

  const temComponentes = await pagina.$$eval("[data-pq]", els => els.length);
  if (temComponentes) {
    await pagina.waitForFunction(() => document.body.dataset.pqPronto === "1",
      null, { timeout: 30000 }).catch(() => {
        erro(info.arquivo, "a página não sinalizou pronto em 30 s");
      });
  }

  // Nenhum número do texto pode ter ficado por preencher.
  const vazios = await pagina.$$eval("[data-pq-num]",
    els => els.filter(e => !e.textContent.trim()).map(e => e.dataset.pqNum));
  if (vazios.length) {
    erro(info.arquivo, `data-pq-num sem valor: ${[...new Set(vazios)].join(", ")}`);
  }

  // Toda aba precisa ser clicável e revelar conteúdo.
  const abas = await pagina.$$(".panel-tabset .nav-link");
  for (let i = 0; i < abas.length; i++) {
    await abas[i].click();
    await pagina.waitForTimeout(60);
  }
  if (abas.length) await abas[0].click();

  // --------------------------------------------------------- distribuições
  const distribuicoes = await pagina.$$eval('[data-pq="distribuicao"], [data-pq="perfil"]',
    els => els.map(e => ({
      bloco: e.dataset.bloco || "perfil",
      graficos: e.querySelectorAll(".pq-grafico").length,
      tabelas: e.querySelectorAll("details.pq-tabela").length,
      erro: e.querySelector(".pq-erro") ? e.querySelector(".pq-erro").textContent : null,
    })));
  for (const d of distribuicoes) {
    totalDistribuicoes++;
    if (d.erro) erro(`${info.arquivo}/${d.bloco}`, `distribuição com erro: ${d.erro}`);
    if (!d.graficos) erro(`${info.arquivo}/${d.bloco}`, "distribuição sem gráfico");
    if (!d.tabelas) erro(`${info.arquivo}/${d.bloco}`, "distribuição sem tabela (a11y)");
  }

  // ------------------------------------------------------ tabela de efeitos
  const temEfeitos = await pagina.$$eval('[data-pq="efeitos"]', e => e.length);
  if (temEfeitos) {
    await ativarAbaDe(pagina, '[data-pq="efeitos"]');
    const info2 = await pagina.evaluate(() => {
      const el = document.querySelector('[data-pq="efeitos"]');
      return {
        erro: el.querySelector(".pq-erro") ? el.querySelector(".pq-erro").textContent : null,
        linhas: el.querySelectorAll("table.pq-efeitos tbody tr").length,
        grafico: !!el.querySelector(".pq-grafico"),
      };
    });
    if (info2.erro) erro(info.arquivo, `tabela de efeitos com erro: ${info2.erro}`);
    if (!info2.grafico) erro(info.arquivo, "tabela de efeitos sem histograma");
    if (info2.linhas < 10) erro(info.arquivo, `tabela de efeitos com ${info2.linhas} linhas`);

    // Filtrar por bloco. Contar linhas VISÍVEIS não serve de teste: a tabela é
    // paginada em 40, então o filtro pode funcionar e o número não mudar. O que
    // prova o filtro é toda linha exibida pertencer ao bloco escolhido.
    await pagina.selectOption('[data-pq="efeitos"] select[data-f="bloco"]', "adc1");
    await pagina.waitForTimeout(250);
    const blocosVisiveis = await pagina.$$eval(
      "table.pq-efeitos tbody .pq-bloco",
      els => [...new Set(els.map(e => e.textContent.trim()))]);
    if (blocosVisiveis.length !== 1) {
      erro(info.arquivo,
           `filtro por bloco deixou ${blocosVisiveis.length} blocos: ${blocosVisiveis}`);
    }
    // E o contador precisa refletir o subconjunto, não o total.
    const contador = await pagina.textContent('[data-pq="efeitos"] .pq-nota');
    if (!/^165 de 1\.012/.test(contador.trim())) {
      erro(info.arquivo, `contador do filtro: "${contador.trim().slice(0, 60)}"`);
    }
    await pagina.selectOption('[data-pq="efeitos"] select[data-f="bloco"]', "");
    await pagina.waitForTimeout(250);

    const [dlEf] = await Promise.all([
      pagina.waitForEvent("download", { timeout: 8000 }).catch(() => null),
      pagina.locator('[data-pq="efeitos"] .pq-botao').last().click(),
    ]);
    if (!dlEf) erro(info.arquivo, "CSV de tamanhos de efeito não baixou");
    else {
      const linhasCsv = readFileSync(await dlEf.path(), "utf-8")
        .replace(/^\ufeff/, "").trim().split("\r\n");
      const esperado = Object.values(CRUZ).length + 1;
      if (linhasCsv.length !== esperado) {
        erro(info.arquivo,
             `CSV de efeitos com ${linhasCsv.length} linhas, esperado ${esperado}`);
      }
    }
  }

  // -------------------------------------------------------------- mosaicos
  const mosaicos = await pagina.$$eval('[data-pq="mosaico"]',
    els => els.map((e, i) => { e.dataset.idx = i; return e.dataset.bloco; }));

  for (let m = 0; m < mosaicos.length; m++) {
    const idBloco = mosaicos[m];
    const b = idBloco === "socio"
      ? { variaveis: dadosBase.ordem_socio }
      : dadosBase.blocos.find(x => x.id === idBloco);
    if (!b) { erro(info.arquivo, `bloco desconhecido ${idBloco}`); continue; }

    // Abre a aba que contém este mosaico. Um gráfico em aba fechada mede
    // zero de largura, e o layout do Plotly sai calculado para zero pixel.
    await ativarAbaDe(pagina, `[data-pq="mosaico"][data-idx="${m}"]`);

    const idGrafico = await pagina.evaluate((idx) => {
      const el = document.querySelector(`[data-pq="mosaico"][data-idx="${idx}"]`);
      const g = el.querySelector(".pq-grafico");
      g.id = "pq-teste-" + idx;
      return g.id;
    }, m);

    // A largura precisa ser real, não a de uma aba fechada.
    const larguraOk = await pagina.evaluate(
      (id) => document.getElementById(id).clientWidth, idGrafico);
    if (larguraOk < 300) {
      erro(`${info.arquivo}/${idBloco}`,
           `gráfico com ${larguraOk}px de largura — aba não abriu ou não redimensionou`);
    }

    const combos = [];
    for (const item of b.variaveis) {
      for (const socio of dadosBase.ordem_socio) {
        if (item !== socio) combos.push([item, socio]);
      }
    }

    for (const [item, socio] of combos.slice(0, amostra)) {
      const onde = `${info.arquivo}/${idBloco} ${item}×${socio}`;
      await pagina.evaluate(({ idx, item, socio }) => {
        const el = document.querySelector(`[data-pq="mosaico"][data-idx="${idx}"]`);
        // Dois cuidados: blocos de uma pergunta só não têm seletor de item
        // (um grupo apenas), e no bloco sociodemográfico os DOIS grupos
        // oferecem os mesmos valores — procurar "o primeiro botão com este
        // valor" acertaria o grupo errado e mandaria as duas seleções para o
        // mesmo lado.
        const grupos = el.querySelectorAll(".pq-pilulas");
        const clicar = (g, v) => {
          if (!g) return;
          const b = Array.from(g.querySelectorAll("button"))
            .find(x => x.dataset.valor === v);
          if (b) b.click();
        };
        if (grupos.length > 1) clicar(grupos[0], item);
        clicar(grupos[grupos.length - 1], socio);
      }, { idx: m, item, socio });
      await pagina.waitForTimeout(20);

      const cruz = CRUZ[`${item}|${socio}`] || CRUZ[`${socio}|${item}`];
      if (!cruz) { erro(onde, "cruzamento ausente no JSON"); continue; }

      const esperados = cruz.observado.flat().filter(v => v > 0).length;
      const desenhados = await retangulos(pagina, idGrafico);
      if (!desenhados) { erro(onde, "gráfico não inicializado"); continue; }
      if (desenhados.length !== esperados) {
        erro(onde, `${desenhados.length} retângulos, esperados ${esperados}`);
        continue;
      }

      const areaPintada = desenhados.reduce((s, r) =>
        s + (r.x1 - r.x0) * (r.y1 - r.y0), 0);
      const nC = cruz.cat_coluna.length, nL = cruz.cat_linha.length;
      const areaUtil = (1 - 0.006 * (nC - 1)) * (1 - 0.004 * (nL - 1));
      const dif = Math.abs(areaPintada - areaUtil);
      piorErroArea = Math.max(piorErroArea, dif);
      if (dif > 0.02) {
        erro(onde, `área pintada ${areaPintada.toFixed(4)} ≠ útil ${areaUtil.toFixed(4)}`);
      }
      for (const r of desenhados) {
        if (r.x0 < -0.004 || r.x1 > 1.004 || r.y0 < -0.004 || r.y1 > 1.004) {
          erro(onde, "retângulo fora da área do gráfico"); break;
        }
      }
      totalBlocos += desenhados.length;
      totalCombos++;
    }
  }

  // ------------------------------------------------------------ hover/CSV
  if (mosaicos.length) {
    await ativarAbaDe(pagina, '[data-pq="mosaico"][data-idx="0"]');
    // A aba usa transição do Bootstrap e o gráfico só é redimensionado depois
    // dela; medir cedo devolve a caixa antiga.
    await pagina.waitForTimeout(600);

    // Mira o CENTRO DO MAIOR RETÂNGULO desenhado, em vez de uma fração fixa da
    // caixa do SVG. Uma fração fixa cai na margem esquerda (que tem 150 px de
    // rótulos) sempre que a primeira faixa é estreita — foi o que aconteceu
    // nas páginas de motivações e perfil, e o "tooltip vazio" resultante era
    // do teste, não da página.
    // Rolar até o gráfico ANTES de medir. `getBoundingClientRect` devolve
    // coordenadas de viewport, e `mouse.move` só alcança o que está na
    // viewport: um mosaico abaixo da dobra tem y maior que a altura da janela,
    // e o cursor simplesmente não chega nele.
    await pagina.evaluate(() => {
      const el = document.querySelector('[data-pq="mosaico"][data-idx="0"]');
      el.scrollIntoView({ block: "center", behavior: "instant" });
    });
    await pagina.waitForTimeout(250);

    const alvo = await pagina.evaluate(() => {
      const el = document.querySelector('[data-pq="mosaico"][data-idx="0"]');
      const caminhos = el.querySelectorAll(".scatterlayer .trace path.js-fill");
      let melhor = null, area = 0;
      for (const p of caminhos) {
        const r = p.getBoundingClientRect();
        if (r.width * r.height > area) { area = r.width * r.height; melhor = r; }
      }
      return melhor && area > 0
        ? { x: melhor.x + melhor.width / 2, y: melhor.y + melhor.height / 2 }
        : null;
    });
    if (!alvo) {
      erro(info.arquivo, "nenhum retângulo desenhado para testar o hover");
    } else {
      await pagina.mouse.move(alvo.x, alvo.y);
      await pagina.waitForTimeout(350);
      const dica = (await pagina.locator(".hoverlayer text").allTextContents()).join(" ");
      for (const marca of ["observado", "esperado", "resíduo"]) {
        if (!dica.includes(marca)) {
          erro(info.arquivo, `tooltip sem "${marca}" (${dica.slice(0, 100)})`);
        }
      }
    }
    await pagina.$$eval('[data-pq="mosaico"][data-idx="0"] details.pq-tabela',
      ds => ds.forEach(d => { d.open = true; }));
    const [dl] = await Promise.all([
      pagina.waitForEvent("download", { timeout: 8000 }).catch(() => null),
      pagina.locator('[data-pq="mosaico"][data-idx="0"] .pq-botao').first().click(),
    ]);
    if (!dl) erro(info.arquivo, "o botão de CSV não produziu arquivo");
    await pagina.$$eval("details.pq-tabela", ds => ds.forEach(d => { d.open = false; }));
  }

  if (pastaCapturas) {
    await pagina.screenshot({
      path: join(pastaCapturas, info.arquivo.replace(".html", "") + "-desktop.png"),
      fullPage: true,
    });
  }

  const ruido = problemas.filter(p => !p.includes("cdnjs") && !p.includes("favicon"));
  if (ruido.length) {
    ruidoGlobal.push(...ruido.map(r => `${info.arquivo}: ${r}`));
  }
  console.log(`  ${info.titulo.padEnd(16)} ok · ${mosaicos.length} mosaico(s) · ` +
              `${distribuicoes.length} distribuição(ões)` +
              (ruido.length ? ` · ${ruido.length} no console` : ""));
  await pagina.close();
}

/* ------------------------------------------------------------- celular */
if (pastaCapturas) {
  const movel = await contexto.newPage();
  await movel.setViewportSize({ width: 390, height: 844 });
  for (const arq of ["index.html", "atividades.html", "opinioes-ct.html"]) {
    await movel.goto(base + arq, { waitUntil: "networkidle" });
    await movel.waitForTimeout(1200);
    await movel.screenshot({
      path: join(pastaCapturas, arq.replace(".html", "") + "-celular.png"),
      fullPage: true,
    });
  }
  await movel.close();
}

await navegador.close();
servidor.close();

console.log(`
páginas:              ${PAGINAS.length}
distribuições:        ${totalDistribuicoes}
combinações mosaico:  ${totalCombos}
blocos conferidos:    ${totalBlocos}
maior erro de área:   ${piorErroArea.toExponential(2)}
console:              ${ruidoGlobal.length ? ruidoGlobal.length + " mensagem(ns)" : "limpo"}`);
for (const r of ruidoGlobal.slice(0, 12)) console.log("   " + r);

if (falhas || ruidoGlobal.length) {
  console.error(`\nFALHOU: ${falhas} problema(s) + ${ruidoGlobal.length} do console.`);
  process.exit(1);
}
console.log("\nOK — as páginas funcionam em navegador real.");
