"""Tests de l'import et de la normalisation des fichiers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.donnees import (
    ErreurDonnees,
    charger_jeu_dossier,
    construire_jeu,
    lire_tableau,
    modeles_import,
    normaliser_depenses,
    normaliser_factures,
    normaliser_ventes,
)


def test_lecture_csv_point_virgule(tmp_path: Path) -> None:
    chemin = tmp_path / "ventes.csv"
    chemin.write_text(
        "date;categorie;montant_mad\n01/02/2026;Alimentation;125,50\n", encoding="utf-8"
    )
    df = lire_tableau(chemin)
    assert list(df.columns) == ["date", "categorie", "montant_mad"]


def test_normalisation_ventes_aliases() -> None:
    df = pd.DataFrame(
        [
            {"Date de vente": "2026-02-01", "Catégorie": "Alimentation",
             "Montant (MAD)": "1 234,50", "Coût": "900"},
        ]
    )
    ventes = normaliser_ventes(df)
    assert ventes.loc[0, "montant_mad"] == 1234.50
    assert ventes.loc[0, "cout_mad"] == 900.0
    assert ventes.loc[0, "client"] == "Clients de passage"
    assert ventes.loc[0, "quantite"] == 1.0


def test_montants_avec_devise_et_espaces() -> None:
    df = pd.DataFrame(
        [
            {"date": "2026-02-01", "categorie": "A", "montant_mad": "2 500,75 MAD"},
            {"date": "2026-02-02", "categorie": "A", "montant_mad": "3.200,00 DHS"},
        ]
    )
    ventes = normaliser_ventes(df)
    assert ventes["montant_mad"].tolist() == [2500.75, 3200.0]


def test_date_illisible_signalee() -> None:
    df = pd.DataFrame(
        [{"date": "pas une date", "categorie": "A", "montant_mad": 100.0}]
    )
    with pytest.raises(ErreurDonnees, match="date"):
        normaliser_ventes(df)


def test_montant_manquant_signale() -> None:
    df = pd.DataFrame(
        [{"date": "2026-02-01", "categorie": "A", "montant_mad": ""}]
    )
    with pytest.raises(ErreurDonnees, match="montant_mad"):
        normaliser_ventes(df)


def test_colonne_obligatoire_manquante() -> None:
    df = pd.DataFrame([{"date": "2026-02-01", "categorie": "A"}])
    with pytest.raises(ErreurDonnees, match="montant_mad"):
        normaliser_ventes(df)


def test_depense_negative_rejetee() -> None:
    df = pd.DataFrame(
        [{"date": "2026-02-01", "categorie": "Loyer", "libelle": "Loyer", "montant_mad": -10.0}]
    )
    with pytest.raises(ErreurDonnees, match="négatifs"):
        normaliser_depenses(df)


def test_factures_sans_montant_paye_sont_impayees() -> None:
    alertes: list[str] = []
    df = pd.DataFrame(
        [
            {"facture_id": "F-1", "client": "Client", "date_emission": "2026-02-01",
             "date_echeance": "2026-03-01", "montant_mad": 1000.0},
        ]
    )
    factures = normaliser_factures(df, alertes)
    assert factures.loc[0, "montant_paye_mad"] == 0.0
    assert any("considérées comme impayées" in a for a in alertes)


def test_facture_id_duplique_rejete() -> None:
    df = pd.DataFrame(
        [
            {"facture_id": "F-1", "client": "A", "date_emission": "2026-02-01",
             "date_echeance": "2026-03-01", "montant_mad": 100.0, "montant_paye_mad": 0.0},
            {"facture_id": "F-1", "client": "B", "date_emission": "2026-02-02",
             "date_echeance": "2026-03-02", "montant_mad": 200.0, "montant_paye_mad": 0.0},
        ]
    )
    with pytest.raises(ErreurDonnees, match="identifiant unique"):
        normaliser_factures(df)


def test_paiement_superieur_au_montant_rejete() -> None:
    df = pd.DataFrame(
        [
            {"facture_id": "F-1", "client": "A", "date_emission": "2026-02-01",
             "date_echeance": "2026-03-01", "montant_mad": 100.0, "montant_paye_mad": 150.0},
        ]
    )
    with pytest.raises(ErreurDonnees, match="dépasse"):
        normaliser_factures(df)


def test_chargement_dossier_complet(tmp_path: Path) -> None:
    (tmp_path / "ventes.csv").write_text(
        "date,categorie,montant_mad\n2026-01-01,Alimentation,100\n", encoding="utf-8"
    )
    (tmp_path / "depenses.csv").write_text(
        "date,categorie,libelle,montant_mad\n2026-01-02,Loyer,Loyer,50\n", encoding="utf-8"
    )
    (tmp_path / "factures_clients.csv").write_text(
        "facture_id,client,date_emission,date_echeance,montant_mad\n"
        "F-1,Client,2026-01-01,2026-02-01,300\n",
        encoding="utf-8",
    )
    (tmp_path / "parametres.json").write_text(
        json.dumps(
            {
                "entreprise": "Test",
                "date_reference": "2026-02-15",
                "solde_tresorerie_initial_mad": 1000,
                "fictif": True,
            }
        ),
        encoding="utf-8",
    )
    jeu = charger_jeu_dossier(tmp_path)
    assert jeu.entreprise == "Test"
    assert jeu.solde_tresorerie_mad == 1000.0
    assert jeu.fictif is True
    assert len(jeu.ventes) == 1
    assert len(jeu.factures) == 1


def test_dossier_incomplet(tmp_path: Path) -> None:
    with pytest.raises(ErreurDonnees, match="parametres.json"):
        charger_jeu_dossier(tmp_path)


def test_fichier_introuvable() -> None:
    with pytest.raises(ErreurDonnees, match="introuvable"):
        lire_tableau("chemin/inexistant.csv")


def test_format_non_supporte() -> None:
    with pytest.raises(ErreurDonnees, match="Format"):
        lire_tableau("fichier.pdf")


def test_import_vide_rejete() -> None:
    with pytest.raises(ErreurDonnees, match="aucune ligne"):
        construire_jeu(
            ventes=pd.DataFrame(),
            depenses=pd.DataFrame(),
            factures=pd.DataFrame(),
            entreprise="Vide",
            date_reference="2026-01-31",
            solde_tresorerie_mad=0.0,
        )


def test_modeles_import_telechargeables() -> None:
    modeles = modeles_import()
    assert set(modeles) == {"ventes.csv", "depenses.csv", "factures_clients.csv"}
    assert all(contenu.startswith(b"\xef\xbb\xbf") for contenu in modeles.values())
