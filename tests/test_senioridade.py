"""Etapa 3 — Grupo A: classificação de senioridade (dados SINTÉTICOS de teste)."""
import pytest

from app import senioridade as s


def nivel(titulo, desc=""):
    return s.classificar(titulo, desc)["nivel"]


# A1 — senioridade explícita no título
@pytest.mark.parametrize("titulo,esperado", [
    ("Desenvolvedor React Native Júnior", "junior"), ("Desenvolvedor Backend Pleno", "pleno"), ("Engenheiro de Dados Sênior", "senior"),
])
def test_a1_titulo_explicito(titulo, esperado):
    r = s.classificar(titulo, "")
    assert r["nivel"] == esperado and r["origem"] == "explicita" and r["confianca"] == "alta"
    assert "Título identificado explicitamente" in r["motivo"]


# A2 — variações
@pytest.mark.parametrize("titulo,esperado", [
    ("Dev Junior", "junior"), ("Dev JÚNIOR", "junior"), ("Dev Jr", "junior"), ("Dev Jr.", "junior"), ("Dev (Jr)", "junior"), ("Entry-level Developer", "junior"),
    ("Dev PLENO", "pleno"), ("Dev Pl", "pleno"), ("Dev Pl.", "pleno"), ("Mid-level Developer", "pleno"), ("Mid Level Engineer", "pleno"), ("Middle Developer", "pleno"),
    ("Dev Sênior", "senior"), ("Dev Senior", "senior"), ("Dev Sr", "senior"), ("Dev Sr.", "senior"), ("Senior Software Engineer", "senior"),
])
def test_a2_variacoes(titulo, esperado):
    assert nivel(titulo) == esperado


@pytest.mark.parametrize("titulo", ["Desenvolvedor Oracle PL/SQL", "Dev Java PL SQL", "Analista SRE", "Dev Internal Tools", "Engenheiro de Software", "Associate Developer"])
def test_a2_nao_confunde(titulo):
    assert nivel(titulo) == "nao_classificado"  # PL/SQL não é pleno; SRE não é sênior; "associate" não vale como nível


# A3 — contradições
def test_a3_titulo_com_dois_niveis():
    r = s.classificar("Desenvolvedor Júnior/Pleno", "")
    assert r["nivel"] == "nao_classificado" and r["conflito"] and "conflitantes" in r["motivo"]


def test_a3_titulo_x_frase_da_descricao():
    r = s.classificar("Desenvolvedor Júnior", "Procuramos pessoa para a vaga de nível sênior.")
    assert r["nivel"] == "nao_classificado" and r["conflito"] and "Sênior" in r["motivo"]


@pytest.mark.parametrize("titulo,desc", [("Dev Pleno", "Exigimos 9 anos de experiência."), ("Dev Júnior", "Mínimo de 6 anos de experiência."), ("Dev Sênior", "1 ano de experiência.")])
def test_a3_titulo_x_anos(titulo, desc):
    r = s.classificar(titulo, desc)
    assert r["nivel"] == "nao_classificado" and r["conflito"] and "experiência" in r["motivo"]


def test_a3_descricao_com_dois_niveis():
    r = s.classificar("Desenvolvedor", "Vaga de nível júnior e também vaga de nível pleno.")
    assert r["nivel"] == "nao_classificado" and r["conflito"]


def test_titulo_compativel_com_descricao_e_registrado():
    r = s.classificar("Dev Pleno", "Vaga de nível pleno. 3 anos de experiência.")
    assert r["nivel"] == "pleno" and "compatível" in r["motivo"]


# A4 — não força nível sem evidência
@pytest.mark.parametrize("desc", [
    "", "Trabalhará ao lado de sêniores e fará mentoria de júniores.", "Stack: " + ", ".join(["Python", "Go", "Kafka", "AWS", "Docker", "Kubernetes", "Terraform"]) * 10,
    "Descrição muito longa " * 400, "Conhecimento avançado em Kubernetes e Kafka.",
])
def test_a4_sem_evidencia_nao_classifica(desc):
    r = s.classificar("Desenvolvedor", desc)
    assert r["nivel"] == "nao_classificado" and not r["conflito"] and r["motivo"] == "Informação insuficiente para classificar."


