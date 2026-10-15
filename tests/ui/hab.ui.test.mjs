// Testes de interface da tela "Vagas por habilidades": página real (jsdom) + backend real + provedor SIMULADO.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';
import { JSDOM } from 'jsdom';

const AQUI = dirname(fileURLToPath(import.meta.url));
const procs = [];
let base, baseSemChave;

const portaLivre = () => new Promise(res => {
  const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});
const dormir = ms => new Promise(r => setTimeout(r, ms));
async function esperar(cond, ms = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await cond()) return; await dormir(15); }
  throw new Error('timeout esperando: ' + cond.toString());
}
async function subir(extra = {}) {
  const porta = await portaLivre();
  const env = { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-hab-')), 'h.db'), ...extra };
  const pr = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env, stdio: 'ignore' });
  procs.push(pr);
  const url = `http://127.0.0.1:${porta}`;
  await esperar(async () => { try { return (await fetch(url + '/status')).ok; } catch { return false; } }, 20000);
  return url;
}
before(async () => { base = await subir(); baseSemChave = await subir({ UI_SEM_CHAVE: '1' }); });
after(() => procs.forEach(p => p.kill()));

async function abrir({ url = base, ponte } = {}) {
  const html = await (await fetch(url + '/')).text();
  const chamadas = [];
  const dom = new JSDOM(html, {
    url: url + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) {
      w.confirm = () => true;
      w.fetch = (u, o = {}) => {
        const original = () => fetch(new URL(u, url), o);
        chamadas.push({ url: String(u), metodo: o.method || 'GET', corpo: o.body ? JSON.parse(o.body) : null });
        return ponte ? ponte(String(u), o, original) : original();
      };
    },
  });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas,
    abrirHab: async () => { $('nav-hab').click(); await esperar(() => !/Carregando/.test($('h-status').textContent)); await dormir(40); },
    chips: () => [...d.querySelectorAll('#h-chips .chip > span')].map(s => s.textContent),
    status: () => $('h-status').textContent,
    adicionar: async t => {
      const antes = ui.chips().length, msg = ui.status();
      $('h-input').value = t; $('h-add').click();
      await esperar(() => ui.chips().length !== antes || ui.status() !== msg || $('h-input').value === '');
      await dormir(30);
    },
    buscar: async () => { $('h-buscar').click(); await esperar(() => !/Buscando|Carregando mais/.test($('h-status').textContent)); },
    cartoes: () => [...d.querySelectorAll('#h-resultado .vaga')],
    posts: () => chamadas.filter(c => c.metodo === 'POST' && c.url === '/busca-habilidades'),
  };
  return ui;
}
const limparPerfil = async (url = base, areas = []) => {
  await fetch(url + '/habilidades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ habilidades: [] }) });
  await fetch(url + '/perfil', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome: '', areas }) });
};

test('navegação: abre a tela, esconde a principal e volta', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  assert.equal(ui.$('hab').hidden, false);
  assert.equal(ui.$('chat').hidden, true); assert.equal(ui.$('form').hidden, true);
  assert.equal(ui.$('nav-hab').getAttribute('aria-current'), 'page');
  ui.$('h-voltar').click();
  assert.equal(ui.$('hab').hidden, true); assert.equal(ui.$('chat').hidden, false);
  assert.equal(ui.$('nav-vagas').getAttribute('aria-current'), 'page');
  assert.equal(ui.$('nav-hab').getAttribute('aria-current'), null);
});

test('estado sem habilidades: explica o que informar e não chama a busca', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  assert.match(ui.status(), /ainda não tem habilidades/);
  assert.equal(ui.$('h-vazio').hidden, false);
  assert.match(ui.$('h-estimativa').textContent, /Adicione ao menos uma habilidade/);
  await ui.buscar();
  assert.match(ui.status(), /Adicione ao menos uma habilidade/);
  assert.equal(ui.posts().length, 0);
});

