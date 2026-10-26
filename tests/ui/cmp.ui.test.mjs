// Testes de interface da tela "Comparar vagas": página real (jsdom) + backend real + provedor SIMULADO (vagas SINTÉTICAS).
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
  const env = { ...process.env, UI_PORT: String(porta), CACHE_DB: join(mkdtempSync(join(tmpdir(), 'ji-cmp-')), 'c.db'), ...extra };
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
    abrir: async () => { $('nav-cmp').click(); await dormir(40); },
    estado: () => $('m-estado').textContent,
    status: () => $('m-status').textContent,
    texto: () => $('m-resultado').textContent,
    buscar: async (L, consulta) => {
      $(`m-${L}-consulta`).value = consulta; $(`m-${L}-buscar`).click();
      await esperar(() => !/Buscando vagas/.test($(`m-${L}-busca-msg`).textContent));
    },
    opcoes: L => [...d.querySelectorAll(`#m-${L}-lista .opcao`)],
    selecionar: (L, i) => ui.opcoes(L)[i].querySelector('button').click(),
    comparar: async () => { $('m-comparar').click(); await esperar(() => !/Comparação em andamento/.test($('m-status').textContent)); },
    posts: () => chamadas.filter(c => c.metodo === 'POST' && c.url === '/comparar'),
    manual: (L, t, desc, extra = {}) => {
      $(`m-${L}-modo`).value = 'manual'; $(`m-${L}-modo`).dispatchEvent(new w.Event('change'));
      $(`m-${L}-titulo`).value = t; $(`m-${L}-descricao`).value = desc;
      $(`m-${L}-empresa`).value = extra.empresa || ''; $(`m-${L}-link`).value = extra.link || '';
      $(`m-${L}-usar`).click();
    },
  };
  return ui;
}
const salvarPerfil = habilidades => fetch(base + '/habilidades', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ habilidades }) });
const DESC_B = 'Requisitos: Python, Go. ' + 'Contexto da vaga com informações de apoio para a análise. '.repeat(8);

test('estados de seleção: nenhuma, só A, mesma vaga, duas vagas', async () => {
  await salvarPerfil([]);
  const ui = await abrir(); await ui.abrir();
  assert.equal(ui.$('cmp').hidden, false); assert.equal(ui.$('chat').hidden, true);
  assert.equal(ui.$('nav-cmp').getAttribute('aria-current'), 'page');
  assert.match(ui.estado(), /Nenhuma vaga selecionada/); assert.equal(ui.$('m-comparar').disabled, true);
  assert.equal(ui.chamadas.filter(c => c.url !== '/status' && !c.url.startsWith('/sessoes')).length, 0);   // abrir a tela não faz nenhuma chamada ao provedor (só o histórico local)
  await ui.buscar('a', 'Cmp Backend'); ui.selecionar('a', 0);
  assert.match(ui.estado(), /Somente a vaga A selecionada\. Falta escolher a vaga B/); assert.equal(ui.$('m-comparar').disabled, true);
  await ui.buscar('b', 'Cmp Backend'); ui.selecionar('b', 0);                  // o mesmo anúncio nos dois lados
  assert.match(ui.estado(), /mesmo anúncio/); assert.equal(ui.$('m-comparar').disabled, true);
  ui.selecionar('b', 1);
  assert.match(ui.estado(), /Duas vagas selecionadas: pronto para comparar/); assert.equal(ui.$('m-comparar').disabled, false);
  assert.equal(ui.posts().length, 0);
});

test('D1: resumo das duas vagas antes de comparar (título, empresa, local, origem)', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend');
  assert.equal(ui.opcoes('a').length, 4); assert.equal(ui.opcoes('b').length, 2);
  assert.match(ui.opcoes('b')[0].textContent, /Gama · São Paulo, SP, BR/);
  ui.selecionar('a', 0); ui.selecionar('b', 1);
  assert.match(ui.$('m-a-sel').textContent, /Vaga A selecionada.*Desenvolvedor Back-end Pleno.*Alfa · São Paulo, SP, BR.*Anúncio de um provedor de vagas/s);
  assert.match(ui.$('m-b-sel').textContent, /Vaga B selecionada.*Desenvolvedor Front-end Pleno.*Gama/s);
  assert.equal(ui.$('m-a-sel').querySelector('a').getAttribute('href'), 'https://alfa.test/cb1');
  assert.match(ui.$('m-a-busca-msg').textContent, /4 vaga\(s\) encontrada\(s\)/);
  ui.$('m-a-consulta').value = 'Cmp Backend'; ui.$('m-a-consulta').dispatchEvent(new ui.w.Event('input'));
  await esperar(() => /^Esta busca usa até 1 requisição/.test(ui.$('m-a-est').textContent));
});

