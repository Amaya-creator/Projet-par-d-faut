"""
Définition des outils exposés au LLM et exécution de ces outils.

Le LLM ne calcule rien : il choisit un outil, MIZAN exécute une fonction
Python pure, puis renvoie le résultat au LLM sous forme de JSON. Tous les
chiffres affichés viennent donc des données ou d'un calcul traçable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tools.creances import analyser_creances
from tools.donnees import JeuDonnees
from tools.kpi import analyser_ventes_depenses
from tools.prevision_tresorerie import prevoir_tresorerie
from tools.recommandations import generer_recommandations

# --- Schémas JSON au format attendu par l'API Anthropic --------------------

OUTILS: list[dict[str, Any]] = [
    {
        "name": "analyser_ventes_depenses",
        "description": (
            "Calcule le chiffre d'affaires, les dépenses, la marge brute, le résultat "
            "estimé, les totaux mensuels, les catégories et l'évolution. "
            "À appeler avant toute réponse sur les ventes, les dépenses ou la marge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_debut": {
                    "type": "string",
                    "description": "Début de période au format AAAA-MM-JJ (facultatif).",
                },
                "date_fin": {
                    "type": "string",
                    "description": "Fin de période au format AAAA-MM-JJ (facultatif).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "analyser_creances",
        "description": (
            "Liste les factures clients impayées, calcule les retards, les tranches "
            "d'ancienneté et les créances à risque. À appeler pour toute question "
            "sur les impayés ou les clients qui doivent de l'argent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_reference": {
                    "type": "string",
                    "description": "Date d'analyse AAAA-MM-JJ (facultatif, par défaut la date du dossier).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "prevoir_tresorerie",
        "description": (
            "Projette la trésorerie sur 3 mois (fenêtres de 30 jours) à partir de "
            "l'historique et des échéances de factures. Indique si le solde devient "
            "négatif. À appeler pour toute question sur la trésorerie ou l'avenir."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon_mois": {
                    "type": "integer",
                    "description": "Nombre de mois à projeter, entre 1 et 12 (défaut : 3).",
                    "minimum": 1,
                    "maximum": 12,
                },
                "date_reference": {
                    "type": "string",
                    "description": "Date de départ AAAA-MM-JJ (facultatif).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "generer_recommandations",
        "description": (
            "Génère 3 à 5 actions concrètes, classées par priorité, chacune avec sa "
            "justification chiffrée. À appeler quand l'utilisateur demande que faire "
            "ou comment améliorer sa situation."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "resume_donnees",
        "description": (
            "Décrit les données disponibles : entreprises, période couverte, nombre "
            "de lignes, qualité des données et alertes d'import. À appeler si "
            "l'utilisateur demande quelles données sont disponibles ou si une "
            "information semble manquer."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


@dataclass
class ContexteOutils:
    """Jeu de données courant et journal des appels d'outils."""

    jeu: JeuDonnees
    journal: list[dict[str, Any]] = field(default_factory=list)

    def executer(self, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Exécute un outil et retourne un dictionnaire sérialisable."""
        arguments = arguments or {}
        if nom == "analyser_ventes_depenses":
            resultat = analyser_ventes_depenses(
                self.jeu,
                date_debut=arguments.get("date_debut"),
                date_fin=arguments.get("date_fin"),
            )
        elif nom == "analyser_creances":
            resultat = analyser_creances(self.jeu, arguments.get("date_reference"))
        elif nom == "prevoir_tresorerie":
            resultat = prevoir_tresorerie(
                self.jeu,
                date_reference=arguments.get("date_reference"),
                horizon_mois=int(arguments.get("horizon_mois", 3)),
            )
        elif nom == "generer_recommandations":
            resultat = generer_recommandations(self.jeu)
        elif nom == "resume_donnees":
            resultat = resume_donnees(self.jeu)
        else:
            raise ValueError(f"Outil inconnu : {nom}")

        self.journal.append(
            {
                "outil": nom,
                "arguments": arguments,
                "resultat_resume": _resume_court(nom, resultat),
            }
        )
        return resultat


def _resume_court(nom: str, resultat: dict[str, Any]) -> str:
    """Résumé lisible pour l'interface (pas envoyé au LLM)."""
    if nom == "analyser_ventes_depenses":
        return (
            f"CA {resultat['chiffre_affaires_mad']:,.2f} MAD, "
            f"dépenses {resultat['depenses_mad']:,.2f} MAD"
        ).replace(",", " ")
    if nom == "analyser_creances":
        return (
            f"{resultat['nombre_factures_impayees']} facture(s) impayée(s), "
            f"{resultat['total_creances_mad']:,.2f} MAD à encaisser"
        ).replace(",", " ")
    if nom == "prevoir_tresorerie":
        etat = "négative" if resultat["alerte_negative"] else "positive"
        return f"Trésorerie {etat}, solde final {resultat['solde_final_mad']:,.2f} MAD".replace(",", " ")
    if nom == "generer_recommandations":
        return f"{resultat['nombre_recommandations']} action(s) proposée(s)"
    if nom == "resume_donnees":
        return f"{resultat['nombre_lignes_total']} ligne(s) de données"
    return ""


def resume_donnees(jeu: JeuDonnees) -> dict[str, Any]:
    """Photographie des données disponibles et de leur qualité."""
    debut, fin = jeu.periode_couverte()
    alertes = list(jeu.alertes_import)
    if jeu.ventes.empty:
        alertes.append("Aucune vente au comptant enregistrée.")
    if jeu.depenses.empty:
        alertes.append("Aucune dépense enregistrée.")
    if jeu.factures.empty:
        alertes.append("Aucune facture client enregistrée.")
    if jeu.solde_tresorerie_mad is None:
        alertes.append("Le solde de trésorerie de départ n'est pas renseigné.")
    if jeu.ventes["cout_mad"].isna().any():
        alertes.append("Certaines ventes n'ont pas de coût d'achat : la marge est partielle.")
    return {
        "entreprise": jeu.entreprise,
        "ville": jeu.ville,
        "type_entreprise": jeu.type_entreprise,
        "devise": jeu.devise,
        "date_reference": jeu.date_reference.isoformat(),
        "periode_couverte": {
            "debut": debut.isoformat() if debut else None,
            "fin": fin.isoformat() if fin else None,
        },
        "nombre_ventes": len(jeu.ventes),
        "nombre_depenses": len(jeu.depenses),
        "nombre_factures": len(jeu.factures),
        "nombre_lignes_total": int(len(jeu.ventes) + len(jeu.depenses) + len(jeu.factures)),
        "solde_tresorerie_mad": jeu.solde_tresorerie_mad,
        "donnees_fictives": jeu.fictif,
        "avertissement": jeu.avertissement,
        "alertes_donnees": alertes,
    }


def executer_outil(contexte: ContexteOutils, nom: str, arguments: dict[str, Any]) -> str:
    """Point d'entrée utilisé par la boucle : renvoie toujours une chaîne JSON.

    Toute exception est convertie en JSON lisible par le modèle : l'agent doit
    pouvoir expliquer un manque de données au lieu de planter.
    """
    try:
        resultat = contexte.executer(nom, arguments)
        return json.dumps(resultat, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001 - frontière volontaire avec le LLM
        return json.dumps(
            {"erreur": str(exc), "outil": nom},
            ensure_ascii=False,
        )


def decrire_outils_pour_affichage() -> list[dict[str, str]]:
    """Liste simplifiée pour l'écran « outils disponibles » de l'application."""
    return [
        {"nom": outil["name"], "description": outil["description"]}
        for outil in OUTILS
    ]


__all__ = [
    "OUTILS",
    "ContexteOutils",
    "decrire_outils_pour_affichage",
    "executer_outil",
    "resume_donnees",
]
