// Etapa 5 — testes dos gráficos: página real (jsdom) + backend real + provedor SIMULADO (dados SINTÉTICOS).
// jsdom não faz layout: a responsividade/sobreposição é verificada pela estrutura (larguras em %, quebra de nomes, regras de CSS).
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
import { JSDOM } from 'jsdom';

const AQUI = dirname(fileURLToPath(import.meta.url));
let proc, base;
const portaLivre = () => new Promise(res => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const dormir = ms => new Promise(r => setTimeout(r, ms));
async function esperar(cond, ms = 6000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await cond()) return; await dormir(15); }
  throw new Error('timeout esperando: ' + cond.toString());
}
before(async () => {
  const porta = await portaLivre();
  proc = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env: { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-gr-')), 'g.db') }, stdio: 'ignore' });
  base = `http://127.0.0.1:${porta}`;
  await esperar(async () => { try { return (await fetch(base + '/status')).ok; } catch { return false; } }, 20000);
});
after(() => proc && proc.kill());

async function abrir({ historico } = {}) {
  const html = await (await fetch(base + '/')).text();
  const chamadas = [];
  const dom = new JSDOM(html, {
    url: base + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) {
      w.confirm = () => true;
      w.fetch = (u, o) => { chamadas.push(`${(o && o.method) || 'GET'} ${u}`); return fetch(new URL(u, base), o); };
      if (historico) w.localStorage.setItem('vagas-historico', JSON.stringify(historico));
    },
  });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas,
    chat: async texto => {
      const antes = d.querySelectorAll('.msg.bot').length;
      $('q').value = texto; $('btn').click();
      await esperar(() => d.querySelectorAll('.msg.bot').length > antes && !$('btn').disabled && !/Buscando vagas/.test([...d.querySelectorAll('.msg.bot')].pop().textContent));
      return [...d.querySelectorAll('.msg.bot')].pop();
    },
    figuras: box => [...box.querySelectorAll('figure.gr')],
    titulo: f => f.querySelector('figcaption').textContent,
    linhas: f => [...f.querySelectorAll('.gr-lista > [role=listitem]')],
    tabela: (box, t) => [...box.querySelectorAll('table tbody tr')].map(tr => [...tr.children].map(td => td.textContent)).find(r => r[0] === t),
  };
  return ui;
}
const larg = el => parseFloat(el.style.width);
const linhaChat = r => ({ nome: r.querySelector('.gr-nome').textContent, valor: r.querySelector('.gr-valor').textContent, largura: larg(r.querySelector('.gr-barra')) });

