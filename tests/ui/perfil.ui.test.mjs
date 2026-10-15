// Testes de interface do Perfil: a página real (index.html) roda no jsdom e conversa com um uvicorn real
// (SQLite temporário). Complementam os testes pytest; não dependem de chaves de APIs externas.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
import { JSDOM } from 'jsdom';

const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
let proc, base, dbPath;

const portaLivre = () => new Promise(res => {
  const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});
const dormir = ms => new Promise(r => setTimeout(r, ms));
async function esperar(cond, ms = 4000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await cond()) return; await dormir(15); }
  throw new Error('timeout esperando condição: ' + cond.toString());
}

before(async () => {
  dbPath = join(mkdtempSync(join(tmpdir(), 'jobinsight-ui-')), 'ui.db');
  const porta = await portaLivre();
  base = `http://127.0.0.1:${porta}`;
  const env = { ...process.env, CACHE_DB: dbPath };
  for (const k of ['OPENWEBNINJA_API_KEY', 'CHAVE_OPENROUTER', 'RAPIDAPI_KEY']) delete env[k];
  proc = spawn('python3', ['-m', 'uvicorn', 'app.main:app', '--port', String(porta), '--log-level', 'warning'], { cwd: RAIZ, env, stdio: 'ignore' });
  await esperar(async () => { try { return (await fetch(base + '/status')).ok; } catch { return false; } }, 15000);
});
after(() => proc && proc.kill());

// Abre a página. `ponte(url, opts, original)` permite simular falhas de rede/servidor.
async function abrir(ponte) {
  const html = await (await fetch(base + '/')).text();
  const chamadas = [];
  const dom = new JSDOM(html, {
    url: base + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) {
      w.confirm = () => true;
      w.fetch = (u, o = {}) => {
        const original = () => fetch(new URL(u, base), o);
        chamadas.push({ url: String(u), metodo: o.method || 'GET' });
        return ponte ? ponte(String(u), o, original) : original();
      };
    },
  });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas, dom,
    abrirPerfil: async () => { $('nav-perfil').click(); await esperar(() => !$('p-corpo').hidden || $('p-status').classList.contains('erro')); },
    chips: () => [...d.querySelectorAll('#p-chips .chip > span')].map(s => s.textContent),
    status: () => $('p-status').textContent,
    digitarArea: t => { $('p-area').value = t; },
    adicionar: t => { $('p-area').value = t; $('p-add').click(); },
    salvar: async () => { $('p-salvar').click(); await esperar(() => !/Salvando/.test($('p-status').textContent)); },
  };
  await dormir(30);
  return ui;
}
const limpar = async () => {
  const r = await fetch(base + '/perfil', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome: '', areas: [] }) });
  assert.equal(r.status, 200);
};

test('K-ui: tela principal intacta ao abrir e Perfil começa oculto', async () => {
  const ui = await abrir();
  assert.equal(ui.$('perfil').hidden, true);
  assert.equal(ui.$('chat').hidden, false);
  assert.equal(ui.$('form').hidden, false);
  assert.match(ui.$('chat').textContent, /Digite um cargo ou área/);
  assert.equal(ui.$('nav-vagas').getAttribute('aria-current'), 'page');
});

test('A: perfil vazio — campos vazios, sem erro e sem dados fictícios', async () => {
  const ui = await abrir();
  await ui.abrirPerfil();
  assert.equal(ui.$('p-nome').value, '');
  assert.deepEqual(ui.chips(), []);
  assert.equal(ui.$('p-vazio').hidden, false);
  assert.ok(!ui.$('p-status').classList.contains('erro'));
  assert.match(ui.status(), /ainda não tem um perfil/);
  assert.equal(ui.$('p-salvar').disabled, false);
});

