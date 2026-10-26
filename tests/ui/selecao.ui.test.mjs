// Etapa 6, Parte I — botões "Usar como vaga A/B" da tela Vagas por habilidades, estado A/B e identificadores (vagas SINTÉTICAS).
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
  proc = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env: { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-sel-')), 's.db') }, stdio: 'ignore' });
  base = `http://127.0.0.1:${porta}`;
  await esperar(async () => { try { return (await fetch(base + '/status')).ok; } catch { return false; } }, 20000);
});
after(() => proc && proc.kill());

const salvar = async (habilidades, areas = []) => {
  await fetch(base + '/habilidades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ habilidades }) });
  await fetch(base + '/perfil', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome: '', areas }) });
};
async function abrir({ ponte } = {}) {
  const html = await (await fetch(base + '/')).text();
  const chamadas = [], hab = [];
  const dom = new JSDOM(html, { url: base + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) {
      w.confirm = () => true;
      w.fetch = async (u, o = {}) => {
        chamadas.push({ url: String(u), corpo: o.body ? JSON.parse(o.body) : null });
        const original = () => fetch(new URL(u, base), o);
        const r = await (ponte ? ponte(String(u), o, original) : original());
        if (String(u) === '/busca-habilidades' && r.ok) hab.push(await r.clone().json());
        return r;
      };
    } });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas, hab,
    cards: () => [...d.querySelectorAll('#h-resultado .vaga')],
    botao: (i, L) => ui.cards()[i].querySelector(`button[data-lado=${L}]`),
    habilitar: async (habs, { area, paginas } = {}) => {
      $('nav-hab').click(); await dormir(60);
      if (area) { await esperar(() => [...$('h-area').options].some(o => o.value === area)); $('h-area').value = area; $('h-area').dispatchEvent(new w.Event('change')); }
      if (paginas) $('h-paginas').value = String(paginas);
      for (const h of habs) { const n = d.querySelectorAll('#h-chips .chip').length; $('h-input').value = h; $('h-add').click(); await esperar(() => d.querySelectorAll('#h-chips .chip').length === n + 1); }
      $('h-buscar').click(); await esperar(() => /Busca concluída/.test($('h-status').textContent));
    },
    maisUma: async () => { const n = hab.length; $('h-mais').click(); await esperar(() => hab.length === n + 1 && !/Carregando mais/.test($('h-status').textContent)); },
    barra: () => $('h-selecao'),
    comparar: async () => { $('m-comparar').click(); await esperar(() => !/Comparação em andamento/.test($('m-status').textContent)); },
    posts: () => chamadas.filter(c => c.url === '/comparar'),
    manualB: (titulo = 'Vaga manual B') => {
      $('m-b-modo').value = 'manual'; $('m-b-modo').dispatchEvent(new w.Event('change'));
      $('m-b-titulo').value = titulo; $('m-b-descricao').value = 'Requisitos: Python, Go. ' + 'Contexto da vaga com informações de apoio. '.repeat(10); $('m-b-usar').click();
    },
  };
  return ui;
}
const titulo = c => c.querySelector('h3').textContent;
const esc = t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const tv = (ui, i) => ui.hab[0].vagas[i].titulo;   // título como veio do backend (o cartão acrescenta aviso quando não há link seguro)

test('1/2/6: clicar em A e em B muda o botão, mostra a seleção e mantém A e B independentes', async () => {
  await salvar([]);
  const ui = await abrir(); await ui.habilitar(['Python']);
  assert.equal(ui.barra().hidden, true);                                   // nada selecionado: sem barra
  const A = ui.botao(0, 'a'), B0 = ui.botao(0, 'b');
  assert.equal(A.textContent, 'Usar como vaga A'); assert.equal(A.getAttribute('aria-pressed'), 'false');
  A.click();
  assert.equal(A.textContent, 'Selecionada como vaga A'); assert.equal(A.getAttribute('aria-pressed'), 'true'); assert.ok(A.classList.contains('ativo'));
  assert.equal(B0.textContent, 'Usar como vaga B');                        // B não foi tocado
  assert.equal(ui.barra().hidden, false);
  assert.match(ui.barra().textContent, new RegExp(`Vaga A.*${esc(tv(ui, 0))}`, 's'));
  assert.match(ui.barra().textContent, /Vaga B.*ainda não selecionada/s); assert.match(ui.barra().textContent, /Somente a vaga A selecionada/);
  assert.match(ui.$('h-status').textContent, /Vaga A definida: “.*”\. Veja “Vagas para comparar”/);
  ui.botao(1, 'b').click();
  assert.equal(ui.botao(1, 'b').textContent, 'Selecionada como vaga B'); assert.equal(A.textContent, 'Selecionada como vaga A');   // B não substituiu A
  assert.match(ui.barra().textContent, /Duas vagas selecionadas: pronto para comparar/);
});

