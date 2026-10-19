"""Tests de la prévision de trésorerie."""

from __future__ import annotations

import pandas as pd
import pytest

from tools.donnees import JeuDonnees, construire_jeu
from tools.prevision_tresorerie import prevoir_tresorerie


def test_structure_et_horizon(jeu: JeuDonnees) -> None:
    prevision = prevoir_tresorerie(jeu)
    assert prevision["horizon_mois"] == 3
    assert len(prevision["mois"]) == 3
    assert prevision["solde_initial_mad"] == 3000.0
    assert prevision["mois"][0]["debut"] == "2026-03-16"
    assert prevision["mois"][0]["fin"] == "2026-04-14"


def test_moyennes_journalieres(jeu: JeuDonnees) -> None:
    prevision = prevoir_tresorerie(jeu)
    # 90 jours de fenêtre, historique démarrant le 1er janvier : 74 jours
    assert prevision["jours_historique_ventes"] == 74
    # Ventes au comptant : 3 400 sur 74 jours
    assert prevision["ventes_comptant_moyenne_journaliere_mad"] == pytest.approx(45.95, abs=0.01)
    # Dépenses : 2 270 sur 72 jours (première dépense le 3 janvier)
    assert prevision["jours_historique_depenses"] == 72
    assert prevision["depenses_moyenne_journaliere_mad"] == pytest.approx(31.53, abs=0.01)


def test_recouvrement_factures(jeu: JeuDonnees) -> None:
    """F-003 échoit le 1er avril (mois 1) ; les retards sont étalés."""
    prevision = prevoir_tresorerie(jeu)
    recouvrements = [m["recouvrement_factures_mad"] for m in prevision["mois"]]
    # Mois 1 : 800 (F-003 à échéance) + 70 % de 750 (retards étalés à 50 %) = 800 + 262,50
    assert recouvrements[0] == pytest.approx(1062.50, abs=0.01)
    # Mois 2 : 30 % de 525 = 157,50
    assert recouvrements[1] == pytest.approx(157.50, abs=0.01)
    # Mois 3 : 20 % de 525 = 105
    assert recouvrements[2] == pytest.approx(105.00, abs=0.01)


def test_solde_projete(jeu: JeuDonnees) -> None:
    prevision = prevoir_tresorerie(jeu)
    mois1 = prevision["mois"][0]
    attendu = (
        3000.0
        + mois1["ventes_comptant_prevues_mad"]
        + mois1["recouvrement_factures_mad"]
        - mois1["depenses_prevues_mad"]
    )
    assert mois1["solde_fin_mad"] == pytest.approx(attendu, abs=0.02)
    # Enchaînement : le solde de début du mois 2 est le solde de fin du mois 1
    assert prevision["mois"][1]["solde_debut_mad"] == mois1["solde_fin_mad"]


def test_alerte_tresorerie_negative() -> None:
    ventes = pd.DataFrame(
        [{"date": f"2026-0{m}-15", "categorie": "Alimentation", "montant_mad": 100.0,
          "cout_mad": 80.0} for m in (1, 2, 3)]
    )
    depenses = pd.DataFrame(
        [{"date": f"2026-0{m}-05", "categorie": "Loyer", "libelle": "Loyer",
          "montant_mad": 3000.0} for m in (1, 2, 3)]
    )
    jeu = construire_jeu(
        ventes=ventes,
        depenses=depenses,
        factures=pd.DataFrame(),
        entreprise="Trésorerie tendue",
        date_reference="2026-03-31",
        solde_tresorerie_mad=1000.0,
    )
    prevision = prevoir_tresorerie(jeu)
    assert prevision["alerte_negative"] is True
    assert prevision["premier_mois_negatif"] is not None
    assert prevision["deficit_max_mad"] > 0
    assert any("négative" in a for a in prevision["alertes_donnees"])


def test_solde_manquant_rejete(jeu: JeuDonnees) -> None:
    jeu.solde_tresorerie_mad = None
    with pytest.raises(ValueError, match="solde de trésorerie"):
        prevoir_tresorerie(jeu)


def test_historique_insuffisant() -> None:
    jeu = construire_jeu(
        ventes=pd.DataFrame(
            [{"date": "2026-03-01", "categorie": "Alimentation", "montant_mad": 100.0, "cout_mad": 70.0}]
        ),
        depenses=pd.DataFrame(),
        factures=pd.DataFrame(),
        entreprise="Jeune entreprise",
        date_reference="2026-03-15",
        solde_tresorerie_mad=5000.0,
    )
    with pytest.raises(ValueError, match="Historique insuffisant"):
        prevoir_tresorerie(jeu)


def test_horizon_invalide(jeu: JeuDonnees) -> None:
    with pytest.raises(ValueError, match="horizon"):
        prevoir_tresorerie(jeu, horizon_mois=0)


def test_hypotheses_exposees(jeu: JeuDonnees) -> None:
    hypotheses = prevoir_tresorerie(jeu)["hypotheses"]
    assert hypotheses["taux_recouvrement_retard"] == 0.70
    assert hypotheses["taux_recouvrement_contentieux"] == 0.30
    assert hypotheses["jours_par_mois"] == 30
    assert sum(hypotheses["repartition_recouvrement_retard"]) == pytest.approx(1.0)


def test_facture_hors_horizon_ignoree() -> None:
    factures = pd.DataFrame(
        [{"facture_id": "F-1", "client": "Client", "date_emission": "2026-03-01",
          "date_echeance": "2027-06-01", "montant_mad": 9000.0, "montant_paye_mad": 0.0}]
    )
    jeu = construire_jeu(
        ventes=pd.DataFrame(
            [{"date": f"2026-0{m}-15", "categorie": "Alimentation", "montant_mad": 100.0,
              "cout_mad": 80.0} for m in (1, 2, 3)]
        ),
        depenses=pd.DataFrame(),
        factures=factures,
        entreprise="Échéance lointaine",
        date_reference="2026-03-31",
        solde_tresorerie_mad=1000.0,
    )
    prevision = prevoir_tresorerie(jeu)
    assert all(m["recouvrement_factures_mad"] == 0 for m in prevision["mois"])