test('comparação completa de áreas diferentes: síntese, individual e consolidada', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend');
  ui.selecionar('a', 0); ui.selecionar('b', 0);
  await ui.comparar();
  assert.equal(ui.status(), 'Comparação concluída.');
  assert.deepEqual(Object.keys(ui.posts()[0].corpo), ['a', 'b', 'sessao_id', 'interacao_uid']);   // + a conversa que recebe o resultado
  assert.match(ui.posts()[0].corpo.sessao_id, /^[0-9a-f]{32}$/);
  assert.deepEqual(ui.posts()[0].corpo.a, { tipo: 'busca', consulta: 'Cmp Backend', pais: 'br', paginas: 1, id: 'id:cb1' });
  const t = ui.texto();
  assert.match(t, /Vagas vindas do cache.*nenhuma requisição nova/);
  assert.match(t, /Nenhuma habilidade técnica em comum foi identificada\./);
  assert.match(t, /As duas vagas indicam o mesmo nível: Pleno\./);
  assert.match(t, /Vaga A: .*PostgreSQL.*Vaga B: .*React/s);
  assert.match(t, /não indica qual vaga é melhor/);
  const tags = [...ui.d.querySelectorAll('#m-resultado .vaga .tag')].map(x => x.textContent);
  assert.deepEqual(tags, ['Vaga A', 'Vaga B']);
  const cards = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.match(cards[0].textContent, /Desenvolvedor Back-end Pleno.*Alfa/s); assert.match(cards[1].textContent, /Desenvolvedor Front-end Pleno.*Gama/s);
  assert.doesNotMatch(cards[0].textContent, /Angular|React/); assert.doesNotMatch(cards[1].textContent, /PostgreSQL|Kafka/);   // nada vaza entre as vagas
  assert.match(cards[0].textContent, /Provedor: jsearch · publicada: não informada/);
  assert.match(cards[0].textContent, /Senioridade.*Pleno \(explícita\)/s);
  assert.match(cards[0].textContent, /Experiência mínima.*Não identificada na descrição/s);
  assert.match(t, /Identificadas somente na vaga A \(não identificadas na descrição da vaga B\)/);
  assert.match(t, /Diferenças em requisitos obrigatórios/);
  assert.match(t, /Obrigatória na vaga A, sem equivalente obrigatório na B: PostgreSQL — não identificada na descrição da outra vaga/);
  assert.match(t, /Sem pontuação: Nenhuma habilidade cadastrada no perfil/);     // sem perfil: segue funcionando
  assert.match(cards[0].querySelector('details').textContent, /Evidências no texto original/);
  assert.match(cards[0].querySelectorAll('details')[1].textContent, /Requisitos: Python, PostgreSQL, Docker/);
  assert.match(cards[0].querySelectorAll('details')[0].textContent, /Python: .*Requisitos: Python/s);   // trecho original que sustenta o requisito
});

test('mesma área, níveis diferentes: comuns com classificação, níveis e relacionadas', async () => {
  await salvarPerfil(['Python', 'Docker']);
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Backend');
  ui.selecionar('a', 0); ui.selecionar('b', 1);
  await ui.comparar();
  const t = ui.texto();
  assert.match(t, /Níveis diferentes: vaga A Pleno \(explícita\) × vaga B Sênior \(explícita\)/);
  const linhas = [...ui.d.querySelectorAll('#m-resultado table tbody tr')].map(tr => [...tr.children].map(td => td.textContent));
  assert.deepEqual(linhas, [['Python', 'obrigatória', 'obrigatória']]);
  assert.match(t, /Kafka \(desejável\)/); assert.match(t, /Terraform \(desejável\)/);
  assert.match(t, /≈ 57% dos requisitos identificados constam no seu perfil/); assert.match(t, /≈ 29% dos requisitos identificados constam no seu perfil/);
  assert.match(t, /É uma estimativa de cobertura; não indica qual vaga é melhor/);
  assert.match(t, /Obrigatórios ainda não cadastrados no perfil.*AWS.*Kubernetes/s);
  assert.doesNotMatch(t, /vencedor|melhor vaga|recomendamos/i);
  await salvarPerfil([]);
});

