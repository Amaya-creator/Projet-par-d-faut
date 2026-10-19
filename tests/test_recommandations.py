"""Tests du moteur de recommandations et du formatage."""

from __future__ import annotations

import pandas as pd

from tools.donnees import JeuDonnees, construire_jeu
from tools.formatage import mois_francais, montant_mad, nombre_mad, pourcentage
from tools.recommandations import generer_recommandations

# ---------------------------------------------------------------------------
# Formatage
# ---------------------------------------------------------------------------

def test_nombre_mad_espace_et_virgule() -> None:
    assert nombre_mad(4705.74) == "4\u202f705,74"
    assert nombre_mad(1500) == "1\u202f500,00"


def test_montant_mad_sans_decimales_inutiles() -> None:
    assert montant_mad(1500.0) == "1\u202f500 MAD"
    assert montant_mad(4705.74) == "4\u202f705,74 MAD"
    assert montant_mad(None) == "montant non disponible"


def test_pourcentage_et_mois() -> None:
    assert pourcentage(42.16) == "42,2 %"
    assert pourcentage(None) == "non disponible"
    assert mois_francais(1.5) == "1,5 mois"


# ---------------------------------------------------------------------------
# Recommandations
# ---------------------------------------------------------------------------

def test_entre_trois_et_cinq_recommandations(jeu: JeuDonnees) -> None:
    resultat = generer_recommandations(jeu)
    assert 3 <= resultat["nombre_recommandations"] <= 5
    assert len(resultat["recommandations"]) == resultat["nombre_recommandations"]


def test_chaque_recommandation_cite_un_chiffre(jeu: JeuDonnees) -> None:
    resultat = generer_recommandations(jeu)
    for action in resultat["recommandations"]:
        assert action["titre"]
        assert action["action"]
        assert action["justification"]
        assert action["chiffres"], f"Aucun chiffre pour {action['id']}"
        for chiffre in action["chiffres"]:
            assert chiffre["libelle"] and chiffre["valeur"]


def test_identifiants_uniques(jeu: JeuDonnees) -> None:
    actions = generer_recommandations(jeu)["recommandations"]
    identifiants = [a["id"] for a in actions]
    assert len(identifiants) == len(set(identifiants))


def test_priorites_triees(jeu: JeuDonnees) -> None:
    actions = generer_recommandations(jeu)["recommandations"]
    priorites = [a["priorite"] for a in actions]
    assert priorites == sorted(priorites)


def test_relance_des_creances_presente(jeu: JeuDonnees) -> None:
    actions = {a["id"]: a for a in generer_recommandations(jeu)["recommandations"]}
    assert "relance_creances" in actions
    assert "750" in actions["relance_creances"]["justification"].replace("\u202f", " ")


def test_alerte_tresorerie_en_tete() -> None:
    """Une trésorerie négative doit produire l'action prioritaire n°1."""
    ventes = pd.DataFrame(
        [{"date": f"2026-0{m}-15", "categorie": "Alimentation", "montant_mad": 200.0,
          "cout_mad": 150.0} for m in (1, 2, 3)]
    )
    depenses = pd.DataFrame(
        [{"date": f"2026-0{m}-05", "categorie": "Loyer", "libelle": "Loyer",
          "montant_mad": 2500.0} for m in (1, 2, 3)]
    )
    factures = pd.DataFrame(
        [{"facture_id": "F-1", "client": "Client", "date_emission": "2026-01-05",
          "date_echeance": "2026-02-05", "montant_mad": 400.0, "montant_paye_mad": 0.0}]
    )
    jeu = construire_jeu(
        ventes=ventes,
        depenses=depenses,
        factures=factures,
        entreprise="Trésorerie critique",
        date_reference="2026-03-31",
        solde_tresorerie_mad=500.0,
    )
    resultat = generer_recommandations(jeu)
    assert resultat["recommandations"][0]["id"] == "tresorerie_negative"
    assert resultat["synthese"]["tresorerie_negative_prevue"] is True


def test_sans_donnees_de_marge_action_de_completion() -> None:
    ventes = pd.DataFrame(
        [{"date": "2026-01-10", "categorie": "Alimentation", "montant_mad": 500.0}]
    )
    depenses = pd.DataFrame(
        [{"date": "2026-01-05", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": 100.0}]
    )
    jeu = construire_jeu(
        ventes=ventes,
        depenses=depenses,
        factures=pd.DataFrame(),
        entreprise="Sans coût",
        date_reference="2026-01-31",
        solde_tresorerie_mad=1000.0,
    )
    actions = {a["id"] for a in generer_recommandations(jeu)["recommandations"]}
    assert "completer_couts" in actions


def test_montants_en_mad_dans_les_justifications(jeu: JeuDonnees) -> None:
    for action in generer_recommandations(jeu)["recommandations"]:
        texte = action["justification"]
        assert "MAD" in texte or "%" in texte or "jours" in texte