test('1: resultado válido — barras de tecnologias, diferenciais, soft skills e senioridade, com escala coerente', async () => {
  const ui = await abrir();
  const msg = await ui.chat('Graf Base');
  const figs = ui.figuras(msg);
  assert.deepEqual(figs.map(ui.titulo), ['Tecnologias mais pedidas', 'Diferenciais', 'Soft skills', 'Distribuição por nível indicado']);
  assert.equal(msg.querySelectorAll('.row, .track, .fill').length, 0);          // as barras antigas (nomes truncados) foram substituídas
  const [tec, dif, soft, niv] = figs;
  assert.match(tec.querySelector('.gr-sub').textContent, /% das 12 vagas analisadas que citam o item \(escala de 0% a 100%\)/);
  const linhas = ui.linhas(tec).map(linhaChat);
  assert.ok(linhas.length > 10);
  const js = linhas.find(l => l.nome === 'JavaScript'), react = linhas.find(l => l.nome === 'React'), ts = linhas.find(l => l.nome === 'TypeScript');
  assert.deepEqual(js, { nome: 'JavaScript', valor: '100% (12 de 12 vagas)', largura: 100 });
  assert.deepEqual(react, { nome: 'React', valor: '75% (9 de 12 vagas)', largura: 75 });
  assert.equal(ts.largura, 42); assert.match(ts.valor, /^42% \(5 de 12 vagas\)$/);
  const pcts = linhas.map(l => parseInt(l.valor)); assert.deepEqual(pcts, [...pcts].sort((a, b) => b - a));  // maior -> menor
  assert.ok(linhas.every(l => Math.abs(l.largura - parseInt(l.valor)) < 0.5));                               // mesma escala 0-100 em todas as barras
  // limite inicial + "Ver mais"
  const rows = ui.linhas(tec), btn = tec.querySelector('button');
  assert.equal(rows.filter(r => !r.hidden).length, 10); assert.equal(btn.textContent, `Ver mais ${rows.length - 10}`);
  btn.click();
  assert.equal(rows.filter(r => !r.hidden).length, rows.length); assert.equal(btn.textContent, 'Ver menos'); assert.equal(btn.getAttribute('aria-expanded'), 'true');
  btn.click(); assert.equal(rows.filter(r => !r.hidden).length, 10);
  // nomes extensos continuam completos (nada de reticências) e quebram em vez de estourar
  const longo = linhas.find(l => l.nome === 'Realidade aumentada/virtual');
  assert.ok(longo && /^17% \(2 de 12 vagas\)$/.test(longo.valor));
  assert.ok(ui.d.querySelector('style').textContent.includes('.gr-nome{overflow-wrap:anywhere'));
  // soft skills em gráfico próprio (não misturado com tecnologias)
  const sl = ui.linhas(soft).map(linhaChat);
  assert.deepEqual(sl.find(l => l.nome === 'Trabalho em equipe'), { nome: 'Trabalho em equipe', valor: '67% (8 de 12 vagas)', largura: 67 });
  assert.ok(!sl.some(l => l.nome === 'JavaScript'));
  // diferenciais
  assert.ok(ui.linhas(dif).map(linhaChat).some(l => l.nome === 'Terraform' && l.valor === '25% (3 de 12 vagas)'));
  // distribuição por senioridade
  const nl = Object.fromEntries(ui.linhas(niv).map(linhaChat).map(l => [l.nome, l]));
  assert.deepEqual([nl['Júnior'].valor, nl['Pleno'].valor, nl['Sênior'].valor, nl['Não informado'].valor], ['33% (4 de 12 vagas)', '33% (4 de 12 vagas)', '25% (3 de 12 vagas)', '8% (1 de 12 vagas)']);
  assert.equal(nl['Sênior'].largura, 25);
  // texto preservado como alternativa
  assert.match(msg.querySelector('.meta').textContent, /Níveis: Júnior 4 · Pleno 4 · Sênior 3 · Não informado 1/);
});

