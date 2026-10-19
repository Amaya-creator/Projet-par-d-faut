"""
Suivi des créances clients : soldes impayés, retards et créances à risque.

Une facture est « à risque » si elle est en retard de plus de 60 jours, ou si
le client paie habituellement avec plus de 30 jours de retard (moyenne
calculée sur ses factures déjà réglées).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from tools.donnees import JeuDonnees
from tools.formatage import montant_mad

TRANCHES = [
    ("Non échue", None, 0),
    ("1-30 jours", 1, 30),
    ("31-60 jours", 31, 60),
    ("61-90 jours", 61, 90),
    ("Plus de 90 jours", 91, None),
]


def _arrondi(valeur: Any, decimales: int = 2) -> float | None:
    if valeur is None or pd.isna(valeur):
        return None
    return round(float(valeur), decimales)


def _tranche(jours_retard: int) -> str:
    if jours_retard <= 0:
        return "Non échue"
    if jours_retard <= 30:
        return "1-30 jours"
    if jours_retard <= 60:
        return "31-60 jours"
    if jours_retard <= 90:
        return "61-90 jours"
    return "Plus de 90 jours"


def _delais_clients(factures: pd.DataFrame, reference: pd.Timestamp) -> dict[str, dict[str, float]]:
    """Calcule, pour chaque client, le délai moyen de paiement observé.

    Seules les factures soldées avec une date de paiement sont utilisées.
    """
    stats: dict[str, dict[str, float]] = {}
    if factures.empty:
        return stats
    reglees = factures[
        (factures["montant_paye_mad"] >= factures["montant_mad"] - 0.01)
        & factures["date_paiement"].notna()
    ]
    for client, groupe in reglees.groupby("client"):
        delais = (groupe["date_paiement"] - groupe["date_echeance"]).dt.days.clip(lower=0)
        statistiques: dict[str, float] = {
            "nombre_factures_reglees": float(len(groupe)),
        }
        if not delais.empty:
            statistiques["delai_moyen_jours"] = round(float(delais.mean()), 1)
        stats[str(client)] = statistiques
    return stats


def analyser_creances(
    jeu: JeuDonnees,
    date_reference: date | str | None = None,
) -> dict[str, Any]:
    """Analyse les factures clients à la date de référence."""
    reference = pd.Timestamp(date_reference or jeu.date_reference).normalize()
    factures = jeu.factures.copy()
    alertes: list[str] = list(jeu.alertes_import)

    if factures.empty:
        return {
            "entreprise": jeu.entreprise,
            "devise": jeu.devise,
            "date_reference": reference.date().isoformat(),
            "nombre_factures": 0,
            "nombre_factures_impayees": 0,
            "nombre_factures_en_retard": 0,
            "nombre_factures_a_risque": 0,
            "total_facture_mad": 0.0,
            "total_encaisse_mad": 0.0,
            "total_creances_mad": 0.0,
            "total_non_echu_mad": 0.0,
            "total_en_retard_mad": 0.0,
            "total_a_risque_mad": 0.0,
            "part_creances_retard_pct": None,
            "retard_max_jours": 0,
            "delai_moyen_retard_jours": None,
            "par_tranche": [{"tranche": label, "montant_mad": 0.0, "nombre": 0} for label, _, _ in TRANCHES],
            "top_debiteurs": [],
            "factures": [],
            "alertes_donnees": alertes + ["Aucune facture client enregistrée."],
            "methodologie": "Aucune facture à analyser.",
        }

    factures["solde_mad"] = (
        factures["montant_mad"] - factures["montant_paye_mad"]
    ).clip(lower=0.0)
    factures["jours_retard"] = (
        (reference - factures["date_echeance"]).dt.days.clip(lower=0)
    ).astype(int)
    factures["jours_avant_echeance"] = (
        (factures["date_echeance"] - reference).dt.days.clip(lower=0)
    ).astype(int)
    factures["en_retard"] = factures["jours_retard"] > 0
    factures["tranche_retard"] = factures["jours_retard"].map(_tranche)

    delais = _delais_clients(factures, reference)

    def statut(row: pd.Series) -> str:
        if row["solde_mad"] <= 0.01:
            return "Payée"
        base = "Partiellement payée" if row["montant_paye_mad"] > 0 else "Impayée"
        return f"{base} — en retard" if row["en_retard"] else base

    factures["statut"] = factures.apply(statut, axis=1)

    def risque(row: pd.Series) -> tuple[bool, str]:
        if row["solde_mad"] <= 0.01:
            return False, ""
        motifs: list[str] = []
        if row["jours_retard"] > 60:
            motifs.append(f"retard de {int(row['jours_retard'])} jours")
        info_client = delais.get(str(row["client"]), {})
        if info_client.get("delai_moyen_jours", 0) >= 30:
            motifs.append(
                f"client habitué aux retards (moyenne {info_client['delai_moyen_jours']:.0f} jours)"
            )
        if motifs:
            return True, " ; ".join(motifs)
        return False, ""

    resultats_risque = factures.apply(risque, axis=1)
    factures["a_risque"] = [item[0] for item in resultats_risque]
    factures["motif_risque"] = [item[1] for item in resultats_risque]

    impayees = factures[factures["solde_mad"] > 0.01].copy()
    en_retard = impayees[impayees["en_retard"]]
    a_risque = impayees[impayees["a_risque"]]

    total_creances = float(impayees["solde_mad"].sum())
    total_retard = float(en_retard["solde_mad"].sum())
    total_risque = float(a_risque["solde_mad"].sum())
    total_non_echu = max(0.0, total_creances - total_retard)

    tranches: list[dict[str, Any]] = []
    for label, _, _ in TRANCHES:
        sous_ensemble = impayees[impayees["tranche_retard"] == label]
        tranches.append(
            {
                "tranche": label,
                "montant_mad": round(float(sous_ensemble["solde_mad"].sum()), 2),
                "nombre": len(sous_ensemble),
            }
        )

    top_debiteurs: list[dict[str, Any]] = []
    if not impayees.empty:
        for client, groupe in impayees.groupby("client"):
            top_debiteurs.append(
                {
                    "client": str(client),
                    "solde_mad": round(float(groupe["solde_mad"].sum()), 2),
                    "en_retard_mad": round(float(groupe.loc[groupe["en_retard"], "solde_mad"].sum()), 2),
                    "a_risque_mad": round(float(groupe.loc[groupe["a_risque"], "solde_mad"].sum()), 2),
                    "retard_max_jours": int(groupe["jours_retard"].max()),
                    "nombre_factures": len(groupe),
                }
            )
        top_debiteurs.sort(key=lambda item: item["solde_mad"], reverse=True)

    lignes: list[dict[str, Any]] = []
    for _, row in impayees.sort_values(
        ["a_risque", "jours_retard", "solde_mad"], ascending=[False, False, False]
    ).iterrows():
        lignes.append(
            {
                "facture_id": str(row["facture_id"]),
                "client": str(row["client"]),
                "categorie": str(row["categorie"]),
                "date_emission": row["date_emission"].date().isoformat(),
                "date_echeance": row["date_echeance"].date().isoformat(),
                "montant_mad": round(float(row["montant_mad"]), 2),
                "montant_paye_mad": round(float(row["montant_paye_mad"]), 2),
                "solde_mad": round(float(row["solde_mad"]), 2),
                "jours_retard": int(row["jours_retard"]),
                "jours_avant_echeance": int(row["jours_avant_echeance"]),
                "tranche_retard": str(row["tranche_retard"]),
                "statut": str(row["statut"]),
                "a_risque": bool(row["a_risque"]),
                "motif_risque": str(row["motif_risque"]),
            }
        )

    if len(impayees) == 0:
        alertes.append("Toutes les factures enregistrées sont payées.")
    if total_risque > 0:
        alertes.append(
            f"{len(a_risque)} facture(s) à risque pour {montant_mad(total_risque)}."
        )
    invalides = (factures["date_paiement"].notna()) & (
        factures["date_paiement"] < factures["date_emission"]
    )
    if invalides.any():
        alertes.append(
            f"{int(invalides.sum())} date(s) de paiement sont antérieures à la date d'émission."
        )

    retards_positifs = en_retard["jours_retard"]
    return {
        "entreprise": jeu.entreprise,
        "devise": jeu.devise,
        "date_reference": reference.date().isoformat(),
        "nombre_factures": len(factures),
        "nombre_factures_impayees": len(impayees),
        "nombre_factures_en_retard": len(en_retard),
        "nombre_factures_a_risque": len(a_risque),
        "total_facture_mad": round(float(factures["montant_mad"].sum()), 2),
        "total_encaisse_mad": round(float(factures["montant_paye_mad"].sum()), 2),
        "total_creances_mad": round(total_creances, 2),
        "total_non_echu_mad": round(total_non_echu, 2),
        "total_en_retard_mad": round(total_retard, 2),
        "total_a_risque_mad": round(total_risque, 2),
        "part_creances_retard_pct": (
            round(100.0 * total_retard / total_creances, 1) if total_creances else None
        ),
        "retard_max_jours": int(retards_positifs.max()) if not retards_positifs.empty else 0,
        "delai_moyen_retard_jours": (
            round(float(retards_positifs.mean()), 1) if not retards_positifs.empty else None
        ),
        "par_tranche": tranches,
        "top_debiteurs": top_debiteurs[:5],
        "factures": lignes,
        "alertes_donnees": alertes,
        "methodologie": (
            "Solde dû = montant de la facture − montant déjà payé. Le retard est "
            "calculé à la date de référence. Une créance est dite à risque au-delà "
            "de 60 jours de retard, ou si le client a un délai moyen de paiement "
            "supérieur à 30 jours sur ses factures déjà réglées."
        ),
    }
