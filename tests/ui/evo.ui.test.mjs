// Testes de interface da tela "Evolução por senioridade": página real (jsdom) + backend real + provedor SIMULADO.
// Todas as vagas são SINTÉTICAS (servidor_ui.py); nenhum número aqui é resultado de mercado.
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
const procs = [];
let base, baseSemChave;
const portaLivre = () => new Promise(res => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });
const dormir = ms => new Promise(r => setTimeout(r, ms));
async function esperar(cond, ms = 6000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await cond()) return; await dormir(15); }
  throw new Error('timeout esperando: ' + cond.toString());
}
async function subir(extra = {}) {
  const porta = await portaLivre();
  const env = { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-evo-')), 'e.db'), ...extra };
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
    abrirEvo: async () => { $('nav-evo').click(); await dormir(40); },
    status: () => $('e-status').textContent,
    texto: () => $('e-resultado').textContent,
    analisar: async cargo => {
      $('e-cargo').value = cargo; $('e-analisar').click();
      await esperar(() => !/Coletando e analisando/.test($('e-status').textContent));
    },
    posts: () => chamadas.filter(c => c.metodo === 'POST' && c.url === '/evolucao'),
    linhas: titulo => [...d.querySelectorAll('#e-resultado table')].flatMap(t => [...t.querySelectorAll('tbody tr')].map(tr => [...tr.children].map(td => td.textContent))).filter(r => r[0] === titulo),
  };
  return ui;
}
const limparPerfil = async habilidades => fetch(base + '/habilidades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ habilidades }) });

test('estado inicial, navegação e validação: nada é chamado sem cargo', async () => {
  await limparPerfil([]);
  const ui = await abrir();
  await ui.abrirEvo();
  assert.equal(ui.$('evo').hidden, false); assert.equal(ui.$('chat').hidden, true);
  assert.equal(ui.$('nav-evo').getAttribute('aria-current'), 'page');
  assert.match(ui.$('e-inicial').textContent, /Nenhuma análise realizada ainda/);
  assert.equal(ui.$('e-resultado').hidden, true);
  assert.match(ui.$('e-estimativa').textContent, /Informe um cargo/);
  ui.$('e-analisar').click();
  assert.match(ui.status(), /Informe um cargo/); assert.ok(ui.$('e-status').classList.contains('erro'));
  assert.equal(ui.posts().length, 0);
  ui.$('e-voltar').click();
  assert.equal(ui.$('evo').hidden, true); assert.equal(ui.$('chat').hidden, false);
  assert.equal(ui.$('nav-vagas').getAttribute('aria-current'), 'page');
});

test('estimativa de consumo antes de iniciar', async () => {
  const ui = await abrir();
  await ui.abrirEvo();
  ui.$('e-cargo').value = 'Desenvolvedor React Native'; ui.$('e-cargo').dispatchEvent(new ui.w.Event('input'));
  await esperar(() => /até 6 requisição/.test(ui.$('e-estimativa').textContent));
  assert.match(ui.$('e-estimativa').textContent, /3 consultas \(júnior, pleno e sênior\) × 2 página\(s\)/);
  assert.match(ui.$('e-estimativa').textContent, /páginas em cache \(válidas por 24 h\) não gastam/);
  ui.$('e-paginas').value = '3'; ui.$('e-paginas').dispatchEvent(new ui.w.Event('change'));
  await esperar(() => /até 9 requisição/.test(ui.$('e-estimativa').textContent));
});

test('análise completa: cobertura, classificação, comparação em p.p., rankings e leitura dos dados', async () => {
  await limparPerfil([]);
  const ui = await abrir();
  await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  assert.equal(ui.status(), 'Análise concluída.');
  assert.equal(ui.posts().length, 1); { const { sessao_id, interacao_uid, ...resto } = ui.posts()[0].corpo; assert.deepEqual(resto, { cargo: 'Desenvolvedor React Native Alfa', paginas: 2 }); assert.match(sessao_id, /^[0-9a-f]{32}$/); assert.ok(interacao_uid.length >= 8); }
  assert.equal(ui.$('e-resultado').hidden, false); assert.equal(ui.$('e-inicial').hidden, true);
  const t = ui.texto();
  assert.match(t, /Dados coletados agora: 6 requisição\(ões\) usada\(s\), 0 página\(s\) vieram do cache/);
  assert.match(t, /30 vaga\(s\) retornada\(s\) pelo provedor · 30 única\(s\) · 29 no contexto · 27 classificada\(s\) · 26 analisada\(s\) nos três níveis/);
  assert.match(t, /1 estágio\/trainee, 0 liderança\/gestão, 0 especialista\/arquitetura/);
  assert.match(t, /Não classificadas: 2 \(1 com informações conflitantes, 1 com informação insuficiente\)\. 1 fora do contexto da pesquisa/);
  assert.deepEqual(ui.linhas('Júnior')[0].slice(0, 4), ['Júnior', '12', '12', 'adequada']);
  assert.deepEqual(ui.linhas('Pleno')[0].slice(0, 4), ['Pleno', '10', '10', 'adequada']);
  assert.deepEqual(ui.linhas('Sênior')[0].slice(0, 4), ['Sênior', '4', '4', 'baixa (indicativa)']);
  assert.match(t, /Cobertura baixa no nível sênior: 4 vaga\(s\) analisada\(s\) \(adequado: 10\+\)/);
  assert.match(t, /1 vaga\(s\) não citam a tecnologia do contexto \(React Native\)/);
  // comparação em pontos percentuais, não em contagens
  const ts = ui.linhas('TypeScript')[0];
  assert.match(ts[1], /^16\.7% \(2\/12\)/); assert.match(ts[2], /^40% \(4\/10\)/); assert.match(ts[3], /^75% \(3\/4\)/);
  assert.equal(ts[4], '+23.3 p.p.'); assert.equal(ts[5], '+35 p.p.');
  assert.match(ts[1], /obrig\. 2 · dif\. 0/);
  assert.match(ui.linhas('Docker')[0][1], /obrig\. 0 · dif\. 2/);   // diferencial é mostrado como diferencial
  assert.match(t, /Habilidades comuns aos três níveis/);
  assert.match(t, /JavaScript: júnior 100% → pleno 100% → sênior 100%/);
  assert.match(t, /TypeScript: júnior 16\.7% → pleno 40% → sênior 75% \(\+35 p\.p\.\)/);
  assert.match(t, /indicativo: amostra pequena/);
  assert.match(t, /Ganham relevância de júnior para pleno/);
  assert.match(t, /Aparecem menos de pleno para sênior.*Git: júnior 75% → pleno 70% → sênior 25% \(-45 p\.p\.\)/s);   // queda aparece como queda
  assert.doesNotMatch(t, /exclusiv/i);
  assert.match(t, /Ranking por nível/); assert.match(t, /TypeScript — 40% \(4\/10\) · obrigatória em 4 · diferencial em 0/);
  assert.match(t, /Experiência exigida/); assert.ok(ui.linhas('Pleno').some(r => r.includes('não identificada')));
  assert.match(t, /Responsabilidades citadas/);
  assert.match(t, /Observado diretamente.*Inferido da frequência.*Incerto/s);
  assert.match(t, /Seu perfil ainda não tem habilidades cadastradas\. A análise acima não depende dele/);
});

test('repetir a análise não duplica e é identificada como dados em cache', async () => {
  const ui = await abrir();
  await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  const t = ui.texto();
  assert.match(t, /Dados armazenados em cache \(nenhuma requisição nova; válidos por até 24 h\)/);
  assert.match(t, /Resultados vindos do cache/);
  assert.match(t, /30 vaga\(s\) retornada\(s\) pelo provedor · 30 única\(s\)/);
  assert.equal(ui.d.querySelectorAll('#e-resultado h3').length, 1);
  await ui.analisar('Desenvolvedor React Native Alfa');  // de novo, na mesma tela
  assert.equal(ui.d.querySelectorAll('#e-resultado h3').length, 1);
  assert.equal(ui.d.querySelectorAll('#e-resultado table').length, ui.d.querySelectorAll('#e-resultado table').length);
});

test('perfil: requisitos do próximo nível "não cadastrados no perfil", sem afirmar desconhecimento', async () => {
  await limparPerfil(['js', 'Git']);
  const ui = await abrir();
  await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  const t = ui.texto();
  assert.match(t, /Usando as 2 habilidade\(s\) do seu perfil/);
  assert.match(t, /“Não cadastrada” não significa que você não saiba usar/);
  assert.match(t, /Júnior → Pleno \(10 vaga\(s\) pleno analisada\(s\); cobertura adequada;/);
  const linhas = [...ui.d.querySelectorAll('#e-resultado .lac')].map(x => x.textContent);
  const ts = linhas.filter(l => l.startsWith('TypeScript'));
  assert.equal(ts.length, 2);
  assert.match(ts[0], /Aparece em 4 de 10 vagas pleno analisadas \(40%\); obrigatória em 4, diferencial em 0; \+23\.3 p\.p\. em relação às vagas júnior\. Não cadastrada no perfil\./);
  assert.match(ts[1], /Aparece em 3 de 4 vagas sênior analisadas \(75%\).*\+35 p\.p\. em relação às vagas pleno/);
  assert.ok(!linhas.some(l => l.startsWith('JavaScript') || l.startsWith('Git')));   // as já cadastradas não são listadas como lacuna
  assert.doesNotMatch(t, /você não sabe|desconhece/i);
  await limparPerfil([]);
});

test('segurança: títulos de vagas aparecem como texto; nada é executado', async () => {
  const ui = await abrir();
  await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  const box = ui.$('e-resultado');
  assert.equal(box.querySelectorAll('img, script').length, 0);
  assert.ok(box.textContent.includes('<img src=x onerror="window.__xss=1">'));
  await dormir(100);
  assert.equal(ui.w.__xss, undefined);
  const det = box.querySelector('details');
  assert.match(det.querySelector('summary').textContent, /Como cada vaga foi classificada \(30\)/);
  assert.match(det.textContent, /Título identificado explicitamente como Júnior/);
  assert.match(det.textContent, /Informações conflitantes: o título cita mais de um nível \(Júnior e Pleno\)/);
  assert.match(det.textContent, /Estagiário React Native.*Estágio\/trainee/);
  assert.match(det.textContent, /Desenvolvedor Java Sênior.*fora do contexto/);
});

test('estados de erro: sem vagas, cota, provedor recusa, rede, credenciais ausentes', async () => {
  let ui = await abrir(); await ui.abrirEvo();
  await ui.analisar('Vazio Evo');
  assert.match(ui.texto(), /Nenhuma vaga encontrada para esse cargo/); assert.match(ui.status(), /nenhuma vaga encontrada/);
  assert.match(ui.texto(), /Nenhuma vaga júnior classificada e analisada/);

  ui = await abrir(); await ui.abrirEvo(); await ui.analisar('Cota Evo');
  assert.ok(ui.$('e-status').classList.contains('erro')); assert.match(ui.status(), /Limite de requisições/); assert.equal(ui.$('e-resultado').hidden, true);

  ui = await abrir(); await ui.abrirEvo(); await ui.analisar('Falha Evo');
  assert.match(ui.status(), /recusou a chave/); assert.doesNotMatch(ui.status(), /chave-de-teste/);

  ui = await abrir({ ponte: (u, o, orig) => (u === '/evolucao' ? Promise.reject(new TypeError('x')) : orig()) });
  await ui.abrirEvo(); await ui.analisar('Desenvolvedor React Native Beta');
  assert.match(ui.status(), /falha de conexão/); assert.ok(ui.$('e-status').classList.contains('erro')); assert.equal(ui.$('e-analisar').disabled, false);

  ui = await abrir({ url: baseSemChave }); await ui.abrirEvo();
  ui.$('e-cargo').value = 'Desenvolvedor React Native'; ui.$('e-cargo').dispatchEvent(new ui.w.Event('input'));
  await esperar(() => /faltam as credenciais/.test(ui.$('e-estimativa').textContent));
  await ui.analisar('Desenvolvedor React Native');
  assert.match(ui.status(), /busca real está indisponível/); assert.equal(ui.$('e-resultado').hidden, true);
});

test('ausência de vagas em níveis: comparações dependentes não são calculadas e isso é dito', async () => {
  const ui = await abrir(); await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native SoJunior');
  const t = ui.texto();
  assert.match(t, /Nenhuma vaga pleno classificada e analisada: comparações com esse nível não foram calculadas/);
  assert.match(t, /Nenhuma vaga sênior classificada e analisada/);
  assert.match(t, /Não calculado: Pleno: 0 vaga\(s\) analisada\(s\)/);
  assert.deepEqual(ui.linhas('Pleno')[0].slice(0, 4), ['Pleno', '0', '0', 'sem vagas']);
  assert.match(t, /Sem dados para este nível/);
  assert.match(t, /algum nível tem menos de 10 vagas analisadas/);
});

test('quantidade insuficiente: dados descritivos, sinalizados como indicativos', async () => {
  const ui = await abrir(); await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Poucas');
  const t = ui.texto();
  assert.deepEqual(ui.linhas('Júnior')[0].slice(0, 4), ['Júnior', '2', '2', 'muito baixa']);
  assert.match(t, /Cobertura insuficiente no nível júnior: 2 vaga\(s\) analisada\(s\)/);
  assert.match(t, /Não calculado: Júnior: 2 vaga\(s\) analisada\(s\); Pleno: 2 vaga\(s\) analisada\(s\) \(mínimo para comparar: 3\)/);
  assert.match(t, /Atenção: algum nível tem menos de 10 vagas analisadas/);
  assert.ok(ui.linhas('TypeScript').length === 1);   // o dado não é escondido
});

test('dados incompatíveis: nenhuma vaga com nível identificável', async () => {
  const ui = await abrir(); await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native SemNivel');
  const t = ui.texto();
  assert.match(t, /Nenhuma vaga pôde ser classificada como júnior, pleno ou sênior; os dados são incompatíveis com a comparação por nível/);
  assert.match(t, /Mais da metade das vagas não indica o nível de forma confiável/);
  assert.doesNotMatch(t, /Comparação entre níveis/);
  assert.match(t, /Informação insuficiente para classificar/);
});

test('extração incompleta e resultado parcial aparecem na tela', async () => {
  const ponte = async (u, o, orig) => {
    const r = await orig();
    if (u !== '/evolucao' || !r.ok) return r;
    const d = await r.json();
    d.contagens.analise_incompleta = 3; d.niveis.pleno.analise_incompleta = 3;
    d.avisos.push('3 vaga(s) com análise incompleta (a IA falhou e o dicionário foi usado).');
    d.status_consultas.senior = 'nao_consultada';
    d.avisos.push('Consultas não realizadas por limite de cota: sênior. Os resultados obtidos foram preservados.');
    return new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  const ui = await abrir({ ponte }); await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  assert.match(ui.texto(), /3 vaga\(s\) com análise incompleta \(a IA falhou e o dicionário foi usado\)/);
  assert.equal(ui.linhas('Pleno')[0][4], '3');
  assert.match(ui.texto(), /Consultas não realizadas por limite de cota: sênior/);
  assert.equal(ui.status(), 'Análise concluída com resultados parciais.');
});

test('busca em andamento: resultado anterior some, cliques repetidos geram uma chamada só', async () => {
  const ui = await abrir({ ponte: (u, o, orig) => (u === '/evolucao' ? dormir(250).then(orig) : orig()) });
  await ui.abrirEvo();
  await ui.analisar('Desenvolvedor React Native Alfa');
  assert.equal(ui.$('e-resultado').hidden, false);
  ui.$('e-cargo').value = 'Desenvolvedor React Native Gama';
  ui.$('e-analisar').click(); ui.$('e-analisar').click(); ui.$('e-analisar').click();
  assert.match(ui.status(), /Coletando e analisando vagas dos três níveis/);
  assert.equal(ui.$('e-resultado').hidden, true);            // dados antigos não ficam como se fossem do novo cargo
  assert.equal(ui.$('e-analisar').disabled, true);
  await esperar(() => ui.status() === 'Análise concluída.');
  assert.equal(ui.posts().length, 2);                        // uma da Alfa + uma da Gama
  assert.match(ui.$('e-resultado').querySelector('h3').textContent, /Gama/);
});