test('C/E/J-ui: adicionar (botão e Enter), salvar, reabrir em nova sessão, remover e salvar', async () => {
  await limpar();
  const ui = await abrir();
  await ui.abrirPerfil();
  ui.$('p-nome').value = '  José D’Ávila-Çelik ';
  ui.adicionar('Desenvolvimento Mobile');
  ui.$('p-area').value = 'Ciência de Dados';
  ui.$('p-area').dispatchEvent(new ui.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  ui.adicionar('  Engenharia   de Dados ');
  assert.deepEqual(ui.chips(), ['Desenvolvimento Mobile', 'Ciência de Dados', 'Engenharia de Dados']);
  await ui.salvar();
  assert.equal(ui.status(), 'Perfil salvo.');
  assert.equal(ui.$('p-nome').value, 'José D’Ávila-Çelik');

  // "recarregar a página" = nova janela; os dados vêm do backend
  const ui2 = await abrir();
  await ui2.abrirPerfil();
  assert.equal(ui2.$('p-nome').value, 'José D’Ávila-Çelik');
  assert.deepEqual(ui2.chips(), ['Desenvolvimento Mobile', 'Ciência de Dados', 'Engenharia de Dados']);

  ui2.d.querySelector('#p-chips .chip button[aria-label="Remover Ciência de Dados"]').click();
  assert.deepEqual(ui2.chips(), ['Desenvolvimento Mobile', 'Engenharia de Dados']);
  await ui2.salvar();

  const ui3 = await abrir();
  await ui3.abrirPerfil();
  assert.deepEqual(ui3.chips(), ['Desenvolvimento Mobile', 'Engenharia de Dados']);
});

test('D-ui: duplicata (caixa/espaços) é recusada com mensagem e não apaga o que existe', async () => {
  await limpar();
  const ui = await abrir();
  await ui.abrirPerfil();
  ui.adicionar('Inteligência Artificial');
  for (const v of ['inteligência artificial', '  INTELIGÊNCIA   ARTIFICIAL  ']) {
    ui.adicionar(v);
    assert.match(ui.status(), /já está na lista/);
    assert.deepEqual(ui.chips(), ['Inteligência Artificial']);
  }
});

test('H-ui: validações do formulário (vazio, tamanho) não enviam nada ao servidor nem apagam áreas', async () => {
  await limpar();
  const ui = await abrir();
  await ui.abrirPerfil();
  ui.adicionar('Cloud Computing');
  ui.adicionar('    ');
  assert.match(ui.status(), /Digite o nome de uma área/);
  ui.adicionar('x'.repeat(61));
  assert.match(ui.status(), /no máximo 60/);
  assert.deepEqual(ui.chips(), ['Cloud Computing']);
  ui.$('p-nome').value = 'n'.repeat(101);
  const antes = ui.chamadas.filter(c => c.metodo === 'PUT').length;
  await ui.salvar();
  assert.match(ui.status(), /nome pode ter no máximo 100/);
  assert.equal(ui.chamadas.filter(c => c.metodo === 'PUT').length, antes);
  assert.deepEqual(ui.chips(), ['Cloud Computing']);
  // texto pendente no campo de área bloqueia o salvamento em vez de ser descartado em silêncio
  ui.$('p-nome').value = 'ok';
  ui.digitarArea('Esquecida');
  await ui.salvar();
  assert.match(ui.status(), /ainda não foi adicionado/);
  assert.equal(ui.$('p-area').value, 'Esquecida');
});

test('I: falha de rede ao salvar — sem sucesso falso, valores preservados, nova tentativa funciona', async () => {
  await limpar();
  let quebrar = true;
  const ui = await abrir((u, o, original) => (quebrar && o.method === 'PUT' ? Promise.reject(new TypeError('Failed to fetch')) : original()));
  await ui.abrirPerfil();
  ui.$('p-nome').value = 'Ana';
  ui.adicionar('Back-end');
  await ui.salvar();
  assert.ok(ui.$('p-status').classList.contains('erro'));
  assert.doesNotMatch(ui.status(), /Perfil salvo/);
  assert.match(ui.status(), /falha de conexão/);
  assert.equal(ui.$('p-nome').value, 'Ana');
  assert.deepEqual(ui.chips(), ['Back-end']);
  assert.equal(ui.$('p-salvar').disabled, false);
  const gravado = await (await fetch(base + '/perfil')).json();
  assert.deepEqual([gravado.nome, gravado.areas], ['', []]); // nada foi gravado

  quebrar = false;
  await ui.salvar();
  assert.equal(ui.status(), 'Perfil salvo.');
  assert.deepEqual((await (await fetch(base + '/perfil')).json()).areas, ['Back-end']);
});

test('I: erro 500 do servidor mostra a mensagem do backend, sem sucesso falso', async () => {
  await limpar();
  const ui = await abrir((u, o, original) => (o.method === 'PUT'
    ? Promise.resolve(new Response(JSON.stringify({ detail: 'Não foi possível salvar o perfil. Tente novamente.' }), { status: 500, headers: { 'Content-Type': 'application/json' } }))
    : original()));
  await ui.abrirPerfil();
  ui.adicionar('IA');
  await ui.salvar();
  assert.ok(ui.$('p-status').classList.contains('erro'));
  assert.match(ui.status(), /Não foi possível salvar/);
  assert.deepEqual(ui.chips(), ['IA']);
});

test('I: falha ao carregar — mensagem, Salvar desabilitado e botão para tentar de novo', async () => {
  await limpar();
  let quebrar = true;
  const ui = await abrir((u, o, original) => (quebrar && u === '/perfil' ? Promise.reject(new TypeError('Failed to fetch')) : original()));
  await ui.abrirPerfil();
  assert.match(ui.status(), /Não foi possível carregar/);
  assert.equal(ui.$('p-salvar').disabled, true);
  assert.equal(ui.$('p-recarregar').hidden, false);
  assert.equal(ui.$('p-corpo').hidden, true);
  quebrar = false;
  ui.$('p-recarregar').click();
  await esperar(() => !ui.$('p-corpo').hidden);
  assert.equal(ui.$('p-salvar').disabled, false);
});

test('Salvar: cliques repetidos geram uma única gravação', async () => {
  await limpar();
  const ui = await abrir((u, o, original) => (o.method === 'PUT' ? dormir(150).then(original) : original()));
  await ui.abrirPerfil();
  ui.adicionar('Mobile');
  ui.$('p-salvar').click(); ui.$('p-salvar').click(); ui.$('p-salvar').click();
  await esperar(() => ui.status() === 'Perfil salvo.');
  assert.equal(ui.chamadas.filter(c => c.metodo === 'PUT').length, 1);
});

test('J: texto parecido com HTML é exibido como texto e nunca executado', async () => {
  await limpar();
  const area = '<img src=x onerror="window.__xss=1">';
  const nome = '<b>Negrito</b> & "aspas"';
  const ui = await abrir();
  await ui.abrirPerfil();
  ui.$('p-nome').value = nome;
  ui.adicionar(area);
  assert.equal(ui.d.querySelectorAll('#p-chips img, #p-chips b').length, 0);
  await ui.salvar();
  const ui2 = await abrir();
  await ui2.abrirPerfil();
  assert.deepEqual(ui2.chips(), [area]);
  assert.equal(ui2.$('p-nome').value, nome);
  assert.equal(ui2.d.querySelectorAll('#perfil img, #perfil b, #perfil script').length, 0);
  await dormir(100);
  assert.equal(ui2.w.__xss, undefined);
  assert.equal(ui.w.__xss, undefined);
});

test('Navegação: voltar às vagas, descartar alterações só com confirmação', async () => {
  await limpar();
  const ui = await abrir();
  await ui.abrirPerfil();
  assert.equal(ui.$('chat').hidden, true);
  assert.equal(ui.$('form').hidden, true);
  assert.equal(ui.$('nav-perfil').getAttribute('aria-current'), 'page');

  ui.adicionar('Mobile');                       // alteração não salva
  ui.w.confirm = () => false;                    // usuário recusa descartar
  ui.$('p-voltar').click();
  assert.equal(ui.$('perfil').hidden, false);
  assert.deepEqual(ui.chips(), ['Mobile']);

  ui.w.confirm = () => true;
  ui.$('p-voltar').click();
  assert.equal(ui.$('perfil').hidden, true);
  assert.equal(ui.$('chat').hidden, false);
  assert.equal(ui.$('form').hidden, false);
  assert.equal(ui.$('nav-vagas').getAttribute('aria-current'), 'page');

  await ui.abrirPerfil();                        // reabrir: o que não foi salvo não aparece
  assert.deepEqual(ui.chips(), []);
});