test('A2-ui: adicionar com alias, duplicata por alias, Enter, corrigir e remover', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('js');
  assert.deepEqual(ui.chips(), ['JavaScript']);                       // grafia canônica, não a digitada
  await ui.adicionar('Javascript');
  assert.match(ui.status(), /já está na lista/);
  assert.deepEqual(ui.chips(), ['JavaScript']);
  ui.$('h-input').value = '  react   native ';
  ui.$('h-input').dispatchEvent(new ui.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await esperar(() => ui.chips().length === 2);
  assert.deepEqual(ui.chips(), ['JavaScript', 'React Native']);
  await ui.adicionar('Java');                                          // Java != JavaScript
  assert.deepEqual(ui.chips(), ['JavaScript', 'React Native', 'Java']);
  await ui.adicionar('   ');
  assert.match(ui.status(), /Digite o nome de uma habilidade/);
  await ui.adicionar('x'.repeat(41));
  assert.match(ui.status(), /no máximo 40/);
  assert.equal(ui.chips().length, 3);                                  // inválida não apaga nada
  ui.d.querySelector('#h-chips button[aria-label="Corrigir Java"]').click();
  assert.equal(ui.$('h-input').value, 'Java'); assert.deepEqual(ui.chips(), ['JavaScript', 'React Native']);
  ui.$('h-input').value = '';
  ui.d.querySelector('#h-chips button[aria-label="Remover React Native"]').click();
  assert.deepEqual(ui.chips(), ['JavaScript']);
});

test('A1-ui: salvar e recuperar em nova sessão; áreas do perfil não viram habilidades', async () => {
  await limparPerfil(base, ['Desenvolvimento Mobile']);
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('nodejs'); await ui.adicionar('Gestão de Projetos');
  ui.$('h-salvar').click();
  await esperar(() => ui.status() === 'Habilidades salvas.');
  const ui2 = await abrir();
  await ui2.abrirHab();
  assert.deepEqual(ui2.chips(), ['Node.js', 'Gestão de projetos']);
  assert.ok(![...ui2.$('h-area').options].some(o => ui2.chips().includes(o.value)));
  assert.deepEqual([...ui2.$('h-area').options].map(o => o.value), ['', 'Desenvolvimento Mobile']);
});

test('falha ao salvar: sem sucesso falso e lista preservada', async () => {
  await limparPerfil();
  let quebrar = true;
  const ui = await abrir({ ponte: (u, o, orig) => (quebrar && o.method === 'PUT' && u === '/habilidades' ? Promise.reject(new TypeError('x')) : orig()) });
  await ui.abrirHab();
  await ui.adicionar('Python');
  ui.$('h-salvar').click();
  await esperar(() => /Não foi possível salvar/.test(ui.status()));
  assert.ok(ui.$('h-status').classList.contains('erro'));
  assert.doesNotMatch(ui.status(), /salvas\./);
  assert.deepEqual(ui.chips(), ['Python']);
  quebrar = false;
  ui.$('h-salvar').click();
  await esperar(() => ui.status() === 'Habilidades salvas.');
});

test('falha ao recuperar o perfil: avisa, bloqueia Salvar (não sobrescrever), mas permite digitar e buscar', async () => {
  await limparPerfil();
  let quebrar = true;
  const ui = await abrir({ ponte: (u, o, orig) => (quebrar && u === '/habilidades' ? Promise.reject(new TypeError('x')) : orig()) });
  await ui.abrirHab();
  assert.match(ui.status(), /Não foi possível recuperar suas habilidades salvas/);
  assert.equal(ui.$('h-salvar').disabled, true);
  assert.equal(ui.$('h-recarregar').hidden, false);
  await ui.adicionar('JavaScript'); await ui.adicionar('Docker'); await ui.adicionar('TypeScript');
  await ui.buscar();
  assert.ok(ui.cartoes().length > 0);
  quebrar = false;
  ui.$('h-recarregar').click();
  await esperar(() => ui.$('h-salvar').disabled === false);
});