test('segurança: textos e links de anúncios e da entrada manual são tratados como não confiáveis', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend');
  ui.selecionar('a', 2);                                     // título com HTML e empresa com HTML
  ui.manual('b', 'Vaga <script>window.__xss=2</script> manual', DESC_B, { empresa: '<b>Contoso</b>', link: 'https://contoso.test/v' });
  assert.match(ui.$('m-b-sel').textContent, /Inserida manualmente: texto digitado por você, não verificado/);
  await ui.comparar();
  const box = ui.$('m-resultado');
  assert.equal(box.querySelectorAll('img, script, b').length, 0);
  assert.ok(box.textContent.includes('<img src=x onerror="window.__xss=1">') && box.textContent.includes('<script>window.__xss=2</script>'));
  await dormir(100);
  assert.equal(ui.w.__xss, undefined);
  const hrefs = [...box.querySelectorAll('a')].map(a => a.getAttribute('href'));
  assert.ok(hrefs.length >= 1 && hrefs.every(h => /^https?:\/\//.test(h)) && hrefs.includes('https://contoso.test/v'));   // só http(s)
  assert.match(box.textContent, /Inserida manualmente \(não verificada\)/);
  box.querySelectorAll('a').forEach(a => { assert.equal(a.target, '_blank'); assert.match(a.rel, /noopener/); });
});

test('link javascript: de anúncio nunca vira link; entrada manual valida campos antes de enviar', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); ui.selecionar('a', 1);                 // cb2 tem link javascript:
  assert.equal(ui.$('m-a-sel').querySelectorAll('a').length, 0);
  ui.manual('b', '', DESC_B);                                                  assert.match(ui.$('m-b-manual-msg').textContent, /Informe o título/);
  ui.manual('b', 'T', '');                                                     assert.match(ui.$('m-b-manual-msg').textContent, /Cole a descrição/);
  ui.manual('b', 'T', DESC_B, { link: 'javascript:alert(1)' });                assert.match(ui.$('m-b-manual-msg').textContent, /http:\/\/ ou https:\/\//);
  ui.manual('b', 'T', 'd'.repeat(8001));                                       assert.match(ui.$('m-b-manual-msg').textContent, /no máximo 8000/);
  assert.equal(ui.$('m-b-sel').querySelector('.opcao'), null);                 // nada foi selecionado
  assert.match(ui.estado(), /Somente a vaga A selecionada/);
});

test('D2: respostas de busca de um lado nunca caem no outro', async () => {
  const ponte = (u, o, orig) => (u === '/comparar/buscar' && JSON.parse(o.body).consulta === 'Cmp Backend' ? dormir(300).then(orig) : orig());
  const ui = await abrir({ ponte }); await ui.abrir();
  ui.$('m-a-consulta').value = 'Cmp Backend'; ui.$('m-a-buscar').click();     // A demora
  ui.$('m-b-consulta').value = 'Cmp Frontend'; ui.$('m-b-buscar').click();    // B responde antes
  await esperar(() => ui.opcoes('b').length === 2);
  assert.equal(ui.opcoes('a').length, 0); assert.match(ui.$('m-a-busca-msg').textContent, /Buscando vagas/);
  await esperar(() => ui.opcoes('a').length === 4);
  assert.match(ui.opcoes('a')[0].textContent, /Back-end/); assert.ok(ui.opcoes('b').every(o => /Front-end/.test(o.textContent)));
  ui.selecionar('a', 0);
  assert.equal(ui.$('m-b-sel').querySelector('.opcao'), null);                 // selecionar em A não mexe em B
  assert.match(ui.$('m-a-sel').textContent, /Back-end/);
});

