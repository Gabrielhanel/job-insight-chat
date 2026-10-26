// Etapa 8 — tema e painel de insights: página real (jsdom) + backend real + provedor SIMULADO (dados SINTÉTICOS).
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
  proc = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env: { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-in-')), 'g.db') }, stdio: 'ignore' });
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

test('tema claro por padrão, alternância persistente e ausência de prefers-color-scheme', async () => {
  const ui = await abrir();
  assert.equal(ui.d.documentElement.getAttribute('data-tema'), 'claro');
  ui.$('tema-alt').click();
  assert.equal(ui.d.documentElement.getAttribute('data-tema'), 'escuro');
  assert.equal(ui.w.localStorage.getItem('jobinsight-tema'), 'escuro');
  assert.ok(!/prefers-color-scheme/.test(ui.d.documentElement.outerHTML));
});

test('painel de insights: vazio, preenchido pelo backend e limpo ao trocar de conversa; atalho só navega', async () => {
  const ui = await abrir();
  assert.match(ui.$('ins-corpo').textContent, /Nenhuma análise/);
  await ui.chat('Insight Base');
  const cards = [...ui.d.querySelectorAll('#ins-corpo .ins')];
  assert.ok(cards.length > 0);
  const atalho = ui.$('ins-corpo').querySelector('.ins button');
  if (atalho) {
    const antes = ui.chamadas.length;
    atalho.click();
    assert.ok(!ui.chamadas.slice(antes).some(c => /busca-habilidades|evolucao|comparar/.test(c) && c.startsWith('POST')));
  }
  ui.$('s-nova').click();
  await esperar(() => /Nenhuma análise/.test(ui.$('ins-corpo').textContent));
});
