// Etapa 6, Parte II — gráficos da tela Comparar vagas (página real em jsdom + backend real + provedor SIMULADO, vagas SINTÉTICAS).
// jsdom não faz layout: larguras/estrutura são verificadas no DOM; o visual em navegador real não é coberto.
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
  proc = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env: { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-cg-')), 'g.db') }, stdio: 'ignore' });
  base = `http://127.0.0.1:${porta}`;
  await esperar(async () => { try { return (await fetch(base + '/status')).ok; } catch { return false; } }, 20000);
});
after(() => proc && proc.kill());

const perfil = h => fetch(base + '/habilidades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ habilidades: h }) });
async function abrir() {
  const html = await (await fetch(base + '/')).text();
  const chamadas = [];
  const dom = new JSDOM(html, { url: base + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) { w.confirm = () => true; w.fetch = (u, o = {}) => { chamadas.push({ url: String(u), metodo: o.method || 'GET' }); return fetch(new URL(u, base), o); }; } });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas,
    abrir: async () => { $('nav-cmp').click(); await dormir(40); },
    buscar: async (L, consulta, n) => { $(`m-${L}-consulta`).value = consulta; $(`m-${L}-buscar`).click(); await esperar(() => d.querySelectorAll(`#m-${L}-lista .opcao`).length === n); },
    escolher: (L, i) => d.querySelectorAll(`#m-${L}-lista .opcao`)[i].querySelector('button').click(),
    manual: (L, t, desc) => { $(`m-${L}-modo`).value = 'manual'; $(`m-${L}-modo`).dispatchEvent(new w.Event('change')); $(`m-${L}-titulo`).value = t; $(`m-${L}-descricao`).value = desc; $(`m-${L}-usar`).click(); },
    comparar: async () => { $('m-comparar').click(); await esperar(() => !/Comparação em andamento/.test($('m-status').textContent)); },
    par: async (qa, ia, qb, ib, na = 4, nb = 4) => { await ui.buscar('a', qa, na); await ui.buscar('b', qb, nb); ui.escolher('a', ia); ui.escolher('b', ib); await ui.comparar(); },
    figs: () => [...d.querySelectorAll('#m-resultado figure.gr')],
    tit: f => f.querySelector('figcaption').textContent,
    linhas: f => [...f.querySelectorAll('.gr-lista > [role=listitem]')],
    resumoLinha: r => ({ nome: r.querySelector('.gr-nome').textContent, valor: r.querySelector('.gr-valor').textContent, largura: parseFloat(r.querySelector('.gr-barra').style.width), seg: [...r.querySelectorAll('.gr-seg')].map(s => s.className.replace('gr-seg ', '')) }),
    fig: t => ui.figs().find(f => ui.tit(f) === t),
    detalhes: () => Object.fromEntries([...d.querySelectorAll('#m-resultado figure.gr ~ details, #m-resultado .card > div > details')].map(x => [x.querySelector('summary').textContent, [...x.querySelectorAll('li')].map(l => l.textContent)])),
  };
  return ui;
}
const T_HAB = 'Habilidades identificadas: em comum e específicas', T_REQ = 'Requisitos por tipo em cada vaga', T_COMP = 'Compatibilidade estimada com o seu perfil', T_EXP = 'Experiência mínima citada (anos)';
const perto = (x, y) => Math.abs(x - y) < 0.01;

test('19/20/21/30: comuns e específicas — contagens, escala do total, cores de identidade e listas completas', async () => {
  await perfil([]);
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);                         // cb1 × cb2
  const f = ui.fig(T_HAB);
  assert.ok(f); assert.match(f.querySelector('.gr-sub').textContent, /7 habilidades distintas no total \(vaga A: 4; vaga B: 4\)\. Cada habilidade está em uma só categoria/);
  const [comum, soA, soB] = ui.linhas(f).map(ui.resumoLinha);
  assert.deepEqual([comum.nome, comum.valor, soA.valor, soB.valor], ['Identificadas nas duas vagas', '1 habilidade(s)', '3 habilidade(s)', '3 habilidade(s)']);
  assert.ok(perto(comum.largura, 100 / 7) && perto(soA.largura, 300 / 7) && perto(soB.largura, 300 / 7));   // mesma escala (total de habilidades distintas)
  assert.deepEqual([comum.seg, soA.seg, soB.seg], [['c-comum'], ['c-a'], ['c-b']]);                             // verde = comum, azul = A, amarelo = B
  assert.equal(soA.nome, 'Identificadas só na vaga A'); assert.equal(soB.nome, 'Identificadas só na vaga B');   // sem ressalva: as duas análises são completas
  const det = {}; ui.d.querySelectorAll('#m-resultado details').forEach(x => { const s = x.querySelector('summary'); if (s) det[s.textContent] = [...x.querySelectorAll('li')].map(l => l.textContent); });
  assert.deepEqual(det['Habilidades em comum (1)'], ['Python']);
  assert.deepEqual(det['Identificadas só na vaga A (3)'], ['PostgreSQL (obrigatória)', 'Docker (obrigatória)', 'Apache Kafka (desejável)']);
  assert.deepEqual(det['Identificadas só na vaga B (3)'], ['AWS (obrigatória)', 'Kubernetes (obrigatória)', 'Terraform (desejável)']);
  assert.ok('Correspondência não determinada: relacionadas, mas distintas (0)' in det);
});