test('D3: nova seleção descarta o resultado anterior; nova comparação não mistura dados', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend');
  ui.selecionar('a', 0); ui.selecionar('b', 0);
  await ui.comparar();
  assert.equal(ui.$('m-resultado').hidden, false); assert.match(ui.texto(), /Alfa/);
  ui.selecionar('a', 1);                                                       // troca a vaga A
  assert.equal(ui.$('m-resultado').hidden, true); assert.equal(ui.texto(), ''); assert.equal(ui.status(), '');
  await ui.comparar();
  const t = ui.texto();
  assert.equal(ui.d.querySelector('#m-resultado > .card > h3').textContent, 'Resultado da comparação');
  assert.match(t, /Desenvolvedor Back-end Sênior.*Beta/s); assert.doesNotMatch(t, /Alfa|PostgreSQL/);      // nada da vaga A anterior
  assert.equal(ui.posts().length, 2);
  ui.$('m-limpar').click();                                                    // "Refazer com outras vagas"
  assert.equal(ui.$('m-resultado').hidden, true); assert.match(ui.estado(), /Nenhuma vaga selecionada/); assert.equal(ui.opcoes('a').length, 0);
});

test('D4: resultado parcial é preservado e identificado (vaga sem descrição)', async () => {
  const ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend');
  ui.selecionar('a', 0);
  await ui.buscar('b', 'Cmp Backend'); ui.selecionar('b', 3);                  // B = vaga sem descrição
  assert.match(ui.$('m-b-sel').textContent, /Sem descrição: a análise de requisitos não será possível/);
  await ui.comparar();
  const t = ui.texto();
  assert.equal(ui.status(), 'Comparação parcial: veja os avisos.');
  assert.match(t, /Resultado parcial da comparação/); assert.match(t, /Atenção: esta comparação está incompleta/);
  assert.match(t, /A vaga não tem descrição: só os dados de identificação estão disponíveis/);
  assert.match(t, /Comparação consolidada indisponível: A comparação de requisitos exige a análise das duas vagas/);
  const cards = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.match(cards[0].textContent, /PostgreSQL/);                           // A preservada
  assert.match(cards[1].textContent, /Dev Sem Descrição.*Delta/s);            // B identificada, sem requisitos inventados
  assert.match(cards[1].textContent, /Nenhuma habilidade técnica identificada/);
  assert.match(t, /Informações indisponíveis ou limitadas/);
});

test('D4: uma vaga que deixou de existir nos resultados — A preservada, B com falha identificada', async () => {
  const ponte = (u, o, orig) => {
    if (u === '/comparar') { const c = JSON.parse(o.body); c.b.id = 'id:nao-existe'; o = { ...o, body: JSON.stringify(c) }; }
    return u === '/comparar' ? fetch(new URL(u, base), o) : orig();
  };
  const ui = await abrir({ ponte }); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend');
  ui.selecionar('a', 0); ui.selecionar('b', 0);
  await ui.comparar();
  const t = ui.texto();
  assert.match(t, /Não foi possível carregar a vaga B: Esta vaga não aparece mais nos resultados/);
  const cards = [...ui.d.querySelectorAll('#m-resultado .vaga')];
  assert.match(cards[1].textContent, /Não foi possível carregar esta vaga/); assert.match(cards[0].textContent, /PostgreSQL/);
  assert.match(t, /Comparação consolidada indisponível/); assert.doesNotMatch(t, /Síntese/);
});

