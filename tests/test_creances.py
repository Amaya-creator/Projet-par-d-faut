"""Tests du suivi des créances clients."""

from __future__ import annotations

import pandas as pd
import pytest

from tools.creances import analyser_creances
from tools.donnees import JeuDonnees, construire_jeu


def test_totaux_creances(jeu: JeuDonnees) -> None:
    """Au 15 mars : 3 factures non soldées sur 4, dont 2 en retard."""
    creances = analyser_creances(jeu)
    assert creances["nombre_factures"] == 4
    assert creances["nombre_factures_impayees"] == 3
    assert creances["nombre_factures_en_retard"] == 2
    assert creances["total_facture_mad"] == 2700.0
    assert creances["total_encaisse_mad"] == 1150.0
    assert creances["total_creances_mad"] == 1550.0
    assert creances["total_en_retard_mad"] == 750.0
    assert creances["total_non_echu_mad"] == 800.0


def test_tranches_de_retard(jeu: JeuDonnees) -> None:
    tranches = {t["tranche"]: t for t in analyser_creances(jeu)["par_tranche"]}
    assert tranches["Non échue"]["montant_mad"] == 800.0
    assert tranches["1-30 jours"]["montant_mad"] == 250.0
    assert tranches["61-90 jours"]["montant_mad"] == 500.0
    assert tranches["Plus de 90 jours"]["montant_mad"] == 0.0


def test_retard_maximum(jeu: JeuDonnees) -> None:
    creances = analyser_creances(jeu)
    assert creances["retard_max_jours"] == 69
    assert creances["delai_moyen_retard_jours"] == pytest.approx(48.5, abs=0.1)


def test_creance_a_risque_au_dela_de_60_jours(jeu: JeuDonnees) -> None:
    creances = analyser_creances(jeu)
    assert creances["nombre_factures_a_risque"] == 1
    assert creances["total_a_risque_mad"] == 500.0
    facture = next(f for f in creances["factures"] if f["facture_id"] == "F-002")
    assert facture["a_risque"] is True
    assert "69 jours" in facture["motif_risque"]


def test_client_habituellement_en_retard_est_a_risque() -> None:
    """Un client dont la moyenne de retard dépasse 30 jours est signalé."""
    factures = pd.DataFrame(
        [
            # Facture réglée avec 40 jours de retard : établit l'habitude
            {"facture_id": "A-1", "client": "Client Lent", "date_emission": "2026-01-01",
             "date_echeance": "2026-02-01", "montant_mad": 1000.0, "montant_paye_mad": 1000.0,
             "date_paiement": "2026-03-13"},
            # Facture récente, à peine en retard, mais client identifié comme lent
            {"facture_id": "A-2", "client": "Client Lent", "date_emission": "2026-03-01",
             "date_echeance": "2026-03-10", "montant_mad": 600.0, "montant_paye_mad": 0.0,
             "date_paiement": None},
        ]
    )
    jeu = construire_jeu(
        ventes=pd.DataFrame(),
        depenses=pd.DataFrame(),
        factures=factures,
        entreprise="Test retards",
        date_reference="2026-03-15",
        solde_tresorerie_mad=0.0,
    )
    creances = analyser_creances(jeu)
    facture = next(f for f in creances["factures"] if f["facture_id"] == "A-2")
    assert facture["a_risque"] is True
    assert "client habitué aux retards" in facture["motif_risque"]


def test_facture_partiellement_payee(jeu: JeuDonnees) -> None:
    creances = analyser_creances(jeu)
    facture = next(f for f in creances["factures"] if f["facture_id"] == "F-004")
    assert facture["solde_mad"] == 250.0
    assert facture["montant_paye_mad"] == 150.0
    assert facture["statut"] == "Partiellement payée — en retard"


def test_sans_facture() -> None:
    jeu = construire_jeu(
        ventes=pd.DataFrame(
            [{"date": "2026-03-01", "categorie": "Alimentation", "montant_mad": 100.0,
              "cout_mad": 70.0}]
        ),
        depenses=pd.DataFrame(),
        factures=pd.DataFrame(),
        entreprise="Sans facture",
        date_reference="2026-03-15",
        solde_tresorerie_mad=0.0,
    )
    creances = analyser_creances(jeu)
    assert creances["total_creances_mad"] == 0.0
    assert creances["nombre_factures"] == 0
    assert any("Aucune facture" in a for a in creances["alertes_donnees"])


def test_facture_soldee_absente_des_impayes(jeu: JeuDonnees) -> None:
    creances = analyser_creances(jeu)
    identifiants = {f["facture_id"] for f in creances["factures"]}
    assert "F-001" not in identifiants


def test_pourcentage_creances_en_retard(jeu: JeuDonnees) -> None:
    creances = analyser_creances(jeu)
    assert creances["part_creances_retard_pct"] == pytest.approx(48.4, abs=0.1)