test('3: selecionar outra vaga como A substitui a anterior e atualiza tudo na hora', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  ui.botao(0, 'a').click(); ui.botao(1, 'b').click(); ui.botao(2, 'a').click();
  assert.equal(ui.botao(0, 'a').textContent, 'Usar como vaga A'); assert.ok(!ui.botao(0, 'a').classList.contains('ativo'));   // a anterior volta ao normal
  assert.equal(ui.botao(2, 'a').textContent, 'Selecionada como vaga A');
  assert.match(ui.barra().textContent, new RegExp('Vaga A.*' + esc(tv(ui, 2)), 's'));
  assert.equal(ui.botao(1, 'b').textContent, 'Selecionada como vaga B');                      // B preservada
  assert.equal(ui.d.querySelectorAll('#h-resultado button.ativo[data-lado=a]').length, 1);   // só uma vaga A
  await dormir(10);
  ui.$('nav-cmp').click(); await dormir(30);
  assert.match(ui.$('m-a-sel').textContent, new RegExp(esc(tv(ui, 2))));
});

test('4: remover só uma vaga (pela barra ou pela tela Comparar) mantém a outra e não habilita comparar', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  ui.botao(0, 'a').click(); ui.botao(1, 'b').click();
  ui.barra().querySelector('button[aria-label="Remover a vaga A"]').click();
  assert.equal(ui.botao(0, 'a').textContent, 'Usar como vaga A'); assert.equal(ui.botao(1, 'b').textContent, 'Selecionada como vaga B');
  assert.match(ui.barra().textContent, /Vaga A.*ainda não selecionada/s); assert.match(ui.barra().textContent, /Somente a vaga B selecionada\. Falta escolher a vaga A/);
  ui.$('nav-cmp').click(); await dormir(30);
  assert.match(ui.$('m-a-sel').textContent, /Vaga A ainda não selecionada/); assert.match(ui.$('m-b-sel').textContent, /Vaga B selecionada/);
  assert.match(ui.$('m-estado').textContent, /Somente a vaga B selecionada/); assert.equal(ui.$('m-comparar').disabled, true);
  ui.$('m-b-sel').querySelector('button').click();                                         // remover B pela tela Comparar
  assert.match(ui.$('m-estado').textContent, /Nenhuma vaga selecionada/);
  ui.$('nav-hab').click(); await dormir(60);
  assert.equal(ui.barra().hidden, true); assert.equal(ui.botao(1, 'b').textContent, 'Usar como vaga B');   // os botões acompanham o estado real
  assert.equal(ui.posts().length, 0);                                                      // nada foi enviado como se estivesse preenchido
});

test('5: a seleção permanece ao navegar entre telas', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  ui.botao(0, 'a').click(); ui.botao(2, 'b').click();
  ui.$('nav-cmp').click(); await dormir(30);
  assert.match(ui.$('m-a-sel').textContent, /Vaga A selecionada/); assert.match(ui.$('m-b-sel').textContent, /Vaga B selecionada/); assert.equal(ui.$('m-comparar').disabled, false);
  ui.$('nav-perfil').click(); await dormir(60); ui.$('nav-vagas').click(); ui.$('nav-hab').click(); await dormir(60);
  assert.equal(ui.botao(0, 'a').textContent, 'Selecionada como vaga A'); assert.equal(ui.botao(2, 'b').textContent, 'Selecionada como vaga B');
  assert.equal(ui.barra().hidden, false);
});

test('7: cliques repetidos no mesmo botão são idempotentes', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  for (let i = 0; i < 4; i++) ui.botao(0, 'a').click();
  assert.equal(ui.botao(0, 'a').textContent, 'Selecionada como vaga A');
  assert.equal(ui.d.querySelectorAll('#h-selecao .sel-linha').length, 2);
  assert.match(ui.barra().textContent, /Somente a vaga A selecionada/);
  assert.equal(ui.d.querySelectorAll('#h-resultado button.ativo').length, 1);
});

