"""Tests du générateur de données fictives.

On vérifie la cohérence des fichiers produits, pas le hasard exact :
les deux profils doivent être exploitables et clairement marqués fictifs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from data.generer_donnees import AVERTISSEMENT_FICTIF, PROFILS, generer_tout
from tools.creances import analyser_creances
from tools.donnees import charger_jeu_dossier
from tools.kpi import analyser_ventes_depenses
from tools.prevision_tresorerie import prevoir_tresorerie
from tools.recommandations import generer_recommandations


@pytest.fixture(scope="module")
def jeux(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    racine = tmp_path_factory.mktemp("donnees")
    generer_tout(racine)
    return {identifiant: racine / identifiant for identifiant in PROFILS}


def test_les_deux_profils_sont_generes(jeux: dict[str, Path]) -> None:
    assert set(jeux) == {"epicerie", "cooperative"}
    for dossier in jeux.values():
        for nom in ("ventes.csv", "depenses.csv", "factures_clients.csv", "parametres.json"):
            assert (dossier / nom).exists()


def test_parametres_marques_fictifs(jeux: dict[str, Path]) -> None:
    for dossier in jeux.values():
        params = json.loads((dossier / "parametres.json").read_text(encoding="utf-8"))
        assert params["fictif"] is True
        assert params["avertissement"] == AVERTISSEMENT_FICTIF
        assert "fictives" in params["avertissement"].lower()
        assert params["devise"] == "MAD"


def test_donnees_exploitables_par_les_outils(jeux: dict[str, Path]) -> None:
    for dossier in jeux.values():
        jeu = charger_jeu_dossier(dossier)
        kpi = analyser_ventes_depenses(jeu)
        creances = analyser_creances(jeu)
        prevision = prevoir_tresorerie(jeu)
        recommandations = generer_recommandations(jeu)

        assert kpi["chiffre_affaires_mad"] > 0
        assert kpi["marge_disponible"] is True
        assert 0 < kpi["taux_marge_pct"] < 60
        assert len(kpi["mensuel"]) >= 8
        assert creances["nombre_factures"] > 0
        assert len(prevision["mois"]) == 3
        assert 3 <= recommandations["nombre_recommandations"] <= 5


def test_scenarios_interessants(jeux: dict[str, Path]) -> None:
    """Les jeux doivent illustrer des situations différentes."""
    epicerie = charger_jeu_dossier(jeux["epicerie"])
    cooperative = charger_jeu_dossier(jeux["cooperative"])

    # L'épicerie a des créances en retard.
    assert analyser_creances(epicerie)["total_en_retard_mad"] > 0

    # La coopérative doit déclencher une alerte de trésorerie négative.
    prevision = prevoir_tresorerie(cooperative)
    assert prevision["alerte_negative"] is True
    assert prevision["premier_mois_negatif"] is not None

    # Et une action prioritaire correspondante.
    actions = generer_recommandations(cooperative)["recommandations"]
    assert actions[0]["id"] == "tresorerie_negative"


def test_couts_complets_pour_la_marge(jeux: dict[str, Path]) -> None:
    for dossier in jeux.values():
        ventes = pd.read_csv(dossier / "ventes.csv")
        assert ventes["cout_unitaire_mad"].notna().all()
        assert (ventes["cout_unitaire_mad"] < ventes["prix_unitaire_mad"]).all()
        assert (ventes["montant_mad"] > 0).all()


def test_factures_coherentes(jeux: dict[str, Path]) -> None:
    for dossier in jeux.values():
        factures = pd.read_csv(dossier / "factures_clients.csv")
        assert factures["facture_id"].is_unique
        assert (factures["montant_paye_mad"] <= factures["montant_mad"]).all()
        assert (pd.to_datetime(factures["date_echeance"]) >= pd.to_datetime(factures["date_emission"])).all()


def test_aucune_date_apres_la_reference(jeux: dict[str, Path]) -> None:
    for dossier in jeux.values():
        params = json.loads((dossier / "parametres.json").read_text(encoding="utf-8"))
        reference = pd.Timestamp(params["date_reference"])
        ventes = pd.read_csv(dossier / "ventes.csv")
        depenses = pd.read_csv(dossier / "depenses.csv")
        assert pd.to_datetime(ventes["date"]).max() <= reference
        assert pd.to_datetime(depenses["date"]).max() <= reference


def test_generation_deterministe(jeux: dict[str, Path], tmp_path: Path) -> None:
    """Deux générations avec la même graine produisent les mêmes fichiers."""
    generer_tout(tmp_path)
    premier = (jeux["epicerie"] / "ventes.csv").read_text(encoding="utf-8")
    second = (tmp_path / "epicerie" / "ventes.csv").read_text(encoding="utf-8")
    assert premier == second
