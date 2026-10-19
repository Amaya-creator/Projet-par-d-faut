"""
Prévision simple de trésorerie sur 3 mois (fenêtres de 30 jours).

Principe, volontairement transparent :
- les ventes au comptant sont prolongées à partir de la moyenne journalière
  observée sur les 90 derniers jours ;
- les dépenses sont prolongées de la même façon ;
- les factures clients impayées sont encaissées à leur échéance si elle tombe
  dans l'horizon ; les factures déjà en retard sont encaissées dans le premier
  mois avec un taux de recouvrement indiqué en hypothèse.

Les hypothèses sont affichées dans le résultat. Elles ne sont pas des
statistiques observées : l'agent doit le dire clairement.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from tools.donnees import JeuDonnees
from tools.formatage import montant_mad

HYPOTHESES_DEFAUT = {
    "taux_recouvrement_retard": 0.70,
    "taux_recouvrement_contentieux": 0.30,
    "repartition_recouvrement_retard": [0.50, 0.30, 0.20],
    "jours_par_mois": 30,
    "fenetre_historique_jours": 90,
    "historique_minimum_jours": 30,
}


def _arrondi(valeur: Any, decimales: int = 2) -> float:
    return round(float(valeur), decimales)


def _libelle_fenetre(debut: pd.Timestamp, fin: pd.Timestamp, numero: int) -> str:
    return f"Mois {numero} — {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}"


def _moyenne_journaliere(
    df: pd.DataFrame,
    colonne_date: str,
    colonne_montant: str,
    reference: pd.Timestamp,
    fenetre_jours: int,
    minimum_jours: int,
) -> tuple[float, int]:
    """Retourne (moyenne par jour, nombre de jours d'historique utilisés)."""
    if df.empty:
        return 0.0, 0
    debut = reference - pd.Timedelta(fenetre_jours - 1, unit="D")
    fenetre = df[(df[colonne_date] >= debut) & (df[colonne_date] <= reference)]
    if fenetre.empty:
        return 0.0, 0
    premiere_date = fenetre[colonne_date].min()
    jours_disponibles = int((reference - premiere_date).days) + 1
    jours_disponibles = min(jours_disponibles, fenetre_jours)
    if jours_disponibles < minimum_jours:
        return 0.0, jours_disponibles
    return float(fenetre[colonne_montant].sum()) / jours_disponibles, jours_disponibles


def prevoir_tresorerie(
    jeu: JeuDonnees,
    date_reference: date | str | None = None,
    horizon_mois: int = 3,
) -> dict[str, Any]:
    """Projette la trésorerie sur plusieurs fenêtres de 30 jours.

    Lève ValueError si le solde de départ manque ou si l'historique est trop court.
    """
    if horizon_mois < 1 or horizon_mois > 12:
        raise ValueError("L'horizon doit être compris entre 1 et 12 mois.")

    reference = pd.Timestamp(date_reference or jeu.date_reference).normalize()
    hypotheses = {**HYPOTHESES_DEFAUT, **(jeu.hypotheses or {})}
    taux_retard = float(hypotheses["taux_recouvrement_retard"])
    taux_contentieux = float(hypotheses["taux_recouvrement_contentieux"])
    jours_par_mois = int(hypotheses["jours_par_mois"])
    fenetre = int(hypotheses["fenetre_historique_jours"])
    minimum = int(hypotheses["historique_minimum_jours"])

    if jeu.solde_tresorerie_mad is None:
        raise ValueError(
            "Le solde de trésorerie de départ n'est pas renseigné. "
            "Ajoutez-le dans les paramètres avant de lancer la prévision."
        )

    if jeu.ventes.empty and jeu.depenses.empty:
        raise ValueError("Aucune vente ni dépense : impossible de construire une prévision.")

    ventes_moyenne, jours_ventes = _moyenne_journaliere(
        jeu.ventes, "date", "montant_mad", reference, fenetre, minimum
    )
    depenses_moyenne, jours_depenses = _moyenne_journaliere(
        jeu.depenses, "date", "montant_mad", reference, fenetre, minimum
    )
    if jours_ventes < minimum and jours_depenses < minimum:
        raise ValueError(
            "Historique insuffisant : il faut au moins "
            f"{minimum} jours de ventes ou de dépenses avant la date de référence. "
            f"Disponible : {max(jours_ventes, jours_depenses)} jour(s)."
        )

    alertes: list[str] = list(jeu.alertes_import)
    if jours_ventes < minimum:
        alertes.append(
            f"Moins de {minimum} jours de ventes au comptant : la prévision des "
            "encaissements est peu fiable."
        )
        ventes_moyenne = 0.0
    if jours_depenses < minimum:
        alertes.append(
            f"Moins de {minimum} jours de dépenses : la prévision des sorties est peu fiable."
        )
        depenses_moyenne = 0.0
    if jeu.factures.empty:
        alertes.append("Aucune facture client : la prévision ne contient aucun encaissement de facture.")

    # --- Encaissements des factures ----------------------------------------
    # Les factures en retard ne sont pas encaissées d'un coup : on étale le
    # montant attendu sur les trois premiers mois selon une répartition
    # indiquée en hypothèse (50 %, 30 %, 20 % par défaut).
    repartition = hypotheses.get("repartition_recouvrement_retard") or [0.50, 0.30, 0.20]
    if not isinstance(repartition, (list, tuple)):
        repartition = [float(repartition)]
    total_repartition = sum(float(x) for x in repartition) or 1.0
    repartition = [float(x) / total_repartition for x in repartition]

    detail_recouvrement: list[dict[str, Any]] = []
    if not jeu.factures.empty:
        for _, facture in jeu.factures.iterrows():
            solde = float(facture["montant_mad"]) - float(facture["montant_paye_mad"])
            if solde <= 0.01:
                continue
            echeance = pd.Timestamp(facture["date_echeance"]).normalize()
            jours = (echeance - reference).days

            if jours > 0:
                index = (jours - 1) // jours_par_mois
                if index >= horizon_mois:
                    continue  # échéance au-delà de l'horizon
                detail_recouvrement.append(
                    {
                        "facture_id": str(facture["facture_id"]),
                        "client": str(facture["client"]),
                        "date_echeance": echeance.date().isoformat(),
                        "mois": index + 1,
                        "solde_mad": round(solde, 2),
                        "type_recouvrement": "à échéance",
                        "taux_applique": 1.0,
                        "montant_attendu_mad": round(solde, 2),
                    }
                )
                continue

            # Facture déjà échue : on étale le recouvrement attendu.
            retard = -jours
            taux = taux_contentieux if retard > 90 else taux_retard
            montant_attendu = solde * taux
            restant = montant_attendu
            for decalage, part in enumerate(repartition):
                index = decalage
                if index >= horizon_mois:
                    break
                montant_mois = round(montant_attendu * part, 2)
                if decalage == len(repartition) - 1:
                    montant_mois = round(restant, 2)
                restant -= montant_mois
                if montant_mois <= 0:
                    continue
                detail_recouvrement.append(
                    {
                        "facture_id": str(facture["facture_id"]),
                        "client": str(facture["client"]),
                        "date_echeance": echeance.date().isoformat(),
                        "mois": index + 1,
                        "solde_mad": round(solde, 2),
                        "type_recouvrement": "en retard",
                        "taux_applique": taux,
                        "montant_attendu_mad": montant_mois,
                    }
                )

    # --- Construction des fenêtres de 30 jours ------------------------------
    mois: list[dict[str, Any]] = []
    solde = float(jeu.solde_tresorerie_mad)
    premier_mois_negatif: str | None = None
    deficit_max = 0.0

    for index in range(horizon_mois):
        debut = reference + pd.Timedelta(1 + index * jours_par_mois, unit="D")
        fin = reference + pd.Timedelta((index + 1) * jours_par_mois, unit="D")
        ventes_prevues = ventes_moyenne * jours_par_mois
        depenses_prevues = depenses_moyenne * jours_par_mois
        recouvrement = sum(
            item["montant_attendu_mad"]
            for item in detail_recouvrement
            if item["mois"] == index + 1
        )
        entrees = ventes_prevues + recouvrement
        solde_fin = solde + entrees - depenses_prevues
        negatif = solde_fin < 0
        if negatif and premier_mois_negatif is None:
            premier_mois_negatif = _libelle_fenetre(debut, fin, index + 1)
        deficit_max = min(deficit_max, solde_fin)

        mois.append(
            {
                "numero": index + 1,
                "libelle": _libelle_fenetre(debut, fin, index + 1),
                "debut": debut.date().isoformat(),
                "fin": fin.date().isoformat(),
                "solde_debut_mad": _arrondi(solde),
                "ventes_comptant_prevues_mad": _arrondi(ventes_prevues),
                "recouvrement_factures_mad": _arrondi(recouvrement),
                "total_entrees_mad": _arrondi(entrees),
                "depenses_prevues_mad": _arrondi(depenses_prevues),
                "total_sorties_mad": _arrondi(depenses_prevues),
                "solde_fin_mad": _arrondi(solde_fin),
                "alerte_negative": bool(negatif),
            }
        )
        solde = solde_fin

    depenses_mensuelles = depenses_moyenne * jours_par_mois
    couverture = (
        float(jeu.solde_tresorerie_mad) / depenses_mensuelles if depenses_mensuelles > 0 else None
    )

    if premier_mois_negatif:
        alertes.append(
            f"Trésorerie négative prévue : {premier_mois_negatif}, "
            f"avec un point bas de {montant_mad(deficit_max)}."
        )
    if detail_recouvrement:
        montant_retard = sum(
            item["montant_attendu_mad"] for item in detail_recouvrement if item["type_recouvrement"] == "en retard"
        )
        if montant_retard:
            alertes.append(
                "Les encaissements de factures en retard reposent sur une hypothèse de "
                f"recouvrement, pas sur une certitude ({montant_mad(montant_retard)} attendus)."
            )

    return {
        "entreprise": jeu.entreprise,
        "devise": jeu.devise,
        "date_reference": reference.date().isoformat(),
        "horizon_mois": horizon_mois,
        "solde_initial_mad": _arrondi(jeu.solde_tresorerie_mad),
        "ventes_comptant_moyenne_journaliere_mad": _arrondi(ventes_moyenne),
        "depenses_moyenne_journaliere_mad": _arrondi(depenses_moyenne),
        "depenses_mensuelles_estimees_mad": _arrondi(depenses_mensuelles),
        "couverture_tresorerie_mois": _arrondi(couverture, 1) if couverture is not None else None,
        "jours_historique_ventes": jours_ventes,
        "jours_historique_depenses": jours_depenses,
        "mois": mois,
        "total_entrees_mad": _arrondi(sum(m["total_entrees_mad"] for m in mois)),
        "total_sorties_mad": _arrondi(sum(m["total_sorties_mad"] for m in mois)),
        "solde_final_mad": mois[-1]["solde_fin_mad"] if mois else _arrondi(jeu.solde_tresorerie_mad),
        "alerte_negative": premier_mois_negatif is not None,
        "premier_mois_negatif": premier_mois_negatif,
        "deficit_max_mad": _arrondi(abs(deficit_max)),
        "detail_recouvrement": detail_recouvrement,
        "hypotheses": {
            "taux_recouvrement_retard": taux_retard,
            "taux_recouvrement_contentieux": taux_contentieux,
            "repartition_recouvrement_retard": repartition,
            "jours_par_mois": jours_par_mois,
            "fenetre_historique_jours": fenetre,
            "historique_minimum_jours": minimum,
        },
        "alertes_donnees": alertes,
        "methodologie": (
            "Ventes et dépenses prolongées à partir de la moyenne journalière des "
            f"{fenetre} derniers jours (ou de l'historique disponible). Factures non "
            "échues encaissées à leur échéance. Factures en retard étalées sur les "
            "premiers mois avec le taux de recouvrement et la répartition indiqués "
            "en hypothèses. Les montants sont des estimations, pas des garanties."
        ),
    }
