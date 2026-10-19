"""Tests de la couche agent : outils, prompt et mode hors ligne.

Aucun appel réseau n'est effectué. L'API Anthropic est remplacée par un faux
client pour vérifier la boucle tool use.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.agent import AgentIndisponible, poser_question, repondre, reponse_hors_ligne
from agent.outils import OUTILS, ContexteOutils, executer_outil, resume_donnees
from agent.prompt import construire_prompt_systeme
from tools.donnees import JeuDonnees


def test_outils_ont_un_schema_valide() -> None:
    noms = {outil["name"] for outil in OUTILS}
    assert noms == {
        "analyser_ventes_depenses",
        "analyser_creances",
        "prevoir_tresorerie",
        "generer_recommandations",
        "resume_donnees",
    }
    for outil in OUTILS:
        assert outil["description"]
        assert outil["input_schema"]["type"] == "object"
        assert isinstance(outil["input_schema"]["properties"], dict)


def test_execution_outil_kpi(jeu: JeuDonnees) -> None:
    contexte = ContexteOutils(jeu=jeu)
    resultat = contexte.executer("analyser_ventes_depenses", {})
    assert resultat["chiffre_affaires_mad"] == 6100.0
    assert contexte.journal[0]["outil"] == "analyser_ventes_depenses"
    assert "CA" in contexte.journal[0]["resultat_resume"]


def test_execution_outil_avec_filtre(jeu: JeuDonnees) -> None:
    contexte = ContexteOutils(jeu=jeu)
    resultat = contexte.executer(
        "analyser_ventes_depenses",
        {"date_debut": "2026-02-01", "date_fin": "2026-02-28"},
    )
    assert resultat["chiffre_affaires_mad"] == 1600.0


def test_execution_outil_inconnu(jeu: JeuDonnees) -> None:
    with pytest.raises(ValueError, match="inconnu"):
        ContexteOutils(jeu=jeu).executer("pirate", {})


def test_erreur_outil_renvoyee_en_json(jeu: JeuDonnees) -> None:
    """Une erreur de calcul doit être renvoyée au LLM, pas levée."""
    jeu.solde_tresorerie_mad = None
    contexte = ContexteOutils(jeu=jeu)
    sortie = executer_outil(contexte, "prevoir_tresorerie", {})
    charge = json.loads(sortie)
    assert "erreur" in charge
    assert "solde de trésorerie" in charge["erreur"]


def test_resume_donnees(jeu: JeuDonnees) -> None:
    resume = resume_donnees(jeu)
    assert resume["nombre_ventes"] == 6
    assert resume["nombre_depenses"] == 7
    assert resume["nombre_factures"] == 4
    assert resume["nombre_lignes_total"] == 17
    assert resume["periode_couverte"]["debut"] == "2026-01-01"
    assert resume["date_reference"] == "2026-03-15"


def test_resume_signale_le_solde_manquant(jeu: JeuDonnees) -> None:
    jeu.solde_tresorerie_mad = None
    resume = resume_donnees(jeu)
    assert any("solde de trésorerie" in a for a in resume["alertes_donnees"])


def test_prompt_contient_les_regles(jeu: JeuDonnees) -> None:
    prompt = construire_prompt_systeme(jeu)
    assert "ne calcules JAMAIS" in prompt
    assert "MAD" in prompt
    assert "Entreprise Test" in prompt
    assert "2026-03-15" in prompt


def test_prompt_signale_les_donnees_fictives(jeu: JeuDonnees) -> None:
    jeu.fictif = True
    assert "fictives" in construire_prompt_systeme(jeu)


def test_mode_hors_ligne_tresorerie(jeu: JeuDonnees) -> None:
    reponse = reponse_hors_ligne(jeu, "pourquoi ma trésorerie baisse ?")
    assert reponse.mode == "hors_ligne"
    assert "trésorerie" in reponse.texte.lower()
    assert any(o["outil"] == "prevoir_tresorerie" for o in reponse.outils_utilises)


def test_mode_hors_ligne_creances(jeu: JeuDonnees) -> None:
    reponse = reponse_hors_ligne(jeu, "quelles factures sont impayées ?")
    assert "facture" in reponse.texte.lower()
    assert any(o["outil"] == "analyser_creances" for o in reponse.outils_utilises)


def test_mode_hors_ligne_actions(jeu: JeuDonnees) -> None:
    reponse = reponse_hors_ligne(jeu, "que faire pour améliorer ?")
    assert any(o["outil"] == "generer_recommandations" for o in reponse.outils_utilises)
    assert "Pourquoi" in reponse.texte


def test_mode_hors_ligne_repli_si_api_indisponible(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reponse = repondre(jeu, "bonjour")
    assert reponse.mode == "hors_ligne"


def test_api_sans_cle_leve_une_erreur_claire(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AgentIndisponible, match="ANTHROPIC_API_KEY"):
        poser_question(jeu, "bonjour")


# ---------------------------------------------------------------------------
# Faux client Anthropic : vérifie la boucle tool use sans réseau
# ---------------------------------------------------------------------------

class FauxClient:
    def __init__(self, reponses: list[Any]) -> None:
        self.reponses = list(reponses)
        self.appels: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.appels.append(kwargs)
        if not self.reponses:
            raise AssertionError("Le faux client n'a plus de réponse à fournir.")
        return self.reponses.pop(0)


def _bloc_texte(texte: str) -> Any:
    return SimpleNamespace(type="text", text=texte)


def _bloc_outil(nom: str, arguments: dict[str, Any], identifiant: str = "tool_1") -> Any:
    return SimpleNamespace(type="tool_use", name=nom, input=arguments, id=identifiant)


def _reponse(contenu: list[Any], stop_reason: str) -> Any:
    return SimpleNamespace(content=contenu, stop_reason=stop_reason)


def test_boucle_appelle_l_outil_puis_repond(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    faux = FauxClient(
        [
            _reponse([_bloc_outil("analyser_ventes_depenses", {})], "tool_use"),
            _reponse([_bloc_texte("Votre chiffre d'affaires est de 6 100 MAD.")], "end_turn"),
        ]
    )
    monkeypatch.setattr("agent.agent._client_anthropic", lambda: faux)

    reponse = poser_question(jeu, "quel est mon chiffre d'affaires ?")

    assert reponse.mode == "api"
    assert "6 100" in reponse.texte
    assert len(faux.appels) == 2
    # Le premier appel contient les outils et le prompt système.
    assert faux.appels[0]["tools"] == OUTILS
    assert "MIZAN AI" in faux.appels[0]["system"]
    # Le second appel contient le résultat de l'outil.
    messages = faux.appels[1]["messages"]
    dernier = messages[-1]
    assert dernier["role"] == "user"
    assert dernier["content"][0]["type"] == "tool_result"
    resultat = json.loads(dernier["content"][0]["content"])
    assert resultat["chiffre_affaires_mad"] == 6100.0
    assert reponse.outils_utilises[0]["outil"] == "analyser_ventes_depenses"


def test_boucle_transmet_l_historique(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    faux = FauxClient([_reponse([_bloc_texte("Bonjour.")], "end_turn")])
    monkeypatch.setattr("agent.agent._client_anthropic", lambda: faux)

    poser_question(
        jeu,
        "et ensuite ?",
        historique=[
            {"role": "user", "content": "bonjour"},
            {"role": "assistant", "content": "Bonjour, comment puis-je aider ?"},
        ],
    )
    messages = faux.appels[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"] == "et ensuite ?"


def test_boucle_erreur_api_bascule_hors_ligne(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")

    class ClientEnPanne:
        def __init__(self) -> None:
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs: Any) -> Any:
            raise RuntimeError("quota dépassé")

    monkeypatch.setattr("agent.agent._client_anthropic", lambda: ClientEnPanne())
    reponse = repondre(jeu, "bonjour")
    assert reponse.mode == "hors_ligne"
    assert reponse.erreur and "quota" in reponse.erreur


def test_question_vide_rejetee(jeu: JeuDonnees, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    with pytest.raises(ValueError, match="vide"):
        poser_question(jeu, "   ")
