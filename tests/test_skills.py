"""Grupo B — normalização e canonicalização de habilidades."""
import pytest

from app import skills
from app.keywords import TECNOLOGIAS, extrair_dicionario


@pytest.mark.parametrize("grupo", [
    ["JavaScript", "Javascript", "javascript", "JS", "js", "Java Script"],         # B1
    ["TypeScript", "Typescript", "TS", "ts", "type script"],                        # B2
    ["Node.js", "NodeJS", "Node JS", "node.js", "nodejs", "node"],                  # B3
    ["React Native", "ReactNative", "react-native", "REACT   NATIVE"],
    ["PostgreSQL", "Postgres", "postgresql"],
    ["Python", "python 3", "Python3"],
    ["C#", "c#", "C Sharp", "csharp"],
    ["C++", "c++", "cpp", "C plus plus"],
    ["ASP.NET", "asp.net", "ASP.NET Core", "asp net"],
])
def test_variantes_equivalentes(grupo):
    assert len({skills.chave(t) for t in grupo}) == 1
    assert len({skills.canonizar(t) for t in grupo}) == 1


def test_nome_canonico_legivel():
    assert skills.canonizar("javascript") == "JavaScript"
    assert skills.canonizar("  js ") == "JavaScript"
    assert skills.canonizar("NodeJS") == "Node.js"
    assert skills.canonizar("Gestão de   Projetos X") == "Gestão de Projetos X"  # desconhecido: grafia do usuário


# B4 — acentos, caixa e espaços
@pytest.mark.parametrize("a,b", [
    ("Gestão de Projetos", "gestao  de projetos"),
    ("Inteligência Artificial", "INTELIGENCIA ARTIFICIAL"),
    ("  Ciência de Dados ", "ciencia de dados"),
    ("Orientação a Objetos", "orientacao a objetos"),
])
def test_acentos_caixa_espacos(a, b):
    assert skills.mesma_habilidade(a, b)


# B5–B7 — tecnologias distintas não se confundem
@pytest.mark.parametrize("a,b", [
    ("Java", "JavaScript"), ("Java", "JS"),
    ("React", "React Native"),
    ("C", "C++"), ("C", "C#"), ("C++", "C#"),
    ("TypeScript", "JavaScript"),
    ("SQL", "PostgreSQL"), ("SQL", "MySQL"),
    ("HTML", "CSS"),
    (".NET", "ASP.NET"), (".NET", "NET"),
    ("Go", "Golang Developer"),
    ("Angular", "AngularJS Tutorials"),
])
def test_tecnologias_distintas(a, b):
    assert not skills.mesma_habilidade(a, b)


# B8 — nada de equivalência por prefixo/substring/semelhança
@pytest.mark.parametrize("a,b", [
    ("Java", "Java Spring"), ("Pyth", "Python"), ("Reac", "React"), ("Docker", "Docker Compose"),
    ("Node", "Nodemon"), ("py", "Python"), ("Script", "JavaScript"), ("Postgre", "PostgreSQL"),
])
def test_sem_correspondencia_parcial(a, b):
    assert not skills.mesma_habilidade(a, b)


def test_simbolos_significativos_preservados():
    assert skills.chave("C++") == "c++" and skills.chave("C#") == "c#" and skills.chave(".NET") == ".net"
    assert skills.chave("CI/CD") == "ci/cd" and skills.chave("Node.js") == "node.js"
    assert skills.canonizar("c++") == "C++" and skills.canonizar("c#") == "C#" and skills.canonizar(".net") == ".NET"


def test_pontuacao_irrelevante_e_vazio():
    assert skills.mesma_habilidade("Python,", "python")
    assert skills.mesma_habilidade("(Docker)", "docker")
    assert skills.chave("   ") == ""
    assert not skills.mesma_habilidade("", "")


def test_idempotente_e_sem_colisao_entre_canonicos():
    for nome in set(skills._TABELA.values()):
        assert skills.canonizar(nome) == nome, nome
    # nenhum nome canônico diferente pode compartilhar a mesma chave
    vistas = {}
    for nome in set(skills._TABELA.values()):
        vistas.setdefault(skills.chave(nome), set()).add(nome)
    assert [v for v in vistas.values() if len(v) > 1] == []


def test_aspnet_nao_e_fundido_em_dotnet_na_extracao():
    vaga = {"titulo": "Pessoa Desenvolvedora", "descricao": "Requisitos: ASP.NET Core e SQL Server. " * 5}
    ext = extrair_dicionario(vaga)
    assert "ASP.NET" in ext["tecnologias"] and ".NET" not in ext["tecnologias"]
    assert "ASP.NET" in TECNOLOGIAS and ".NET" in TECNOLOGIAS


def test_duplicatas_do_dicionario_viram_um_requisito():
    assert skills.chave("DDD") == skills.chave("Domain-Driven Design")
    assert skills.chave("Kafka") == skills.chave("Apache Kafka")


def test_mesma_logica_para_perfil_e_vagas():
    # o que o dicionário extrai e o que o usuário digita caem na mesma chave
    vaga = {"titulo": "Dev", "descricao": "Requisitos: javascript, node, react native e postgres. " * 4}
    extraidos = {skills.chave(t) for t in extrair_dicionario(vaga)["tecnologias"]}
    digitados = {skills.chave(t) for t in ["JS", "NodeJS", "ReactNative", "Postgres"]}
    assert digitados <= extraidos