def test_a4_poucas_tecnologias_ou_muitas_nao_decidem():
    assert nivel("Dev", "Python.") == nivel("Dev", "Python, Go, Rust, Java, C++, AWS, GCP, Azure, Kafka, Spark") == "nao_classificado"


def test_inferencia_por_frase_explicita_na_descricao():
    r = s.classificar("Desenvolvedor", "Estamos buscando um desenvolvedor pleno para o time.")
    assert (r["nivel"], r["origem"], r["confianca"]) == ("pleno", "inferida", "media")
    assert s.classificar("Desenvolvedor", "Você vai atuar como engenheiro sênior.")["nivel"] == "senior"


def test_inferencia_por_multiplos_indicios_exige_limiar():
    forte = s.classificar("Desenvolvedor", "5 anos de experiência. Fará mentoria do time, decisões técnicas e arquitetura.")
    assert forte["nivel"] == "senior" and forte["origem"] == "inferida" and "múltiplos indícios" in forte["motivo"]
    fraco = s.classificar("Desenvolvedor", "5 anos de experiência. Fará mentoria do time.")  # só 2 indícios
    assert fraco["nivel"] == "nao_classificado"


def test_mencao_a_outros_niveis_sem_contexto_nao_conta():
    r = s.classificar("Desenvolvedor Júnior", "Você será apoiado por desenvolvedores sêniores e plenos do time.")
    assert r["nivel"] == "junior" and not r["conflito"]


# A5 — fora das categorias principais
@pytest.mark.parametrize("titulo,esperado", [
    ("Estagiário em Desenvolvimento", "estagio"), ("Trainee de Tecnologia", "estagio"), ("Software Engineering Intern", "estagio"),
    ("Especialista em Segurança", "especialista"), ("Arquiteto de Software", "especialista"), ("Staff Engineer", "especialista"),
    ("Tech Lead", "lideranca"), ("Gerente de Engenharia", "lideranca"), ("Coordenador de TI", "lideranca"), ("Líder Técnico", "lideranca"),
    ("Engenheiro Sênior | Tech Lead", "lideranca"), ("Arquiteto de Soluções Sênior", "especialista"),
])
def test_a5_niveis_fora_das_tres_categorias(titulo, esperado):
    r = s.classificar(titulo, "")
    assert r["nivel"] == esperado and r["categoria"] == "outro" and r["nivel"] not in s.PRINCIPAIS


def test_a5_estagio_nao_vira_junior():
    assert nivel("Estágio Júnior") == "nao_classificado"  # dois sinais incompatíveis: não escolhe


# --- anos de experiência (corrige o limite do extrator antigo: em faixas valia o maior número)
@pytest.mark.parametrize("texto,minimo", [
    ("3 a 5 anos de experiência", 3), ("3-5 years of experience", 3), ("Experiência de 4 a 6 anos", 4), ("mínimo de 2 anos de experiência", 2),
    ("5+ anos de experiência", 5), ("at least 7 years of experience", 7), ("Experiência mínima: 3 anos", 3),
    ("empresa com 20 anos de mercado", None), ("sem exigência de experiência", None),
])
def test_anos_minimos(texto, minimo):
    assert s.anos_minimos(texto)["min"] == minimo


def test_anos_com_valores_diferentes_mostra_ambiguidade():
    r = s.anos_minimos("2 anos de experiência com Python e 5 anos de experiência com AWS")
    assert r["min"] == 2 and r["valores"] == [2, 5]


def test_responsabilidades_detectadas_por_texto():
    r = s.responsabilidades("Fará code review, mentoria de colegas, decisões técnicas e trabalhará com stakeholders. Autonomia é valorizada.")
    assert {"revisao_codigo", "mentoria", "decisoes_tecnicas", "negocio", "autonomia"} <= r
    assert "arquitetura" not in r and "lideranca_tecnica" not in r