test('10: o mesmo anúncio nas duas posições é barrado, em qualquer tela; anúncios diferentes liberam', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  ui.botao(0, 'a').click(); ui.botao(0, 'b').click();
  assert.match(ui.barra().textContent, /As duas seleções são o mesmo anúncio\. Escolha duas vagas diferentes/);
  ui.$('nav-cmp').click(); await dormir(30);
  assert.match(ui.$('m-estado').textContent, /mesmo anúncio/); assert.equal(ui.$('m-comparar').disabled, true);
  ui.$('nav-hab').click(); await dormir(60);
  ui.botao(1, 'b').click();
  assert.match(ui.barra().textContent, /Duas vagas selecionadas: pronto para comparar/);
});

test('11/12/13/18: o POST de comparação leva as referências corretas e o ID original, e o resultado volta ao lado certo', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  const v0 = ui.hab[0].vagas[0], v1 = ui.hab[0].vagas[1];
  assert.equal(titulo(ui.cards()[0]).replace(/ \(sem link.*/, ''), v0.titulo.replace(/ \(sem link.*/, ''));
  ui.botao(0, 'a').click(); ui.botao(1, 'b').click();
  ui.$('nav-cmp').click(); await dormir(30);
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.');
  const { a, b } = ui.posts()[0].corpo;
  assert.deepEqual(Object.keys(a), ['tipo', 'consulta', 'pais', 'paginas', 'id']); assert.deepEqual(Object.keys(b), ['tipo', 'consulta', 'pais', 'paginas', 'id']);
  assert.deepEqual(a, { tipo: 'busca', ...v0.ref, id: v0.id }); assert.deepEqual(b, { tipo: 'busca', ...v1.ref, id: v1.id });
  assert.notEqual(a.id, b.id);
  const cards = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.match(cards[0].querySelector('.tag').textContent, /Vaga A/); assert.ok(cards[0].textContent.includes(v0.titulo)); assert.ok(cards[1].textContent.includes(v1.titulo));
  assert.match(ui.$('m-resultado').textContent, /Vagas vindas do cache.*nenhuma requisição nova/);   // reaproveitou a busca já feita
});

test('6/8: a seleção sobrevive a uma nova pesquisa e continua válida (não depende da lista atual)', async () => {
  const ui = await abrir(); await ui.habilitar(['Python']);
  const antes = ui.hab[0].vagas[0];
  ui.botao(0, 'a').click(); ui.botao(1, 'b').click();
  ui.$('h-chips').querySelector('button[aria-label="Remover Python"]').click();           // troca a pesquisa
  ui.$('h-input').value = 'Rust'; ui.$('h-add').click(); await esperar(() => ui.d.querySelectorAll('#h-chips .chip').length === 1);
  ui.$('h-buscar').click(); await esperar(() => ui.hab.length === 2 && /Busca concluída/.test(ui.$('h-status').textContent));
  assert.equal(ui.barra().hidden, false); assert.match(ui.barra().textContent, /Duas vagas selecionadas/);
  ui.$('nav-cmp').click(); await dormir(30);
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.');
  assert.deepEqual(ui.posts()[0].corpo.a, { tipo: 'busca', ...antes.ref, id: antes.id });   // continua apontando para a busca original
});

test('14/15: ID longo legítimo (459 caracteres) é preservado até o backend; ID acima do limite é barrado com mensagem clara', async () => {
  const ui = await abrir(); await ui.habilitar(['IdLongo']);
  const longo = ui.hab[0].vagas.find(v => v.titulo === 'Dev Python IdLongo'), enorme = ui.hab[0].vagas.find(v => v.titulo === 'Dev Go IdEnorme');
  assert.equal(longo.id.length, 459); assert.equal(enorme.id.length, 1203);
  const i = ui.cards().findIndex(c => titulo(c).startsWith('Dev Python IdLongo')), j = ui.cards().findIndex(c => titulo(c).startsWith('Dev Go IdEnorme'));
  ui.botao(i, 'a').click();
  ui.$('nav-cmp').click(); await dormir(30);
  ui.manualB();
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.');
  assert.equal(ui.posts()[0].corpo.a.id, longo.id);                                      // idêntico ao devolvido pelo provedor, sem corte nem recodificação
  assert.match([...ui.d.querySelectorAll('#m-resultado .vaga')][0].textContent, /Dev Python IdLongo/);
  ui.$('nav-hab').click(); await dormir(60);
  ui.botao(j, 'a').click();                                                              // ID de 1203 caracteres: acima do limite documentado (1024)
  ui.$('nav-cmp').click(); await dormir(30);
  assert.match(ui.$('m-estado').textContent, /Seleção inválida para comparar \(vaga A: o identificador do anúncio tem 1203 caracteres \(limite 1024\)\)/);
  assert.equal(ui.$('m-comparar').disabled, true);
  assert.match(ui.$('m-b-sel').textContent, /Vaga manual B/);                            // a outra seleção válida foi preservada
  assert.equal(ui.posts().length, 1);                                                    // nada inválido foi enviado
});

test('regressão do defeito: busca com consulta longa e 4 páginas gera seleção que o backend aceita', async () => {
  await salvar([], ['Desenvolvimento Mobile Multiplataforma']);
  const ui = await abrir();
  await ui.habilitar(['Habilidade Muito Longa Numero Um', 'Habilidade Muito Longa Numero Dois', 'Paginas'], { area: 'Desenvolvimento Mobile Multiplataforma', paginas: 1 });
  await ui.maisUma(); await ui.maisUma(); await ui.maisUma();
  const r = ui.hab.at(-1);
  assert.equal(r.paginas, 4); assert.ok(r.vagas[0].ref.consulta.length > 80, 'consulta de ' + r.vagas[0].ref.consulta.length);   // antes: 422 (limites 80 caracteres / 3 páginas)
  ui.botao(0, 'a').click();
  ui.$('nav-cmp').click(); await dormir(30);
  ui.manualB();
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.', ui.$('m-status').textContent);
  assert.equal(ui.posts()[0].corpo.a.paginas, 4); assert.equal(ui.posts()[0].corpo.a.consulta, r.vagas[0].ref.consulta);
  await salvar([]);
});

test('17: erro na comparação não apaga as seleções válidas e permite tentar de novo', async () => {
  let quebrar = true;
  const ui = await abrir({ ponte: (u, o, orig) => (quebrar && u === '/comparar' ? Promise.reject(new TypeError('x')) : orig()) });
  await ui.habilitar(['Python']);
  ui.botao(0, 'a').click(); ui.botao(1, 'b').click();
  ui.$('nav-cmp').click(); await dormir(30);
  await ui.comparar();
  assert.match(ui.$('m-status').textContent, /falha de conexão/); assert.ok(ui.$('m-status').classList.contains('erro'));
  assert.match(ui.$('m-a-sel').textContent, /Vaga A selecionada/); assert.match(ui.$('m-b-sel').textContent, /Vaga B selecionada/);
  assert.equal(ui.$('m-comparar').disabled, false); assert.equal(ui.botao(0, 'a').textContent, 'Selecionada como vaga A');
  quebrar = false;
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.');
});

test('16/A5: anúncios com o mesmo título e a mesma empresa são distintos pelo ID; o mesmo ID dos dois lados é barrado', async () => {
  const ui = await abrir(); ui.$('nav-cmp').click(); await dormir(30);
  for (const L of ['a', 'b']) { ui.$(`m-${L}-consulta`).value = 'Cmp Frontend'; ui.$(`m-${L}-buscar`).click(); await esperar(() => ui.d.querySelectorAll(`#m-${L}-lista .opcao`).length === 2); }
  const op = L => [...ui.d.querySelectorAll(`#m-${L}-lista .opcao`)];
  assert.equal(op('a')[0].querySelector('strong').textContent, op('a')[1].querySelector('strong').textContent);   // títulos iguais
  op('a')[0].querySelector('button').click(); op('b')[0].querySelector('button').click();
  assert.match(ui.$('m-estado').textContent, /mesmo anúncio/); assert.equal(ui.$('m-comparar').disabled, true);
  op('b')[1].querySelector('button').click();
  assert.match(ui.$('m-estado').textContent, /pronto para comparar/);
  await ui.comparar();
  assert.equal(ui.$('m-status').textContent, 'Comparação concluída.');
  const [a, b] = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.match(a.textContent, /React/); assert.doesNotMatch(a.textContent, /Angular/); assert.match(b.textContent, /Angular/); assert.doesNotMatch(b.textContent, /React/);
});

test('identidade usa provedor + ID e os limites do frontend espelham os do backend', async () => {
  const html = await (await fetch(base + '/')).text();
  assert.match(html, /const chaveBusca = \(provedor, id\) => 'busca\|' \+ \(provedor \|\| ''\) \+ '\|' \+ id;/);
  const m = html.match(/const LIM = (\{[^}]*\});/); const lim = Function('return ' + m[1])();
  assert.deepEqual(lim, { titulo: 200, empresa: 120, link: 500, descricao: 8000, id: 1024, consulta: 184, paginas: 5 });
});