test('A5 + F1: perfil vazio, habilidades digitadas na tela, resultados com pontuação transparente e ordenados', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  for (const h of ['JavaScript', 'Docker', 'TypeScript']) await ui.adicionar(h);
  assert.match(ui.$('h-estimativa').textContent, /até \d+ requisição/);
  assert.match(ui.$('h-estimativa').textContent, /páginas já em cache não gastam/);
  await ui.buscar();
  assert.equal(ui.posts().length, 1);
  assert.deepEqual(ui.posts()[0].corpo.habilidades, ['JavaScript', 'Docker', 'TypeScript']);
  assert.equal(ui.$('h-buscar').disabled, false);

  const cards = ui.cartoes();
  assert.equal(cards.length, 4);
  const txt = cards.map(c => c.textContent);
  assert.match(txt[0], /Dev Fullstack/);
  assert.match(txt[0], /≈ 63% dos requisitos identificados constam no seu perfil/);
  assert.match(txt[0], /2\/3 obrigatórios · 1\/2 diferenciais · 5 requisitos identificados/);
  assert.match(txt[0], /Obrigatórios ainda não cadastrados no perfil/);
  assert.match(txt[0], /Java/); assert.match(txt[0], /Kubernetes/);
  assert.match(txt[0], /Alfa · São Paulo, SP, BR/);
  assert.match(txt[1], /≈ 33%/);                                       // 2ª por compatibilidade
  assert.match(txt[3], /Vaga curta/); assert.match(txt[3], /Dados insuficientes: sem pontuação/);
  assert.doesNotMatch(txt[3], /≈ \d+%/);                               // sem nota artificial
  // lacunas: rótulo é de cadastro, não de desconhecimento
  const res = ui.$('h-resultado').textContent;
  assert.match(res, /Habilidades a desenvolver/);
  assert.match(res, /não cadastrada no perfil · em \d+ de \d+ vagas \(\d+%\) · obrigatória em \d+ · diferencial em \d+/);
  assert.match(res, /não prova que você não saiba usá-los/);
  assert.doesNotMatch(res, /você não sabe|desconhece/i);
  assert.match(res, /Esta busca usou \d+ requisição/);
  assert.match(res, /retornada\(s\) pelo provedor/);
});