test('11 (texto × gráfico): as contagens do gráfico são o tamanho das listas completas e das seções de texto', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);
  const vals = ui.linhas(ui.fig(T_HAB)).map(r => parseInt(ui.resumoLinha(r).valor));
  const lis = t => { const p = [...ui.d.querySelectorAll('#m-resultado p.rotulo')].find(x => x.textContent.startsWith(t)); return p.nextElementSibling.querySelectorAll('li, tbody tr').length; };
  assert.deepEqual(vals, [lis('Habilidades comuns'), lis('Identificadas somente na vaga A'), lis('Identificadas somente na vaga B')]);
  const sinteseA = [...ui.d.querySelectorAll('#m-resultado li')].find(l => l.textContent.startsWith('Vaga A: '));
  assert.match(sinteseA.textContent, /PostgreSQL.*Docker.*Kafka/);
});

test('23: obrigatórios e diferenciais por vaga em barras agrupadas, iguais às listas de cada vaga', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);
  const f = ui.fig(T_REQ);
  assert.match(f.querySelector('.gr-sub').textContent, /não mede dificuldade, qualidade nem senioridade/);
  const grupos = ui.linhas(f).map(g => ({ nome: g.querySelector(':scope > .gr-nome').textContent, linhas: [...g.querySelectorAll('.gr-row')].map(r => [r.querySelector('.gr-nome').textContent, r.querySelector('.gr-valor').textContent, parseFloat(r.querySelector('.gr-barra').style.width), r.querySelector('.gr-barra').className.replace('gr-barra ', '')]) }));
  assert.deepEqual(grupos.map(g => g.nome), ['Requisitos obrigatórios', 'Diferenciais desejáveis']);            // sem grupo "sem classificação": nada a mostrar
  assert.deepEqual(grupos[0].linhas.map(l => l.slice(0, 2)), [['Vaga A', '3 habilidade(s)'], ['Vaga B', '3 habilidade(s)']]);
  assert.deepEqual(grupos[1].linhas.map(l => l.slice(0, 2)), [['Vaga A', '1 habilidade(s)'], ['Vaga B', '1 habilidade(s)']]);
  assert.deepEqual([grupos[0].linhas[0][2], grupos[1].linhas[0][2]].map(x => Math.round(x)), [100, 33]);          // mesma escala (máximo = 3)
  assert.deepEqual(grupos[0].linhas.map(l => l[3]), ['c-a', 'c-b']);                                                 // A azul, B amarelo, como nos outros gráficos
  assert.deepEqual([...f.querySelectorAll('.gr-legenda .gr-leg')].map(x => x.textContent), ['Vaga A', 'Vaga B']);
  const chips = (card, rot) => { const p = [...card.querySelectorAll('p.rotulo')].find(x => x.textContent === rot); return p ? p.nextElementSibling.children.length : 0; };
  const [a, b] = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.deepEqual([chips(a, 'Requisitos obrigatórios'), chips(a, 'Diferenciais desejáveis'), chips(b, 'Requisitos obrigatórios'), chips(b, 'Diferenciais desejáveis')], [3, 1, 3, 1]);
});

test('24/29: compatibilidade das duas vagas — mesma nota dos cartões, escala 0–100 e cores de A e B', async () => {
  await perfil(['Python', 'Docker']);
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);
  const f = ui.fig(T_COMP);
  assert.match(f.querySelector('.gr-sub').textContent, /mesma fórmula do JobInsight.*escala de 0% a 100%.*Não é chance de contratação e não indica qual vaga é melhor/);
  const [a, b] = ui.linhas(f).map(ui.resumoLinha);
  assert.deepEqual([a.nome, a.valor, b.nome, b.valor], ['Vaga A', '≈ 57%', 'Vaga B', '≈ 29%']);
  assert.ok(perto(a.largura, 57.1) && perto(b.largura, 28.6));                             // barra = valor que o backend devolveu (57,1 e 28,6), não recalculado aqui
  assert.deepEqual([a.seg, b.seg], [['c-a'], ['c-b']]);
  assert.deepEqual([...f.querySelectorAll('details.gr-texto li')].map(l => l.textContent), ['Vaga A: ≈ 57% · 2/3 obrigatórios · 0/1 diferenciais', 'Vaga B: ≈ 29% · 1/3 obrigatórios · 0/1 diferenciais']);
  const badges = [...ui.d.querySelectorAll('#m-resultado .vaga .badge')].map(x => x.textContent);
  assert.match(badges[0], /≈ 57% dos requisitos/); assert.match(badges[1], /≈ 29% dos requisitos/);       // o mesmo número do texto
  assert.doesNotMatch(ui.$('m-resultado').textContent, /vencedor|melhor vaga|recomendamos/i);
  await perfil([]);
});