test('D5: erros não deixam a tela presa; credenciais, cota e provedor', async () => {
  let ui = await abrir({ ponte: (u, o, orig) => (u === '/comparar' ? Promise.reject(new TypeError('x')) : orig()) }); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend'); ui.selecionar('a', 0); ui.selecionar('b', 0);
  await ui.comparar();
  assert.match(ui.status(), /falha de conexão/); assert.ok(ui.$('m-status').classList.contains('erro'));
  assert.equal(ui.$('m-comparar').disabled, false); assert.equal(ui.$('m-resultado').hidden, true);

  ui = await abrir(); await ui.abrir();
  await ui.buscar('a', 'Cmp Cota');
  assert.match(ui.$('m-a-busca-msg').textContent, /Limite de requisições/); assert.equal(ui.$('m-a-buscar').disabled, false);
  await ui.buscar('b', 'Cmp Falha');
  assert.match(ui.$('m-b-busca-msg').textContent, /recusou a chave/); assert.doesNotMatch(ui.$('m-b-busca-msg').textContent, /chave-de-teste/);
  await ui.buscar('a', 'Cmp Vazio');
  assert.match(ui.$('m-a-busca-msg').textContent, /Nenhuma vaga encontrada para essa consulta/);

  ui = await abrir({ url: baseSemChave }); await ui.abrir();
  ui.$('m-a-consulta').value = 'Cmp Backend'; ui.$('m-a-consulta').dispatchEvent(new ui.w.Event('input'));
  await esperar(() => /faltam as credenciais/.test(ui.$('m-a-est').textContent));
  await ui.buscar('a', 'Cmp Backend');
  assert.match(ui.$('m-a-busca-msg').textContent, /busca real está indisponível/); assert.equal(ui.opcoes('a').length, 0);
  ui.manual('a', 'Vaga manual A', 'Requisitos: Python, SQL. ' + 'Contexto da vaga com informações de apoio para a análise. '.repeat(8));
  ui.manual('b', 'Vaga manual B', DESC_B);
  await ui.comparar();                                                         // duas vagas manuais funcionam sem credenciais
  assert.equal(ui.status(), 'Comparação concluída.'); assert.match(ui.texto(), /Python.*obrigatória.*obrigatória/s);
});

test('comparação em andamento: estado, botão bloqueado e uma única chamada', async () => {
  const ui = await abrir({ ponte: (u, o, orig) => (u === '/comparar' ? dormir(250).then(orig) : orig()) }); await ui.abrir();
  await ui.buscar('a', 'Cmp Backend'); await ui.buscar('b', 'Cmp Frontend'); ui.selecionar('a', 0); ui.selecionar('b', 0);
  ui.$('m-comparar').click(); ui.$('m-comparar').click(); ui.$('m-comparar').click();
  assert.match(ui.status(), /Comparação em andamento/); assert.equal(ui.$('m-comparar').disabled, true);
  await esperar(() => ui.status() === 'Comparação concluída.');
  assert.equal(ui.posts().length, 1); assert.equal(ui.$('m-comparar').disabled, false);
});

test('vagas escolhidas em "Vagas por habilidades" entram na comparação sem nova busca', async () => {
  await salvarPerfil([]);
  const ui = await abrir(); await ui.abrir();
  ui.$('nav-hab').click(); await dormir(60);
  ui.$('h-input').value = 'Python'; ui.$('h-add').click(); await esperar(() => ui.d.querySelectorAll('#h-chips .chip').length === 1);
  ui.$('h-buscar').click(); await esperar(() => /Busca concluída/.test(ui.$('h-status').textContent));
  const botoes = [...ui.d.querySelectorAll('#h-resultado button')].filter(b => /Usar como vaga A/.test(b.textContent));
  assert.ok(botoes.length > 0);
  botoes[0].click();
  assert.match(ui.$('h-status').textContent, /Vaga A definida: “.*”\. Veja “Vagas para comparar”/);
  ui.$('nav-cmp').click(); await dormir(40);
  assert.match(ui.$('m-a-sel').textContent, /Vaga A selecionada/);
  ui.manual('b', 'Vaga manual B', DESC_B);
  const antes = ui.chamadas.filter(c => c.url === '/comparar/buscar').length;
  await ui.comparar();
  assert.equal(ui.status(), 'Comparação concluída.');
  assert.equal(ui.chamadas.filter(c => c.url === '/comparar/buscar').length, antes);
  assert.match(ui.texto(), /Vagas vindas do cache.*nenhuma requisição nova/);
  const corpo = ui.posts()[0].corpo.a;
  assert.equal(corpo.tipo, 'busca'); assert.ok(corpo.consulta && corpo.id.startsWith('id:'));
});