test('J/F4-ui: dados externos como texto, links só http(s), nada executa; títulos longos não quebram o layout', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('Python'); await ui.adicionar('SQL');
  await ui.buscar();
  const box = ui.$('h-resultado');
  assert.equal(box.querySelectorAll('img, script, b').length, 0);
  assert.ok([...box.querySelectorAll('h3')].some(h => h.textContent.includes('<img src=x onerror="window.__xss=1">')));
  assert.ok([...box.querySelectorAll('.sub')].some(p => p.textContent.includes('<b>X</b>')));
  await dormir(100);
  assert.equal(ui.w.__xss, undefined);
  const hrefs = [...box.querySelectorAll('a')].map(a => a.getAttribute('href'));
  assert.ok(hrefs.length >= 2 && hrefs.every(h => /^https?:\/\//.test(h)));  // só http(s)
  assert.ok(hrefs.includes('https://ok.test/vaga?x=1'));                   // link legítimo preservado
  assert.ok(!hrefs.some(h => /javascript:/i.test(h)));                      // javascript: não vira link
  box.querySelectorAll('a').forEach(a => { assert.equal(a.target, '_blank'); assert.match(a.rel, /noopener/); });
  assert.ok(ui.cartoes().some(c => /sem link de candidatura/.test(c.textContent)));
  assert.ok(ui.w.document.querySelector('style').textContent.includes('overflow-wrap:anywhere'));
});

test('estados de erro: sem vagas, cota, provedor recusa, rede, credenciais ausentes', async () => {
  await limparPerfil();
  let ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('Vazio');
  await ui.buscar();
  assert.match(ui.$('h-resultado').textContent, /Nenhuma vaga encontrada para essas habilidades/);
  assert.equal(ui.$('h-mais').hidden, true);
  assert.match(ui.status(), /nenhuma vaga encontrada/i);

  ui = await abrir(); await ui.abrirHab(); await ui.adicionar('Cota'); await ui.buscar();
  assert.ok(ui.$('h-status').classList.contains('erro')); assert.match(ui.status(), /Limite de requisições/);

  ui = await abrir(); await ui.abrirHab(); await ui.adicionar('Falha'); await ui.buscar();
  assert.ok(ui.$('h-status').classList.contains('erro')); assert.match(ui.status(), /recusou a chave/);
  assert.doesNotMatch(ui.status() + ui.$('h-resultado').textContent, /chave-de-teste/);

  ui = await abrir({ ponte: (u, o, orig) => (u === '/busca-habilidades' ? Promise.reject(new TypeError('x')) : orig()) });
  await ui.abrirHab(); await ui.adicionar('Python'); await ui.buscar();
  assert.match(ui.status(), /falha de conexão/); assert.ok(ui.$('h-status').classList.contains('erro'));
  assert.equal(ui.$('h-buscar').disabled, false);

  ui = await abrir({ url: baseSemChave });
  await ui.abrirHab(); await ui.adicionar('Python');
  assert.match(ui.$('h-estimativa').textContent, /faltam as credenciais do provedor/);
  await ui.buscar();
  assert.match(ui.status(), /busca real está indisponível/); assert.ok(ui.$('h-status').classList.contains('erro'));
  assert.equal(ui.cartoes().length, 0);                                // nada fictício
});

test('busca em andamento: estado de carregamento e cliques repetidos geram uma única chamada', async () => {
  await limparPerfil();
  const ui = await abrir({ ponte: (u, o, orig) => (u === '/busca-habilidades' ? dormir(200).then(orig) : orig()) });
  await ui.abrirHab();
  await ui.adicionar('Python');
  ui.$('h-buscar').click(); ui.$('h-buscar').click(); ui.$('h-buscar').click();
  assert.match(ui.status(), /Buscando e analisando/);
  assert.equal(ui.$('h-buscar').disabled, true);
  await esperar(() => /Busca concluída/.test(ui.status()));
  assert.equal(ui.posts().length, 1);
});

test('paginação: carregar mais usa as mesmas habilidades e detecta o fim dos resultados', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('Python'); await ui.adicionar('Docker');
  await ui.buscar();
  assert.equal(ui.$('h-mais').hidden, false);
  const n1 = ui.cartoes().length;
  ui.$('h-input').value = ''; await ui.adicionar('Rust');                // edição posterior não afeta o "carregar mais"
  ui.$('h-mais').click();
  await esperar(() => ui.posts().length === 2 && !/Carregando mais/.test(ui.status()));
  assert.equal(ui.posts()[1].corpo.paginas, 2);
  assert.deepEqual(ui.posts()[1].corpo.habilidades, ['Python', 'Docker']);
  assert.ok(ui.cartoes().length > n1);
  ui.$('h-mais').click();                                                 // página 3 vem vazia
  await esperar(() => ui.posts().length === 3 && !/Carregando mais/.test(ui.status()));
  assert.match(ui.status(), /Não há mais resultados/);
  assert.equal(ui.$('h-mais').hidden, true);
});

test('contexto: áreas do perfil aparecem como opção e entram na consulta; sem área, só habilidades', async () => {
  await limparPerfil(base, ['Ciência de Dados']);
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('Python');
  assert.doesNotMatch(ui.$('h-estimativa').textContent, /Ciência de Dados/);
  ui.$('h-area').value = 'Ciência de Dados'; ui.$('h-area').dispatchEvent(new ui.w.Event('change'));
  await esperar(() => /Ciência de Dados Python/.test(ui.$('h-estimativa').textContent));
  await ui.buscar();
  assert.equal(ui.posts()[0].corpo.area, 'Ciência de Dados');
  assert.deepEqual(ui.posts()[0].corpo.habilidades, ['Python']);
});

test('sair com alterações não salvas pede confirmação; descartar recarrega do servidor', async () => {
  await limparPerfil();
  const ui = await abrir();
  await ui.abrirHab();
  await ui.adicionar('Rust');
  ui.w.confirm = () => false;
  ui.$('nav-vagas').click();
  assert.equal(ui.$('hab').hidden, false); assert.deepEqual(ui.chips(), ['Rust']);
  ui.w.confirm = () => true;
  ui.$('nav-vagas').click();
  assert.equal(ui.$('hab').hidden, true);
  await ui.abrirHab();
  assert.deepEqual(ui.chips(), []);
});