test('25: só uma pontuação válida — mostra a disponível, explica a outra (que não é zero) e omite o resto', async () => {
  await perfil(['Python', 'Docker']);
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 3);                                      // B = vaga sem descrição
  assert.deepEqual(ui.figs().map(ui.tit), [T_COMP]);
  const linhas = ui.linhas(ui.fig(T_COMP)).map(ui.resumoLinha);
  assert.equal(linhas.length, 1); assert.deepEqual([linhas[0].nome, linhas[0].valor], ['Vaga A', '≈ 57%']);
  const t = ui.$('m-resultado').textContent;
  assert.match(t, /Vaga B sem pontuação \(não é zero\): Sem análise de requisitos para esta vaga\. Não há comparação quantitativa entre as duas\./);
  assert.match(t, /Gráficos de habilidades e de requisitos omitidos: A comparação de requisitos exige a análise das duas vagas/);
  assert.match(t, /Resultado parcial da comparação/);
  await perfil([]);
});

test('26: sem perfil a comparação segue, sem gráfico de compatibilidade e sem notas inventadas', async () => {
  await perfil([]);
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);
  assert.deepEqual(ui.figs().map(ui.tit), [T_HAB, T_REQ]);
  assert.match(ui.$('m-resultado').textContent, /Gráfico de compatibilidade omitido: vaga A: Nenhuma habilidade cadastrada no perfil; vaga B: Nenhuma habilidade cadastrada no perfil\./);
  assert.equal(ui.d.querySelectorAll('#m-resultado .vaga')[0].querySelector('.badge.nd').textContent.startsWith('Sem pontuação: Nenhuma habilidade cadastrada no perfil'), true);   // a nota ausente é dita, não zerada
});

test('27: contagem zero é desenhada como zero; dado desconhecido não é desenhado; sem nenhuma habilidade o gráfico é omitido', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 2, 'Cmp Frontend', 0, 4, 2);                               // cb3 (sem diferenciais) × cf1
  const r = ui.linhas(ui.fig(T_HAB)).map(ui.resumoLinha);
  assert.deepEqual([r[0].valor, r[0].largura], ['0 habilidade(s)', 0]);                  // nenhuma em comum: zero real
  assert.deepEqual(r.slice(1).map(x => x.valor), ['2 habilidade(s)', '4 habilidade(s)']);
  const grupo = ui.linhas(ui.fig(T_REQ))[1];
  assert.equal(grupo.querySelector(':scope > .gr-nome').textContent, 'Diferenciais desejáveis');
  assert.deepEqual([...grupo.querySelectorAll('.gr-row')].map(x => x.querySelector('.gr-valor').textContent), ['0 habilidade(s)', '1 habilidade(s)']);
  // duas vagas sem nenhuma tecnologia: nada a desenhar
  const ui2 = await abrir(); await ui2.abrir();
  const sem = 'Procuramos pessoa dedicada, comunicativa e muito organizada para o nosso time. '.repeat(6);
  ui2.manual('a', 'Vaga sem tecnologia A', sem); ui2.manual('b', 'Vaga sem tecnologia B', sem + ' Outra vaga.');
  await ui2.comparar();
  assert.equal(ui2.figs().filter(f => [T_HAB, T_REQ].includes(ui2.tit(f))).length, 0);
  assert.match(ui2.$('m-resultado').textContent, /Nenhuma habilidade técnica foi identificada nas duas vagas: o gráfico de habilidades foi omitido\./);
});

test('22: descrição incompleta — o gráfico sinaliza que "só em uma vaga" pode ser omissão e nunca afirma exclusividade', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Curta', 0, 'Cmp Curta', 1, 2, 2);                                    // cc1 (descrição curta) × cc2
  const [, soA, soB] = ui.linhas(ui.fig(T_HAB)).map(ui.resumoLinha);
  assert.equal(soB.nome, 'Identificadas só na vaga B (a análise da A é limitada: pode ser omissão)');
  assert.equal(soA.nome, 'Identificadas só na vaga A');                                  // a análise de B é completa
  const t = ui.$('m-resultado').textContent;
  assert.match(t, /Atenção: a análise da\(s\) vaga\(s\) A é limitada \(descrição curta, trecho parcial, IA indisponível ou sem tecnologias\)/);
  assert.match(t, /Descrição curta \(\d+ caracteres\): a análise pode estar incompleta/);
  assert.doesNotMatch(t, /exclusiv/i);
});