test('6: percentuais do texto e dos gráficos são os mesmos números (inclusive o texto da API)', async () => {
  const ui = await abrir();
  const msg = await ui.chat('Graf Base');
  const resp = await (await fetch(base + '/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mensagem: 'Graf Base', pais: 'br', paginas: 3, apenas_novas: false }) })).json();
  const doTexto = Object.fromEntries([...resp.resposta.matchAll(/^- (.+?): (\d+)% \((\d+) vagas\)$/gm)].map(m => [m[1], `${m[2]}% (${m[3]} de ${resp.dados.vagas_analisadas} vagas)`]));
  const naTela = Object.fromEntries(ui.figuras(msg).flatMap(f => ui.linhas(f)).map(r => [r.querySelector('.gr-nome').textContent, r.querySelector('.gr-valor').textContent]));
  assert.ok(Object.keys(doTexto).length >= 15);
  for (const [nome, valor] of Object.entries(doTexto)) assert.equal(naTela[nome], valor, nome);
  // e a alternativa em texto de cada gráfico repete exatamente as linhas desenhadas
  for (const f of ui.figuras(msg)) {
    const desenhado = ui.linhas(f).map(r => `${r.querySelector('.gr-nome').textContent}: ${r.querySelector('.gr-valor').textContent}`);
    const alt = [...f.querySelectorAll('details.gr-texto li')].map(li => li.textContent);
    assert.deepEqual(alt, desenhado);
  }
});

test('2/3/4: nova pesquisa gera gráficos novos com os próprios dados; listas vazias e dados insuficientes são omitidos com explicação', async () => {
  const ui = await abrir();
  const m1 = await ui.chat('Graf Base');
  const m2 = await ui.chat('Graf Poucos');
  assert.notEqual(m1, m2);
  assert.match(ui.figuras(m1)[0].querySelector('.gr-sub').textContent, /das 12 vagas/);     // a resposta anterior segue com os seus dados
  const f2 = ui.figuras(m2);
  assert.deepEqual(f2.map(ui.titulo), ['Tecnologias mais pedidas']);                         // sem soft skills, diferenciais ou níveis: nada de gráfico vazio
  assert.match(f2[0].querySelector('.gr-sub').textContent, /das 2 vagas/);
  assert.deepEqual(ui.linhas(f2[0]).map(linhaChat).filter(l => l.nome === 'JavaScript'), [{ nome: 'JavaScript', valor: '100% (2 de 2 vagas)', largura: 100 }]);
  assert.match(m2.textContent, /Nenhuma vaga indicou o nível: o gráfico de distribuição por nível foi omitido \(dados insuficientes\)/);
  assert.equal(m2.querySelectorAll('figure').length, 1);
  assert.equal(m1.querySelectorAll('figure').length, 4);                                     // a 1ª continua intacta
});

test('5: valor extremo (100%) e categoria única', async () => {
  const ui = await abrir();
  const m = await ui.chat('Graf Pleno100');
  const fs = ui.figuras(m);
  assert.deepEqual(fs.map(ui.titulo).slice(-1), ['Distribuição por nível indicado']);
  const nivel = ui.linhas(fs.at(-1)).map(linhaChat);
  assert.deepEqual(nivel, [{ nome: 'Pleno', valor: '100% (8 de 8 vagas)', largura: 100 }]);
  assert.equal(ui.linhas(fs[0]).map(linhaChat)[0].largura, 100);
});

test('resultado antigo guardado no navegador (sem os campos novos) continua abrindo, só com o texto onde falta o gráfico', async () => {
  const antigo = { q: 'antigo', d: { cargo: 'antigo', vagas_analisadas: 5, tecnologias: [{ nome: 'Python', vagas: 3, percentual: 60 }], diferenciais: [], soft_skills: [],
    niveis: { pleno: 2, nao_informado: 3 }, experiencia_mediana_anos: null, avisos: [], metodo: 'dicionario', do_cache: 0, vagas: [] } };
  const ui = await abrir({ historico: [antigo] });                       // o histórico antigo do navegador é importado para uma conversa salva e reexibido a partir do backend
  await esperar(() => ui.d.querySelectorAll('.msg.bot figure').length >= 1);
  const m = [...ui.d.querySelectorAll('.msg.bot')].pop();
  assert.match(m.textContent, /Resultado salvo: pesquisa de/);
  assert.deepEqual(ui.figuras(m).map(ui.titulo), ['Tecnologias mais pedidas']);
  assert.match(m.querySelector('.meta').textContent, /Níveis: Pleno 2 · Não informado 3/);
  const novo = await ui.chat('Graf Pleno100');                                               // e a página continua funcional
  assert.ok(ui.figuras(novo).length >= 2);
});

test('helpers: dados inválidos/extremos não geram larguras inválidas e erros de renderização não quebram a página', async () => {
  const ui = await abrir(), w = ui.w, box = ui.d.createElement('div');
  w.graficoBarras(box, { titulo: 'E', itens: [null, { nome: 'NaN', valor: NaN, texto: '?' }, { nome: 'Alto', valor: 150, texto: '150%' }, { nome: 'Neg', valor: -5, texto: '-5%' },
    { nome: 'Nulo', valor: null, texto: 'sem dados' }, { nome: 'Texto', valor: '50', texto: '50' }, { nome: '', valor: 10, texto: 'x' }] });
  const ls = ui.linhas(box.querySelector('figure')).map(linhaChat);
  assert.deepEqual(ls.map(l => [l.nome, l.largura]), [['NaN', 0], ['Alto', 100], ['Neg', 0], ['Nulo', 0], ['Texto', 0]]);   // itens sem nome são ignorados; nada vira "NaN%"
  assert.equal(w.graficoBarras(ui.d.createElement('div'), { titulo: 'vazio', itens: [] }), null);
  assert.equal(w.graficoBarras(ui.d.createElement('div'), undefined), null);
  assert.equal(w.graficoRosca(ui.d.createElement('div'), { titulo: 'r', total: 0, partes: [{ nome: 'a', valor: 0, texto: '0' }, { nome: 'b', valor: -1, texto: '-1' }] }), null);
  const b2 = ui.d.createElement('div');
  assert.equal(w.graficoBarras(b2, { titulo: 'Falha', get itens() { throw new Error('boom'); } }), null);
  assert.match(b2.textContent, /Não foi possível desenhar o gráfico “Falha”; os valores estão nas listas e tabelas em texto/);
  const b3 = ui.d.createElement('div');
  w.graficoAgrupado(b3, { titulo: 'G', series: [{ rotulo: 'A', cls: 'c-a' }], itens: [{ nome: 'X', valores: [] }] });          // valores faltando: contido
  assert.match(b3.textContent, /Não foi possível desenhar o gráfico “G”/);
  assert.ok(ui.$('chat'));                                                                                                  // a página segue de pé
});

test('Vagas por habilidades: gráfico de lacunas bate com o texto e separa obrigatória/diferencial', async () => {
  const ui = await abrir();
  ui.$('nav-hab').click(); await dormir(60);
  ui.$('h-input').value = 'Python'; ui.$('h-add').click(); await esperar(() => ui.d.querySelectorAll('#h-chips .chip').length === 1);
  ui.$('h-buscar').click(); await esperar(() => /Busca concluída/.test(ui.$('h-status').textContent));
  const box = ui.$('h-resultado'), fig = ui.figuras(box)[0];
  assert.equal(ui.titulo(fig), 'Habilidades a desenvolver, por relevância');
  assert.match(fig.querySelector('.gr-sub').textContent, /% das \d+ vagas avaliadas que citam a habilidade \(não cadastrada no perfil\); escala de 0% a 100%/);
  const chart = ui.linhas(fig).map(linhaChat), texto = [...box.querySelectorAll('.lac')].map(x => x.textContent);
  assert.ok(chart.length > 0 && chart.length === texto.length);
  chart.forEach(c => {
    const t = texto.find(x => x.startsWith(c.nome));
    const m = t.match(/em (\d+) de (\d+) vagas \((\d+)%\)/);
    assert.equal(c.valor, `${m[3]}% (${m[1]} de ${m[2]} vagas)`);        // mesmos números do texto
    assert.ok(Math.abs(c.largura - Number(m[3])) < 0.5);
  });
  const seg = ui.linhas(fig)[0].querySelectorAll('.gr-seg');
  assert.equal(seg.length, 2); assert.ok(Math.abs(parseFloat(seg[0].style.width) + parseFloat(seg[1].style.width) - 100) < 0.01);   // as duas partes preenchem a barra
  assert.deepEqual([...fig.querySelectorAll('.gr-legenda .gr-leg')].map(x => x.textContent), ['obrigatória', 'diferencial']);
  assert.equal(fig.querySelector('details.gr-texto'), null);              // o texto abaixo já é a alternativa
});

test('Evolução por senioridade: rosca de classificação, cobertura por nível e habilidades por nível (iguais à tabela)', async () => {
  const ui = await abrir();
  ui.$('nav-evo').click(); await dormir(60);
  ui.$('e-cargo').value = 'Desenvolvedor React Native Alfa'; ui.$('e-analisar').click();
  await esperar(() => ui.$('e-status').textContent === 'Análise concluída.');
  const box = ui.$('e-resultado'), figs = ui.figuras(box);
  assert.deepEqual(figs.map(ui.titulo), ['Como as vagas coletadas foram classificadas', 'Vagas por nível: coletadas e analisadas', 'Principais habilidades por nível']);
  // --- rosca
  const [rosca, cob, hab] = figs, svg = rosca.querySelector('svg');
  assert.equal(svg.getAttribute('role'), 'img');
  const legenda = [...rosca.querySelectorAll('.gr-legenda li')].map(li => li.textContent);
  assert.deepEqual(legenda, ['Júnior: 12 (40%)', 'Pleno: 10 (33.3%)', 'Sênior: 4 (13.3%)', 'Estágio/trainee: 1 (3.3%)', 'Não classificadas: 2 (6.7%)', 'Fora do contexto da pesquisa: 1 (3.3%)']);
  assert.equal(svg.querySelectorAll('circle').length, 6);
  const arcos = [...svg.querySelectorAll('circle')].map(c => parseFloat(c.getAttribute('stroke-dasharray')));
  assert.ok(Math.abs(arcos.reduce((a, b) => a + b, 0) - 2 * Math.PI * 45) < 0.01);                    // as fatias fecham o círculo
  assert.ok(Math.abs(arcos[0] / (2 * Math.PI * 45) - 12 / 30) < 1e-6);                                // proporção = 12 de 30
  const textos = [...svg.querySelectorAll('text')].map(t => t.textContent);
  assert.deepEqual(textos, ['30', 'vagas']);                                                           // nomes só na legenda: nada sobreposto dentro do gráfico
  assert.match(svg.getAttribute('aria-label'), /Júnior 12 \(40%\); Pleno 10 \(33\.3%\)/);
  // --- cobertura (quantidades em escala comum)
  const g = ui.linhas(cob);
  assert.deepEqual(g.map(x => x.querySelector('.gr-nome').textContent), ['Júnior', 'Pleno', 'Sênior (amostra pequena)']);
  const vals = g.map(x => [...x.querySelectorAll('.gr-row')].map(r => [r.querySelector('.gr-valor').textContent, larg(r.querySelector('.gr-barra'))]));
  assert.deepEqual(vals[0].map(v => v[0]), ['12', '12']); assert.equal(vals[0][0][1], 100);
  assert.ok(Math.abs(vals[1][0][1] - (10 / 12) * 100) < 0.01); assert.ok(Math.abs(vals[2][1][1] - (4 / 12) * 100) < 0.01);
  for (const [n, linha] of [['Júnior', 0], ['Pleno', 1], ['Sênior', 2]]) {                              // iguais à tabela de cobertura
    const t = ui.tabela(box, n);
    assert.deepEqual(vals[linha].map(v => v[0]), [t[1], t[2]]);
  }
  // --- habilidades por nível (mesmos valores da tabela de texto)
  const grupos = ui.linhas(hab);
  assert.equal(grupos.length, 6);
  const ts = grupos.find(x => x.querySelector('.gr-nome').textContent === 'TypeScript');
  const rts = [...ts.querySelectorAll('.gr-row')].map(r => [r.querySelector('.gr-nome').textContent, r.querySelector('.gr-valor').textContent, larg(r.querySelector('.gr-barra'))]);
  assert.deepEqual(rts, [['Júnior', '16.7% (2/12)', 16.7], ['Pleno', '40% (4/10)', 40], ['Sênior', '75% (3/4)', 75]]);
  const linhaTabela = ui.tabela(box, 'TypeScript');
  [1, 2, 3].forEach(i => assert.ok(linhaTabela[i].startsWith(rts[i - 1][1])));
  assert.deepEqual([...hab.querySelectorAll('.gr-legenda .gr-leg')].map(x => x.textContent), ['Júnior', 'Pleno', 'Sênior']);   // a série também é nomeada em cada barra
  // nova análise substitui por completo (nada do resultado anterior sobra)
  ui.$('e-cargo').value = 'Desenvolvedor React Native SoJunior'; ui.$('e-analisar').click();
  await esperar(() => ui.$('e-status').textContent === 'Análise concluída.' && ui.figuras(box).length > 0);
  assert.equal(ui.d.querySelectorAll('#e-resultado figure').length, ui.figuras(box).length);
  assert.ok(!/Alfa/.test(box.textContent));
});

test('Evolução: níveis sem vagas aparecem como "sem dados" (barra vazia), nunca como valores inventados', async () => {
  const ui = await abrir();
  ui.$('nav-evo').click(); await dormir(60);
  ui.$('e-cargo').value = 'Desenvolvedor React Native SoJunior'; ui.$('e-analisar').click();
  await esperar(() => ui.$('e-status').textContent === 'Análise concluída.');
  const [rosca, cob, hab] = ui.figuras(ui.$('e-resultado'));
  assert.ok(![...rosca.querySelectorAll('.gr-legenda li')].some(l => /^Pleno|^Sênior/.test(l.textContent)));        // categorias vazias não entram
  const vc = ui.linhas(cob).map(g => [...g.querySelectorAll('.gr-row')].map(r => [r.querySelector('.gr-valor').textContent, larg(r.querySelector('.gr-barra'))]));
  assert.deepEqual(vc[1], [['0', 0], ['0', 0]]); assert.deepEqual(vc[2], [['0', 0], ['0', 0]]);                       // pleno e sênior: 0 coletadas (valor real), barra vazia
  const g = ui.linhas(hab)[0], rs = [...g.querySelectorAll('.gr-row')].map(r => [r.querySelector('.gr-valor').textContent, larg(r.querySelector('.gr-barra'))]);
  assert.deepEqual(rs.slice(1), [['sem dados', 0], ['sem dados', 0]]);
  assert.match(rs[0][0], /^100% \(12\/12\)$/);
});

test('7: estrutura responsiva — larguras em %, nomes que quebram, rosca que encolhe, regras para telas pequenas', async () => {
  const ui = await abrir();
  const css = [...ui.d.querySelectorAll('style')].map(s => s.textContent).join('\n');
  assert.match(css, /@media\(max-width:560px\)\{[^}]*\.gr-row[^}]*grid-template-columns:1fr auto/s);
  assert.match(css, /\.gr-row>\.gr-nome\{grid-column:1 \/ -1\}/);                    // no celular o nome ocupa a linha toda, sem disputar espaço com a barra
  assert.match(css, /\.gr-nome\{overflow-wrap:anywhere;min-width:0\}/);
  assert.match(css, /\.gr-rosca svg\{[^}]*max-width:100%/);
  assert.match(css, /\.gr\{[^}]*min-width:0/);
  const msg = await ui.chat('Graf Base');
  const comLargura = [...msg.querySelectorAll('[style*="width"]')].filter(e => e.closest('figure'));
  assert.ok(comLargura.length > 20);
  assert.ok(comLargura.every(e => /^[\d.]+%$/.test(e.style.width)));                // nunca px fixos nas barras
  const svg = (await ui.chat('Graf Pleno100'), null);                                  // (a rosca é testada na evolução)
  assert.equal(ui.d.querySelectorAll('canvas, script[src], link[href*="cdn"]').length, 0);   // sem bibliotecas nem CDNs
});

test('8: sem biblioteca externa — nenhum <script src>, CDN ou canvas na página', async () => {
  const html = await (await fetch(base + '/')).text();
  assert.doesNotMatch(html, /<script[^>]+src=/i); assert.doesNotMatch(html, /cdn\.|unpkg|jsdelivr|chart\.js|d3\.|plotly|echarts/i); assert.doesNotMatch(html, /<canvas/i);
});

test('7b: desenhar os gráficos não faz nenhuma chamada além da própria busca', async () => {
  const ui = await abrir();
  const antes = ui.chamadas.length;
  await ui.chat('Graf Base');
  const semHistorico = () => ui.chamadas.slice(antes).filter(c => !c.startsWith('GET /sessoes') && !c.startsWith('POST /sessoes'));
  const esperado = ['POST /chat', 'GET /status'];                                  // a busca + o refresh de cota que o chat já fazia (o histórico local é à parte); os gráficos usam os dados dela
  assert.deepEqual(semHistorico(), esperado);
  const msg = [...ui.d.querySelectorAll('.msg.bot')].pop();
  msg.querySelector('figure button').click(); msg.querySelector('details.gr-texto summary').click();   // expandir/ver texto: continua local
  assert.deepEqual(semHistorico(), esperado);
});
