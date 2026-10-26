// Etapa 7 — histórico persistente e sessões na interface (página real em jsdom + backend real + provedor SIMULADO; vagas SINTÉTICAS).
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
  proc = spawn('python3', [join(AQUI, 'servidor_ui.py')], { env: { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-ses-')), 's.db') }, stdio: 'ignore' });
  base = `http://127.0.0.1:${porta}`;
  await esperar(async () => { try { return (await fetch(base + '/status')).ok; } catch { return false; } }, 20000);
});
after(() => proc && proc.kill());

const api = async (m, u, corpo) => { const r = await fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json' }, body: corpo ? JSON.stringify(corpo) : undefined }); return { status: r.status, dados: await r.json().catch(() => null) }; };
async function abrir({ ponte, storage = {}, confirmar = true } = {}) {
  const html = await (await fetch(base + '/')).text();
  const chamadas = [];
  const dom = new JSDOM(html, { url: base + '/', runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse(w) {
      w.confirm = () => confirmar;
      Object.entries(storage).forEach(([k, v]) => w.localStorage.setItem(k, v));
      w.fetch = (u, o = {}) => { chamadas.push({ url: String(u), metodo: o.method || 'GET', corpo: o.body ? JSON.parse(o.body) : null }); const original = () => fetch(new URL(u, base), o); return ponte ? ponte(String(u), o, original) : original(); };
    } });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const ui = {
    w, d, $, chamadas,
    guardado: () => Object.fromEntries(Object.keys(w.localStorage).map(k => [k, w.localStorage.getItem(k)])),
    pronto: () => esperar(() => !/Carregando histórico|Abrindo conversa/.test($('s-lista-msg').textContent + $('s-status').textContent)),
    status: () => $('s-status').textContent,
    titulo: () => $('s-titulo').textContent,
    painel: async () => { if ($('s-painel').hidden) $('s-hist').click(); await esperar(() => !/Carregando histórico/.test($('s-lista-msg').textContent)); },
    lista: () => [...$('s-lista').children].map(li => ({ titulo: li.querySelector('strong').firstChild.textContent, ativa: li.getAttribute('aria-current') === 'true', meta: li.querySelector('.meta').textContent, abrir: li.querySelector('button[aria-label^="Abrir"]'), excluir: li.querySelector('button[aria-label^="Excluir"]') })),
    linha: () => [...$('s-linha').children].map(li => ({ tipo: li.querySelector('.s-tipo').textContent, consulta: li.querySelector('strong').textContent, meta: li.querySelector('.meta').textContent, abrir: li.querySelector('button') })),
    msgs: () => [...d.querySelectorAll('.msg')],
    chat: async (texto) => {
      const antes = d.querySelectorAll('.msg.bot').length;
      $('q').value = texto; $('btn').click();
      await esperar(() => d.querySelectorAll('.msg.bot').length > antes && !$('btn').disabled && !/Buscando vagas/.test([...d.querySelectorAll('.msg.bot')].pop().textContent));
      return [...d.querySelectorAll('.msg.bot')].pop();
    },
    nova: async () => { $('s-nova').click(); await esperar(() => /Nova conversa criada e salva|Não foi possível criar/.test(ui.status())); },
    abrirSessao: async titulo => { (await ui.painel(), ui.lista().find(x => x.titulo === titulo).abrir.click()); await esperar(() => /Conversa aberta|não foi possível abrir|Conversa não encontrada/i.test(ui.status())); },
  };
  await ui.pronto();
  return ui;
}
const usado = async () => (await api('GET', '/status')).dados.usado;
const figuras = box => [...box.querySelectorAll('figure.gr')].map(f => f.querySelector('figcaption').textContent);

test('21: histórico vazio — mensagem própria, nenhuma conversa ativa e nenhuma chamada além do histórico', async () => {
  const ui = await abrir();
  await ui.painel();
  assert.match(ui.$('s-lista-msg').textContent, /Nenhuma conversa salva ainda/);
  assert.equal(ui.titulo(), 'nenhuma ativa'); assert.equal(ui.$('s-ativa').hidden, true); assert.equal(ui.$('s-renomear').disabled, true);
  assert.match(ui.$('s-linha-msg').textContent, /Nenhuma conversa ativa/);
  assert.deepEqual([...new Set(ui.chamadas.map(c => c.url).filter(u => u !== '/status'))], ['/sessoes']);        // só o histórico; nada ao provedor
});

test('22: criar conversa só aparece como criada depois da confirmação do backend; falha não cria nada', async () => {
  let quebrar = true;
  const ui = await abrir({ ponte: (u, o, orig) => (quebrar && o.method === 'POST' && u === '/sessoes' ? Promise.reject(new TypeError('x')) : orig()) });
  const antes = (await api('GET', '/sessoes')).dados.sessoes.length;
  await ui.nova();
  assert.match(ui.status(), /Não foi possível criar a conversa: falha de conexão.*Nada foi salvo/); assert.ok(ui.$('s-status').classList.contains('erro'));
  assert.equal(ui.titulo(), 'nenhuma ativa'); assert.equal((await api('GET', '/sessoes')).dados.sessoes.length, antes);
  quebrar = false;
  await ui.nova();
  assert.equal(ui.status(), 'Nova conversa criada e salva.'); assert.equal(ui.titulo(), 'Nova conversa'); assert.equal(ui.$('s-ativa').hidden, false);
  const sessoes = (await api('GET', '/sessoes')).dados.sessoes;
  assert.equal(sessoes.length, antes + 1); assert.equal(sessoes[0].titulo, 'Nova conversa');                      // realmente gravada no backend
  await ui.painel(); assert.deepEqual(ui.lista()[0].ativa, true);                                               // 24: indicador da sessão ativa
});

test('cliques repetidos em "+ Nova conversa" criam uma só sessão', async () => {
  const ui = await abrir();
  const antes = (await api('GET', '/sessoes')).dados.sessoes.length;
  ui.$('s-nova').click(); ui.$('s-nova').click(); ui.$('s-nova').click();
  await esperar(() => ui.status() === 'Nova conversa criada e salva.'); await dormir(100);
  assert.equal((await api('GET', '/sessoes')).dados.sessoes.length, antes + 1);
});

test('primeira análise cria a conversa sozinha (título da consulta, sem IA); análise salva e listada', async () => {
  const ui = await abrir();
  await ui.chat('Graf Base Auto');
  await esperar(() => /Análise salva na conversa \(nº 1\)/.test(ui.status()));
  await esperar(() => ui.titulo() === 'Graf Base Auto');
  const corpo = ui.chamadas.find(c => c.url === '/chat').corpo;
  assert.match(corpo.sessao_id, /^[0-9a-f]{32}$/); assert.ok(corpo.interacao_uid.length >= 8);
  assert.deepEqual(ui.linha().map(x => [x.tipo, x.consulta]), [['Busca por cargo', 'Graf Base Auto']]);
  await ui.painel();
  const item = ui.lista().find(x => x.titulo === 'Graf Base Auto');
  assert.ok(item.ativa); assert.match(item.meta, /1 análise\(s\) · Busca por cargo: 12 vagas analisadas/);
});

test('23/5/15: abrir uma conversa anterior restaura só as análises dela, em ordem, sem nova consulta externa; continuar acrescenta', async () => {
  const ui = await abrir();
  await ui.nova(); await ui.chat('Graf Poucos Um'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.chat('Graf Base Dois'); await esperar(() => /nº 2/.test(ui.status()));
  await ui.nova(); await ui.chat('Graf Pleno100 Tres'); await esperar(() => /nº 1/.test(ui.status()));
  assert.equal(ui.msgs().filter(m => m.classList.contains('user')).length, 1);                                  // a conversa nova começa limpa
  const cota = await usado(), n = ui.chamadas.length;
  await ui.abrirSessao('Graf Poucos Um');
  const users = ui.msgs().filter(m => m.classList.contains('user')).map(m => m.textContent);
  assert.deepEqual(users, ['Graf Poucos Um', 'Graf Base Dois']);                                                // ordem cronológica; nada da outra conversa
  assert.ok(!ui.$('chat').textContent.includes('Pleno100 Tres'));
  const bots = [...ui.d.querySelectorAll('.msg.bot')];
  assert.match(bots[1].textContent, /Resultado salvo: pesquisa de/); assert.ok(figuras(bots[2] || bots[1]).length >= 1);   // gráficos reconstruídos dos dados salvos
  assert.match(ui.status(), /Conversa aberta: 2 análise\(s\) salva\(s\)\. Nada foi consultado de novo\./);
  const novas = ui.chamadas.slice(n).map(c => `${c.metodo} ${c.url}`);
  assert.ok(!novas.some(c => c.startsWith('POST /chat') || c.startsWith('POST /busca') || c.startsWith('POST /evolucao') || c.startsWith('POST /comparar')));  // 13: nenhuma análise refeita
  assert.equal(await usado(), cota);                                                                             // nem cota
  await ui.painel(); assert.deepEqual(ui.lista().filter(x => x.ativa).map(x => x.titulo), ['Graf Poucos Um']);   // 24
  assert.deepEqual(ui.linha().map(x => x.consulta), ['Graf Poucos Um', 'Graf Base Dois']);
  await ui.chat('Graf Base Quatro');                                                                            // 5: continuar a conversa antiga
  await esperar(() => /nº 3/.test(ui.status()));
  assert.deepEqual(ui.linha().map(x => x.consulta), ['Graf Poucos Um', 'Graf Base Dois', 'Graf Base Quatro']);
  const outra = (await api('GET', '/sessoes')).dados.sessoes.find(s => s.titulo === 'Graf Pleno100 Tres');
  assert.equal(outra.total_interacoes, 1);                                                                       // a outra conversa não recebeu nada
});

test('7: lista ordenada pela atividade mais recente', async () => {
  const ui = await abrir();
  await ui.nova(); await ui.chat('Graf Ordem Antiga'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.nova(); await ui.chat('Graf Ordem Nova'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.painel();
  const titulos = () => ui.lista().map(x => x.titulo);
  assert.deepEqual(titulos().slice(0, 2), ['Graf Ordem Nova', 'Graf Ordem Antiga']);
  await ui.abrirSessao('Graf Ordem Antiga'); await ui.chat('Graf Ordem Antiga Retorno'); await esperar(() => /nº 2/.test(ui.status()));
  await esperar(() => titulos()[0] === 'Graf Ordem Antiga');                                                    // atividade recente a leva ao topo
});

test('8/12: dados dos gráficos e resultados de habilidades, evolução e comparação são reabertos a partir do histórico', async () => {
  const ui = await abrir();
  await ui.nova();
  ui.$('nav-hab').click(); await dormir(60);
  ui.$('h-input').value = 'Python'; ui.$('h-add').click(); await esperar(() => ui.d.querySelectorAll('#h-chips .chip').length >= 1);
  ui.$('h-buscar').click(); await esperar(() => /Busca concluída/.test(ui.$('h-status').textContent));
  const figHab = figuras(ui.$('h-resultado'));
  ui.$('nav-evo').click(); await dormir(40);
  ui.$('e-cargo').value = 'Desenvolvedor React Native Hist'; ui.$('e-analisar').click(); await esperar(() => ui.$('e-status').textContent === 'Análise concluída.');
  const figEvo = figuras(ui.$('e-resultado')), roscaLegenda = [...ui.$('e-resultado').querySelectorAll('.gr-rosca .gr-legenda li')].map(l => l.textContent);
  ui.$('nav-cmp').click(); await dormir(40);
  for (const L of ['a', 'b']) { ui.$(`m-${L}-consulta`).value = 'Cmp Backend'; ui.$(`m-${L}-buscar`).click(); await esperar(() => ui.d.querySelectorAll(`#m-${L}-lista .opcao`).length === 4); }
  ui.d.querySelectorAll('#m-a-lista .opcao')[0].querySelector('button').click(); ui.d.querySelectorAll('#m-b-lista .opcao')[1].querySelector('button').click();
  ui.$('m-comparar').click(); await esperar(() => ui.$('m-status').textContent === 'Comparação concluída.');
  const figCmp = figuras(ui.$('m-resultado'));
  assert.ok(figHab.length && figEvo.length && figCmp.length);
  await esperar(() => ui.linha().length === 3);
  await ui.nova();                                                                                              // sai: as telas ficam limpas
  assert.equal(ui.$('h-resultado').hidden, true); assert.equal(ui.$('e-resultado').hidden, true); assert.equal(ui.$('m-resultado').hidden, true);
  assert.match(ui.$('m-estado').textContent, /Nenhuma vaga selecionada/);
  const n = ui.chamadas.length;
  const titulo = (await api('GET', '/sessoes')).dados.sessoes.find(s => s.total_interacoes === 3).titulo;
  await ui.abrirSessao(titulo);
  assert.deepEqual(figuras(ui.$('h-resultado')), figHab);
  assert.deepEqual(figuras(ui.$('e-resultado')), figEvo);
  assert.deepEqual([...ui.$('e-resultado').querySelectorAll('.gr-rosca .gr-legenda li')].map(l => l.textContent), roscaLegenda);   // mesma rosca, mesmos números
  assert.deepEqual(figuras(ui.$('m-resultado')), figCmp);
  assert.match(ui.$('m-a-sel').textContent, /Vaga A selecionada/); assert.match(ui.$('m-b-sel').textContent, /Vaga B selecionada/);   // seleções restauradas
  for (const id of ['h-resultado', 'e-resultado', 'm-resultado']) assert.match(ui.$(id).textContent, /Resultado salvo desta conversa: pesquisa feita em .*Nada foi consultado de novo ao reabrir/);   // 5.3: dado antigo identificado
  assert.equal(ui.$('h-mais').hidden, true);
  assert.ok(!ui.chamadas.slice(n).some(c => c.metodo === 'POST' && !c.url.startsWith('/sessoes')));
  // abrir uma análise específica pela linha do tempo leva à tela certa
  ui.$('nav-vagas').click();
  ui.linha().find(x => x.tipo === 'Evolução').abrir.click();
  assert.equal(ui.$('evo').hidden, false);
});

test('25: resposta tardia de uma conversa antiga não entra na conversa que está ativa', async () => {
  const ui = await abrir({ ponte: (u, o, orig) => (u === '/chat' ? dormir(400).then(orig) : orig()) });
  await ui.nova();
  ui.$('q').value = 'Graf Tardia Origem'; ui.$('btn').click();
  await esperar(() => /Graf Tardia Origem/.test(ui.titulo()) || ui.chamadas.some(c => c.url === '/chat'));
  const origem = ui.chamadas.find(c => c.url === '/chat').corpo.sessao_id;
  ui.$('s-nova').click();                                                                                       // troca de conversa com a análise ainda rodando
  await esperar(() => ui.status() === 'Nova conversa criada e salva.');
  assert.equal(ui.$('btn').disabled, false);                                                                    // a conversa nova está livre
  await esperar(() => /terminou depois que você trocou de conversa/.test(ui.status()), 8000);
  assert.match(ui.status(), /Foi salva na conversa de origem e não entrou nesta/);
  assert.equal(ui.d.querySelectorAll('.msg.bot figure').length, 0); assert.ok(!ui.$('chat').textContent.includes('Graf Tardia Origem')); // nada na conversa nova
  assert.equal(ui.titulo(), 'Nova conversa'); assert.equal(ui.linha().length, 0);
  const salva = (await api('GET', '/sessoes/' + origem)).dados;                                                 // e está na de origem
  assert.deepEqual(salva.interacoes.map(i => i.consulta), ['Graf Tardia Origem']);
  const nova = (await api('GET', '/sessoes')).dados.sessoes.find(s => s.titulo === 'Nova conversa');
  assert.equal(nova.total_interacoes, 0);
});

test('26/27: erros de abertura preservam a conversa atual; análise não salva é avisada e mantida na tela', async () => {
  let falha500 = false;
  const ui = await abrir({ ponte: (u, o, orig) => (falha500 && /^\/sessoes\/[0-9a-f]{32}$/.test(u) && (!o.method || o.method === 'GET') ? Promise.resolve(new Response('{"detail":"boom"}', { status: 500 })) : orig()) });
  await ui.nova(); await ui.chat('Graf Erro Atual'); await esperar(() => /nº 1/.test(ui.status()));
  const outra = (await api('POST', '/sessoes', { titulo: 'Conversa para falhar' })).dados;
  await ui.painel(); await esperar(() => ui.lista().some(x => x.titulo === 'Conversa para falhar') || (ui.$('s-hist').click(), false));
  falha500 = true;
  await ui.abrirSessao('Conversa para falhar');
  assert.match(ui.status(), /Não foi possível abrir a conversa: Erro 500|boom/); assert.equal(ui.titulo(), 'Graf Erro Atual');       // continua na atual
  assert.ok(ui.$('chat').textContent.includes('Graf Erro Atual'));
  falha500 = false;
  await api('DELETE', '/sessoes/' + outra.id);                                                                 // some no backend; a lista local ainda a mostra
  await ui.painel(); const item = ui.lista().find(x => x.titulo === 'Conversa para falhar'); item.abrir.click();
  await esperar(() => /Conversa não encontrada/.test(ui.status()));
  await esperar(() => !ui.lista().some(x => x.titulo === 'Conversa para falhar'));                             // a lista é atualizada
  assert.equal(ui.titulo(), 'Graf Erro Atual');
});

test('27b: se o backend não salva, a análise continua na tela e é marcada como NÃO salva', async () => {
  const ponte = async (u, o, orig) => { const r = await orig(); if (u !== '/chat' || !r.ok) return r; const j = await r.json(); j.salvo = false; j.interacao = null; j.aviso_historico = 'Não foi possível salvar a análise no histórico. Nada foi alterado.';
    return new Response(JSON.stringify(j), { status: 200, headers: { 'Content-Type': 'application/json' } }); };
  const ui = await abrir({ ponte });
  const bot = await ui.chat('Graf Nao Salva');
  assert.ok(figuras(bot).length >= 1);                                                                          // o resultado foi preservado na interface
  assert.match(ui.status(), /Atenção: esta análise NÃO foi salva no histórico\. Não foi possível salvar/); assert.ok(ui.$('s-status').classList.contains('erro'));
  assert.doesNotMatch(ui.status(), /Análise salva na conversa/); assert.equal(ui.linha().length, 0);           // nada de sucesso sem confirmação
});

test('27c: sem conseguir criar a conversa a análise é feita, sem sessao_id, e o aviso diz que não será salva', async () => {
  const ui = await abrir({ ponte: (u, o, orig) => (o.method === 'POST' && u === '/sessoes' ? Promise.resolve(new Response('{"detail":"x"}', { status: 500 })) : orig()) });
  const bot = await ui.chat('Graf Sem Historico');
  assert.ok(figuras(bot).length >= 1); assert.equal(ui.chamadas.find(c => c.url === '/chat').corpo.sessao_id, undefined);
  assert.match(ui.status(), /A análise será feita, mas não será salva/); assert.equal(ui.titulo(), 'nenhuma ativa');
});

test('28: renomear (persiste, mantém id e análises) e excluir (confirmação, só a escolhida, backend confirma)', async () => {
  let quebrar = false;
  const ui = await abrir({ ponte: (u, o, orig) => (quebrar && ['PATCH', 'DELETE'].includes(o.method) ? Promise.resolve(new Response('{"detail":"x"}', { status: 500 })) : orig()) });
  await ui.nova(); await ui.chat('Graf Renomear'); await esperar(() => /nº 1/.test(ui.status()));
  const id = ui.chamadas.find(c => c.url === '/chat').corpo.sessao_id;
  ui.$('s-renomear').click(); assert.equal(ui.$('s-input').hidden, false); assert.equal(ui.$('s-input').value, 'Graf Renomear');
  quebrar = true; ui.$('s-input').value = 'Novo nome'; ui.$('s-salvar-nome').click();
  await esperar(() => /Não foi possível renomear/.test(ui.status()));
  assert.equal(ui.titulo(), 'Graf Renomear'); assert.equal(ui.$('s-input').hidden, false);                    // falha: título antigo e campo aberto
  quebrar = false; ui.$('s-salvar-nome').click();
  await esperar(() => ui.status() === 'Conversa renomeada.');
  assert.equal(ui.titulo(), 'Novo nome'); assert.equal(ui.$('s-input').hidden, true);
  const s = (await api('GET', '/sessoes/' + id)).dados;
  assert.equal(s.sessao.titulo, 'Novo nome'); assert.equal(s.interacoes.length, 1);                            // mesmo id, mesmas análises
  // excluir: recusar a confirmação não faz nada
  const recusa = await abrir({ confirmar: false }); await recusa.painel();
  recusa.lista().find(x => x.titulo === 'Novo nome').excluir.click(); await dormir(60);
  assert.equal((await api('GET', '/sessoes/' + id)).status, 200);
  // falha do backend: nada some da tela
  quebrar = true; await ui.painel(); ui.lista().find(x => x.titulo === 'Novo nome').excluir.click();
  await esperar(() => /Não foi possível excluir/.test(ui.status())); assert.ok(ui.lista().some(x => x.titulo === 'Novo nome')); assert.equal(ui.titulo(), 'Novo nome');
  // sucesso: só a escolhida; a ativa é desativada e as telas limpas
  const outra = (await api('POST', '/sessoes', { titulo: 'Fica aqui' })).dados;
  quebrar = false; ui.lista().find(x => x.titulo === 'Novo nome').excluir.click();
  await esperar(() => ui.status() === 'Conversa excluída.');
  assert.equal(ui.titulo(), 'nenhuma ativa'); assert.equal(ui.msgs().length, 1);                               // só a mensagem de boas-vindas
  assert.equal((await api('GET', '/sessoes/' + id)).status, 404); assert.equal((await api('GET', '/sessoes/' + outra.id)).status, 200);
});

test('17: depois de atualizar o navegador a conversa ativa volta, vinda do backend', async () => {
  const ui = await abrir();
  await ui.nova(); await ui.chat('Graf Refresh Um'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.chat('Graf Refresh Dois'); await esperar(() => /nº 2/.test(ui.status()));
  const guardado = ui.guardado();
  assert.match(guardado['jobinsight-sessao-ativa'], /^[0-9a-f]{32}$/);                                         // só o id; os dados estão no backend
  assert.ok(!Object.values(guardado).some(v => v.includes('Graf Refresh Um') && v.length > 200));
  const novo = await abrir({ storage: guardado });
  await esperar(() => /Conversa aberta: 2 análise/.test(novo.status()));
  assert.equal(novo.titulo(), 'Graf Refresh Um');
  assert.deepEqual(novo.msgs().filter(m => m.classList.contains('user')).map(m => m.textContent), ['Graf Refresh Um', 'Graf Refresh Dois']);
  assert.ok(!novo.chamadas.some(c => c.metodo === 'POST' && c.url === '/chat'));
});

test('mesma consulta repetida de propósito vira duas análises na conversa', async () => {
  const ui = await abrir();
  await ui.nova(); await ui.chat('Graf Repetida'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.chat('Graf Repetida'); await esperar(() => /nº 2/.test(ui.status()));
  assert.deepEqual(ui.linha().map(x => x.consulta), ['Graf Repetida', 'Graf Repetida']);
  const uids = ui.chamadas.filter(c => c.url === '/chat').map(c => c.corpo.interacao_uid); assert.notEqual(uids[0], uids[1]);
});

test('histórico antigo do navegador é importado uma única vez', async () => {
  const antigo = [{ q: 'consulta do navegador antigo', d: { cargo: 'x', vagas_analisadas: 4, tecnologias: [{ nome: 'Python', vagas: 3, percentual: 75 }], diferenciais: [], soft_skills: [], niveis: { pleno: 2 }, avisos: [], vagas: [] } }];
  const ui = await abrir({ storage: { 'vagas-historico': JSON.stringify(antigo) } });
  await esperar(() => /Conversa aberta: 1 análise/.test(ui.status()));
  assert.equal(ui.titulo(), 'Conversas anteriores (importadas)'); assert.ok(ui.$('chat').textContent.includes('consulta do navegador antigo'));
  const g = ui.guardado(); assert.equal(g['jobinsight-legado-importado'], '1'); assert.ok(g['vagas-historico']);       // o original continua no navegador (cópia de segurança)
  const antes = (await api('GET', '/sessoes')).dados.sessoes.filter(s => s.titulo === 'Conversas anteriores (importadas)').length;
  const outra = await abrir({ storage: g });
  assert.equal(outra.chamadas.filter(c => c.url === '/sessoes/importar-legado').length, 0);
  assert.equal((await api('GET', '/sessoes')).dados.sessoes.filter(s => s.titulo === 'Conversas anteriores (importadas)').length, antes);
});

test('segurança: títulos e consultas com HTML aparecem como texto em todo o histórico', async () => {
  const ui = await abrir();
  await ui.nova(); await ui.chat('Graf <img src=x onerror="window.__xss=1"> teste'); await esperar(() => /nº 1/.test(ui.status()));
  await ui.painel();
  await esperar(() => ui.titulo().includes('<img'));
  assert.equal(ui.d.querySelectorAll('#s-barra img, #s-painel img, #s-lista img, #s-linha img').length, 0);
  assert.ok(ui.titulo().includes('<img src=x onerror="window.__xss=1">'));
  await dormir(80); assert.equal(ui.w.__xss, undefined);
});