test('23b: habilidades sem marcação de obrigatória/desejável ficam num grupo à parte (não viram obrigatórias)', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp SemMarcador', 0, 'Cmp SemMarcador', 1, 2, 2);
  const grupos = ui.linhas(ui.fig(T_REQ)).map(g => [g.querySelector(':scope > .gr-nome').textContent, [...g.querySelectorAll('.gr-row .gr-valor')].map(x => x.textContent)]);
  assert.deepEqual(grupos, [['Requisitos obrigatórios', ['0 habilidade(s)', '2 habilidade(s)']], ['Diferenciais desejáveis', ['0 habilidade(s)', '0 habilidade(s)']], ['Citadas sem classificação', ['2 habilidade(s)', '0 habilidade(s)']]]);
  assert.match(ui.$('m-resultado').textContent, /"Sem classificação": habilidades citadas sem marcação de obrigatória ou desejável no anúncio; não foram contadas como obrigatórias nem como diferenciais/);
});

test('9: experiência mínima em barras só quando as duas vagas informam o valor', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Anos', 0, 'Cmp Anos', 1, 2, 2);
  const [a, b] = ui.linhas(ui.fig(T_EXP)).map(ui.resumoLinha);
  assert.deepEqual([a.valor, b.valor], ['3 ano(s)', '5 ano(s)']); assert.ok(perto(a.largura, 60) && perto(b.largura, 100));
  assert.deepEqual([a.seg, b.seg], [['c-a'], ['c-b']]);
  const ui2 = await abrir(); await ui2.abrir();
  await ui2.par('Cmp Backend', 0, 'Cmp Frontend', 0, 4, 2);
  assert.equal(ui2.fig(T_EXP), undefined);
  assert.match(ui2.$('m-resultado').textContent, /Gráfico de experiência omitido: Experiência mínima não identificada na\(s\) vaga\(s\) A e B: não há como comparar\./);   // ausente != zero
});

test('28: nova comparação substitui os gráficos por completo, sem resíduos da anterior', async () => {
  await perfil(['Python', 'Docker']);
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 0, 'Cmp Backend', 1);
  assert.deepEqual(ui.linhas(ui.fig(T_HAB)).map(r => ui.resumoLinha(r).valor), ['1 habilidade(s)', '3 habilidade(s)', '3 habilidade(s)']);
  assert.ok(ui.$('m-resultado').textContent.includes('AWS'));
  await ui.buscar('b', 'Cmp Frontend', 2); ui.escolher('b', 0);                         // troca só a vaga B
  assert.equal(ui.$('m-resultado').hidden, true); assert.equal(ui.d.querySelectorAll('#m-resultado figure').length, 0);
  await ui.comparar();
  assert.deepEqual(ui.linhas(ui.fig(T_HAB)).map(r => ui.resumoLinha(r).valor), ['0 habilidade(s)', '4 habilidade(s)', '4 habilidade(s)']);
  assert.ok(!ui.$('m-resultado').textContent.includes('AWS'));                            // nada da comparação anterior
  const comp = ui.linhas(ui.fig(T_COMP)).map(ui.resumoLinha);
  assert.deepEqual(comp.map(x => [x.nome, x.valor]), [['Vaga A', '≈ 57%'], ['Vaga B', '≈ 0%']]);   // cf1 não cobre nada do perfil: 0% é um valor real, calculado
  assert.equal(ui.d.querySelectorAll('#m-resultado figure.gr').length, ui.figs().length);
  await perfil([]);
});

test('36: desenhar os gráficos da comparação não faz nenhuma chamada além da própria comparação', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend', 4); await ui.buscar('b', 'Cmp Backend', 4); ui.escolher('a', 0); ui.escolher('b', 1);
  const antes = ui.chamadas.length;
  await ui.comparar();
  assert.deepEqual(ui.chamadas.slice(antes).filter(c => !c.url.startsWith('/sessoes')).map(c => `${c.metodo} ${c.url}`), ['POST /comparar']);   // fora o histórico local, só a comparação
});

test('segurança: dados externos nos gráficos vão como texto e a página não depende de biblioteca externa', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.par('Cmp Backend', 2, 'Cmp Frontend', 0, 4, 2);                               // cb3 tem título/empresa com HTML
  assert.equal(ui.d.querySelectorAll('#m-resultado figure img, #m-resultado figure script, #m-resultado figure b').length, 0);
  await dormir(80); assert.equal(ui.w.__xss, undefined);
  assert.equal(ui.d.querySelectorAll('script[src], canvas').length, 0);
});
