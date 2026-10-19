"""Fixtures partagées : petites données maîtrisées, sans aléatoire."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tools.donnees import JeuDonnees, construire_jeu


def ventes_exemple() -> pd.DataFrame:
    """Trois mois de ventes, deux catégories, coûts complets."""
    return pd.DataFrame(
        [
            # Janvier : 1 000 de CA, 600 de coût
            {"date": "2026-01-01", "client": "Clients de passage", "categorie": "Alimentation",
             "quantite": 10, "prix_unitaire_mad": 60.0, "cout_unitaire_mad": 40.0, "montant_mad": 600.0},
            {"date": "2026-01-20", "client": "Café Rif", "categorie": "Boissons",
             "quantite": 10, "prix_unitaire_mad": 40.0, "cout_unitaire_mad": 20.0, "montant_mad": 400.0},
            # Février : 1 200 de CA, 700 de coût
            {"date": "2026-02-01", "client": "Clients de passage", "categorie": "Alimentation",
             "quantite": 12, "prix_unitaire_mad": 75.0, "cout_unitaire_mad": 45.0, "montant_mad": 900.0},
            {"date": "2026-02-18", "client": "Café Rif", "categorie": "Boissons",
             "quantite": 10, "prix_unitaire_mad": 30.0, "cout_unitaire_mad": 25.0, "montant_mad": 300.0},
            # Mars (mois en cours, partiel) : 1 200 de CA, 720 de coût
            {"date": "2026-03-05", "client": "Clients de passage", "categorie": "Alimentation",
             "quantite": 20, "prix_unitaire_mad": 45.0, "cout_unitaire_mad": 27.0, "montant_mad": 900.0},
            {"date": "2026-03-08", "client": "Café Rif", "categorie": "Boissons",
             "quantite": 10, "prix_unitaire_mad": 30.0, "cout_unitaire_mad": 18.0, "montant_mad": 300.0},
        ]
    )


def depenses_exemple() -> pd.DataFrame:
    """Dépenses mensuelles simples, plus un achat de marchandises en février."""
    return pd.DataFrame(
        [
            {"date": "2026-01-03", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": 400.0},
            {"date": "2026-01-15", "categorie": "Électricité", "libelle": "Électricité", "montant_mad": 100.0},
            {"date": "2026-02-03", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": 400.0},
            {"date": "2026-02-15", "categorie": "Électricité", "libelle": "Électricité", "montant_mad": 150.0},
            {"date": "2026-02-20", "categorie": "Achats de marchandises", "libelle": "Réassort",
             "montant_mad": 700.0},
            {"date": "2026-03-03", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": 400.0},
            {"date": "2026-03-15", "categorie": "Électricité", "libelle": "Électricité", "montant_mad": 120.0},
        ]
    )


def factures_exemple() -> pd.DataFrame:
    """Quatre factures : payée, en retard, non échue, partiellement payée."""
    return pd.DataFrame(
        [
            # Payée à l'échéance
            {"facture_id": "F-001", "client": "Café Rif", "categorie": "Boissons",
             "date_emission": "2026-01-10", "date_echeance": "2026-02-10",
             "montant_mad": 1000.0, "montant_paye_mad": 1000.0, "cout_mad": 600.0,
             "date_paiement": "2026-02-10"},
            # En retard de 69 jours au 15 mars, non payée, donc à risque
            {"facture_id": "F-002", "client": "Snack Océan", "categorie": "Alimentation",
             "date_emission": "2026-01-05", "date_echeance": "2026-01-05",
             "montant_mad": 500.0, "montant_paye_mad": 0.0, "cout_mad": 300.0,
             "date_paiement": None},
            # Non échue au 15 mars
            {"facture_id": "F-003", "client": "École Al Fath", "categorie": "Alimentation",
             "date_emission": "2026-03-01", "date_echeance": "2026-04-01",
             "montant_mad": 800.0, "montant_paye_mad": 0.0, "cout_mad": 500.0,
             "date_paiement": None},
            # Partiellement payée, en retard de 28 jours
            {"facture_id": "F-004", "client": "Café Rif", "categorie": "Boissons",
             "date_emission": "2026-02-01", "date_echeance": "2026-02-15",
             "montant_mad": 400.0, "montant_paye_mad": 150.0, "cout_mad": 250.0,
             "date_paiement": None},
        ]
    )


@pytest.fixture
def jeu() -> JeuDonnees:
    return construire_jeu(
        ventes=ventes_exemple(),
        depenses=depenses_exemple(),
        factures=factures_exemple(),
        entreprise="Entreprise Test",
        date_reference=date(2026, 3, 15),
        solde_tresorerie_mad=3000.0,
        source="Fixture de test",
    )
