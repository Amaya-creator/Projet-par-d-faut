"""Tests des indicateurs de ventes, dépenses et marge."""

from __future__ import annotations

import pandas as pd
import pytest

from tools.donnees import JeuDonnees, construire_jeu
from tools.kpi import analyser_ventes_depenses


def test_totaux_globaux(jeu: JeuDonnees) -> None:
    """CA = ventes comptant + factures ; marge = CA − coût des marchandises."""
    kpi = analyser_ventes_depenses(jeu)
    assert kpi["ventes_comptant_mad"] == 3400.0
    assert kpi["factures_emises_mad"] == 2700.0
    assert kpi["chiffre_affaires_mad"] == 6100.0
    assert kpi["cout_achats_mad"] == 3760.0
    assert kpi["marge_brute_mad"] == 2340.0
    assert kpi["taux_marge_pct"] == pytest.approx(38.4, abs=0.05)
    assert kpi["depenses_mad"] == 2270.0
    assert kpi["achats_marchandises_mad"] == 700.0
    assert kpi["depenses_exploitation_mad"] == 1570.0
    # Résultat = marge − dépenses d'exploitation (les achats sont déjà dans le coût)
    assert kpi["resultat_estime_mad"] == 770.0


def test_agregation_mensuelle(jeu: JeuDonnees) -> None:
    kpi = analyser_ventes_depenses(jeu)
    assert [m["mois"] for m in kpi["mensuel"]] == ["2026-01", "2026-02", "2026-03"]
    janvier = kpi["mensuel"][0]
    assert janvier["ca_mad"] == 2500.0
    assert janvier["ventes_comptant_mad"] == 1000.0
    assert janvier["factures_emises_mad"] == 1500.0
    assert janvier["marge_brute_mad"] == 1000.0
    assert janvier["depenses_mad"] == 500.0
    assert janvier["resultat_estime_mad"] == 500.0
    assert janvier["partiel"] is False


def test_mois_en_cours_marque_partiel(jeu: JeuDonnees) -> None:
    kpi = analyser_ventes_depenses(jeu)
    mars = kpi["mensuel"][-1]
    assert mars["mois"] == "2026-03"
    assert mars["partiel"] is True
    assert any("incomplet" in alerte for alerte in kpi["alertes_donnees"])


def test_evolution_compare_les_deux_derniers_mois_complets(jeu: JeuDonnees) -> None:
    evolution = analyser_ventes_depenses(jeu)["evolution"]
    assert evolution["mois_recent"] == "2026-02"
    assert evolution["mois_precedent"] == "2026-01"
    # CA : 1 600 en février contre 2 500 en janvier → −36 %
    assert evolution["variation_ca_pct"] == pytest.approx(-36.0, abs=0.05)
    # Dépenses : 1 250 en février contre 500 en janvier → +150 %
    assert evolution["variation_depenses_pct"] == pytest.approx(150.0, abs=0.05)


def test_categories_triees_par_ca(jeu: JeuDonnees) -> None:
    categories = analyser_ventes_depenses(jeu)["ventes_par_categorie"]
    assert categories[0]["categorie"] == "Alimentation"
    assert categories[0]["ca_mad"] == 3700.0
    assert categories[0]["marge_brute_mad"] == 1420.0
    assert categories[0]["taux_marge_pct"] == pytest.approx(38.4, abs=0.05)
    total_parts = sum(c["part_ca_pct"] for c in categories)
    assert total_parts == pytest.approx(100.0, abs=0.2)


def test_marge_non_calculee_si_cout_manquant() -> None:
    ventes = pd.DataFrame(
        [
            {"date": "2026-01-10", "categorie": "Alimentation", "montant_mad": 500.0},
        ]
    )
    jeu = construire_jeu(
        ventes=ventes,
        depenses=pd.DataFrame(
            [{"date": "2026-01-05", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": 100.0}]
        ),
        factures=pd.DataFrame(),
        entreprise="Sans coût",
        date_reference="2026-01-31",
        solde_tresorerie_mad=1000.0,
    )
    kpi = analyser_ventes_depenses(jeu)
    assert kpi["marge_disponible"] is False
    assert kpi["marge_brute_mad"] is None
    assert kpi["resultat_estime_mad"] is None
    assert any("Coût d'achat manquant" in a for a in kpi["alertes_donnees"])


def test_filtre_de_periode(jeu: JeuDonnees) -> None:
    kpi = analyser_ventes_depenses(jeu, date_debut="2026-02-01", date_fin="2026-02-28")
    assert kpi["chiffre_affaires_mad"] == 1600.0
    assert kpi["depenses_mad"] == 1250.0
    assert len(kpi["mensuel"]) == 1


def test_periode_inversee_rejetee(jeu: JeuDonnees) -> None:
    with pytest.raises(ValueError, match="antérieure"):
        analyser_ventes_depenses(jeu, date_debut="2026-03-01", date_fin="2026-02-01")


def test_top_clients(jeu: JeuDonnees) -> None:
    clients = analyser_ventes_depenses(jeu)["top_clients"]
    noms = [c["client"] for c in clients]
    assert "Clients de passage" in noms
    assert clients[0]["ca_mad"] >= clients[-1]["ca_mad"]
