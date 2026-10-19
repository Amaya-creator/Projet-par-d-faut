"""
Indicateurs de ventes, de dépenses et de marge.

Tous les montants sont en MAD et proviennent uniquement des tableaux fournis.
Aucune valeur n'est extrapolée dans ce module.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from tools.donnees import JeuDonnees

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _arrondi(valeur: Any, decimales: int = 2) -> float | None:
    if valeur is None or pd.isna(valeur):
        return None
    return round(float(valeur), decimales)


def _pourcentage(numerateur: float, denominateur: float, decimales: int = 1) -> float | None:
    if not denominateur:
        return None
    return round(100.0 * numerateur / denominateur, decimales)


def _libelle_mois(periode: pd.Period) -> str:
    return f"{MOIS_FR[periode.month - 1]} {periode.year}"


def _fin_de_mois(jour: date) -> date:
    return (pd.Timestamp(jour) + pd.offsets.MonthEnd(0)).date()


def _ventes_combinees(jeu: JeuDonnees) -> pd.DataFrame:
    """Réunit ventes au comptant et factures émises (CA, coût, catégorie, client)."""
    morceaux: list[pd.DataFrame] = []
    if not jeu.ventes.empty:
        comptant = jeu.ventes[["date", "client", "categorie", "montant_mad", "cout_mad"]].copy()
        comptant["type_vente"] = "Comptant"
        morceaux.append(comptant)
    if not jeu.factures.empty:
        credit = jeu.factures[
            ["date_emission", "client", "categorie", "montant_mad", "cout_mad"]
        ].rename(columns={"date_emission": "date"})
        credit["type_vente"] = "Facture"
        morceaux.append(credit)
    if not morceaux:
        return pd.DataFrame(
            columns=["date", "client", "categorie", "montant_mad", "cout_mad", "type_vente"]
        )
    return pd.concat(morceaux, ignore_index=True)


def analyser_ventes_depenses(
    jeu: JeuDonnees,
    date_debut: date | str | None = None,
    date_fin: date | str | None = None,
) -> dict[str, Any]:
    """Calcule le CA, les dépenses, la marge et les évolutions.

    La marge n'est calculée que si le coût d'achat est présent sur *toutes* les
    lignes de vente de la période. Sinon elle vaut None et une alerte l'explique.
    """
    ventes = _ventes_combinees(jeu)
    depenses = jeu.depenses.copy()

    filtre_ventes = pd.Series(True, index=ventes.index)
    filtre_depenses = pd.Series(True, index=depenses.index)
    debut = pd.Timestamp(date_debut) if date_debut is not None else None
    fin = pd.Timestamp(date_fin) if date_fin is not None else None
    if debut is not None and fin is not None and debut > fin:
        raise ValueError("La date de début doit être antérieure à la date de fin.")
    if debut is not None:
        filtre_ventes &= ventes["date"] >= debut
        filtre_depenses &= depenses["date"] >= debut
    if fin is not None:
        filtre_ventes &= ventes["date"] <= fin
        filtre_depenses &= depenses["date"] <= fin
    ventes = ventes.loc[filtre_ventes].copy()
    depenses = depenses.loc[filtre_depenses].copy()

    alertes: list[str] = list(jeu.alertes_import)
    if ventes.empty and depenses.empty:
        alertes.append("Aucune vente ni dépense sur la période demandée.")
    if ventes.empty:
        alertes.append("Aucune vente enregistrée sur la période demandée.")
    if depenses.empty:
        alertes.append("Aucune dépense enregistrée sur la période demandée.")

    ca = float(ventes["montant_mad"].sum()) if not ventes.empty else 0.0
    ca_comptant = float(ventes.loc[ventes["type_vente"] == "Comptant", "montant_mad"].sum())
    ca_factures = float(ventes.loc[ventes["type_vente"] == "Facture", "montant_mad"].sum())
    depenses_total = float(depenses["montant_mad"].sum()) if not depenses.empty else 0.0

    # Les achats de marchandises figurent dans les dépenses (sortie de
    # trésorerie réelle) mais leur coût est déjà retiré dans la marge.
    # On les exclut donc du résultat pour ne pas les compter deux fois.
    masque_achats = depenses["categorie"].str.lower().isin(
        ["achats de marchandises", "achats", "achat de marchandises"]
    )
    depenses_achats = float(depenses.loc[masque_achats, "montant_mad"].sum())
    depenses_exploitation = depenses_total - depenses_achats

    couts_manquants = int(ventes["cout_mad"].isna().sum()) if not ventes.empty else 0
    marge_disponible = bool(not ventes.empty and couts_manquants == 0)
    if couts_manquants:
        alertes.append(
            f"Coût d'achat manquant sur {couts_manquants} ligne(s) de vente : "
            "la marge brute n'est pas calculée."
        )
    cout_total = float(ventes["cout_mad"].sum()) if marge_disponible else None
    marge = round(ca - cout_total, 2) if marge_disponible else None
    taux_marge = _pourcentage(marge, ca) if marge is not None else None
    resultat = round(marge - depenses_exploitation, 2) if marge is not None else None

    # --- Agrégation mensuelle ------------------------------------------------
    dates = []
    if not ventes.empty:
        dates.append(ventes["date"].min())
        dates.append(ventes["date"].max())
    if not depenses.empty:
        dates.append(depenses["date"].min())
        dates.append(depenses["date"].max())

    mensuel: list[dict[str, Any]] = []
    if dates:
        debut_mois = min(dates).to_period("M")
        fin_mois = max(dates).to_period("M")
        for periode in pd.period_range(debut_mois, fin_mois, freq="M"):
            ventes_mois = ventes[ventes["date"].dt.to_period("M") == periode]
            depenses_mois = depenses[depenses["date"].dt.to_period("M") == periode]
            ca_mois = float(ventes_mois["montant_mad"].sum())
            dep_mois = float(depenses_mois["montant_mad"].sum())
            achats_mois = float(
                depenses_mois.loc[
                    depenses_mois["categorie"].str.lower().isin(
                        ["achats de marchandises", "achats", "achat de marchandises"]
                    ),
                    "montant_mad",
                ].sum()
            )
            couts_mois_manquants = int(ventes_mois["cout_mad"].isna().sum())
            marge_mois = (
                round(ca_mois - float(ventes_mois["cout_mad"].sum()), 2)
                if not ventes_mois.empty and couts_mois_manquants == 0
                else None
            )
            mensuel.append(
                {
                    "mois": str(periode),
                    "libelle": _libelle_mois(periode),
                    "ca_mad": round(ca_mois, 2),
                    "ventes_comptant_mad": round(
                        float(ventes_mois.loc[ventes_mois["type_vente"] == "Comptant", "montant_mad"].sum()), 2
                    ),
                    "factures_emises_mad": round(
                        float(ventes_mois.loc[ventes_mois["type_vente"] == "Facture", "montant_mad"].sum()), 2
                    ),
                    "marge_brute_mad": marge_mois,
                    "depenses_mad": round(dep_mois, 2),
                    "achats_marchandises_mad": round(achats_mois, 2),
                    "depenses_exploitation_mad": round(dep_mois - achats_mois, 2),
                    "resultat_estime_mad": (
                        round(marge_mois - (dep_mois - achats_mois), 2)
                        if marge_mois is not None
                        else None
                    ),
                    "partiel": bool(
                        periode == pd.Period(jeu.date_reference, freq="M")
                        and jeu.date_reference < _fin_de_mois(jeu.date_reference)
                    ),
                }
            )

    # --- Évolution sur les mois complets -------------------------------------
    complets = [m for m in mensuel if not m["partiel"]]
    evolution: dict[str, Any] = {
        "base": "Comparaison des deux derniers mois complets.",
        "mois_recent": complets[-1]["mois"] if len(complets) >= 2 else None,
        "mois_precedent": complets[-2]["mois"] if len(complets) >= 2 else None,
        "variation_ca_pct": None,
        "variation_depenses_pct": None,
        "variation_marge_points": None,
        "message": "Pas assez de mois complets pour calculer une évolution.",
    }
    if len(complets) >= 2:
        recent, precedent = complets[-1], complets[-2]
        evolution["variation_ca_pct"] = (
            _pourcentage(recent["ca_mad"] - precedent["ca_mad"], precedent["ca_mad"])
            if precedent["ca_mad"]
            else None
        )
        evolution["variation_depenses_pct"] = (
            _pourcentage(recent["depenses_mad"] - precedent["depenses_mad"], precedent["depenses_mad"])
            if precedent["depenses_mad"]
            else None
        )
        if recent["marge_brute_mad"] is not None and precedent["marge_brute_mad"] is not None:
            taux_recent = _pourcentage(recent["marge_brute_mad"], recent["ca_mad"])
            taux_precedent = _pourcentage(precedent["marge_brute_mad"], precedent["ca_mad"])
            if taux_recent is not None and taux_precedent is not None:
                evolution["variation_marge_points"] = round(taux_recent - taux_precedent, 1)
        evolution["message"] = (
            f"Le chiffre d'affaires de {recent['libelle']} est comparé à celui du mois "
            f"précédent ({precedent['libelle']})."
        )

    if any(m["partiel"] for m in mensuel):
        alertes.append(
            "Le mois en cours est incomplet : il est affiché mais exclu des comparaisons d'évolution."
        )
    if len(complets) < 2:
        alertes.append("Il faut au moins deux mois complets pour calculer une évolution fiable.")
    if resultat is not None and resultat < 0:
        alertes.append("Le résultat estimé de la période est négatif.")

    # --- Catégories de ventes -----------------------------------------------
    categories: list[dict[str, Any]] = []
    if not ventes.empty:
        for categorie, groupe in ventes.groupby("categorie", dropna=False):
            ca_cat = float(groupe["montant_mad"].sum())
            manquants = int(groupe["cout_mad"].isna().sum())
            marge_cat = (
                round(ca_cat - float(groupe["cout_mad"].sum()), 2) if manquants == 0 else None
            )
            categories.append(
                {
                    "categorie": str(categorie),
                    "ca_mad": round(ca_cat, 2),
                    "part_ca_pct": _pourcentage(ca_cat, ca),
                    "marge_brute_mad": marge_cat,
                    "taux_marge_pct": _pourcentage(marge_cat, ca_cat) if marge_cat is not None else None,
                    "marge_disponible": manquants == 0,
                }
            )
        categories.sort(key=lambda item: item["ca_mad"], reverse=True)

    depenses_categories: list[dict[str, Any]] = []
    if not depenses.empty:
        for categorie, groupe in depenses.groupby("categorie", dropna=False):
            montant = float(groupe["montant_mad"].sum())
            depenses_categories.append(
                {
                    "categorie": str(categorie),
                    "montant_mad": round(montant, 2),
                    "part_pct": _pourcentage(montant, depenses_total),
                    "nombre_lignes": len(groupe),
                }
            )
        depenses_categories.sort(key=lambda item: item["montant_mad"], reverse=True)

    top_clients: list[dict[str, Any]] = []
    if not ventes.empty:
        for client, groupe in ventes.groupby("client", dropna=False):
            ca_client = float(groupe["montant_mad"].sum())
            top_clients.append(
                {
                    "client": str(client),
                    "ca_mad": round(ca_client, 2),
                    "part_ca_pct": _pourcentage(ca_client, ca),
                }
            )
        top_clients.sort(key=lambda item: item["ca_mad"], reverse=True)
        top_clients = top_clients[:5]

    return {
        "entreprise": jeu.entreprise,
        "devise": jeu.devise,
        "date_reference": jeu.date_reference.isoformat(),
        "periode": {
            "debut": (
                min(ventes["date"].min(), depenses["date"].min()).date().isoformat()
                if not ventes.empty and not depenses.empty
                else (
                    ventes["date"].min().date().isoformat()
                    if not ventes.empty
                    else depenses["date"].min().date().isoformat()
                    if not depenses.empty
                    else None
                )
            ),
            "fin": (
                max(ventes["date"].max(), depenses["date"].max()).date().isoformat()
                if not ventes.empty and not depenses.empty
                else (
                    ventes["date"].max().date().isoformat()
                    if not ventes.empty
                    else depenses["date"].max().date().isoformat()
                    if not depenses.empty
                    else None
                )
            ),
        },
        "chiffre_affaires_mad": round(ca, 2),
        "ventes_comptant_mad": round(ca_comptant, 2),
        "factures_emises_mad": round(ca_factures, 2),
        "cout_achats_mad": _arrondi(cout_total),
        "marge_brute_mad": _arrondi(marge),
        "taux_marge_pct": taux_marge,
        "marge_disponible": marge_disponible,
        "couts_manquants_nombre": couts_manquants,
        "depenses_mad": round(depenses_total, 2),
        "depenses_exploitation_mad": round(depenses_exploitation, 2),
        "achats_marchandises_mad": round(depenses_achats, 2),
        "resultat_estime_mad": _arrondi(resultat),
        "mensuel": mensuel,
        "ventes_par_categorie": categories,
        "depenses_par_categorie": depenses_categories,
        "top_clients": top_clients,
        "evolution": evolution,
        "alertes_donnees": alertes,
        "methodologie": (
            "Chiffre d'affaires = ventes au comptant + factures clients émises, "
            "qu'elles soient payées ou non. Marge brute = chiffre d'affaires − coût "
            "d'achat des marchandises. Résultat estimé = marge brute − dépenses "
            "d'exploitation (hors achats de marchandises, déjà comptés dans le coût). "
            "Les montants sont en MAD, sans calcul de TVA."
        ),
    }
