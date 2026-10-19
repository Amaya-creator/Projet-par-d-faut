"""
Boucle d'agent avec l'API Anthropic et tool use.

Le LLM ne voit jamais les DataFrames. Il voit :
- le prompt système (règles + contexte) ;
- l'historique de la conversation ;
- les résultats JSON des outils qu'il a demandés.

Sans clé API, un mode « hors ligne » répond avec les mêmes fonctions de calcul
et un texte de gabarit. Cela permet de tester l'interface et les chiffres sans
réseau, sans jamais simuler une réponse du modèle.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from agent.outils import OUTILS, ContexteOutils, executer_outil
from agent.prompt import construire_prompt_systeme
from tools.donnees import JeuDonnees
from tools.formatage import montant_mad, pourcentage

MODELE_DEFAUT = os.environ.get("MIZAN_MODEL", "claude-sonnet-4-5")
MAX_TOURS = 8


class AgentIndisponible(RuntimeError):
    """Levée quand l'API ne peut pas être appelée."""


@dataclass
class ReponseAgent:
    """Résultat d'un tour de conversation."""

    texte: str
    outils_utilises: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "api"  # « api » ou « hors_ligne »
    erreur: str | None = None


def cle_api_disponible() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _client_anthropic():
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise AgentIndisponible(
            "La bibliothèque « anthropic » n'est pas installée. "
            "Lancez : pip install -r requirements.txt"
        ) from exc
    cle = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not cle:
        raise AgentIndisponible(
            "La variable d'environnement ANTHROPIC_API_KEY n'est pas définie."
        )
    return Anthropic(api_key=cle)


def _messages_pour_api(historique: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    """Convertit l'historique simple (role/content) au format API."""
    messages: list[dict[str, Any]] = []
    for message in historique:
        role = message.get("role")
        contenu = message.get("content", "")
        if role not in {"user", "assistant"} or not contenu:
            continue
        messages.append({"role": role, "content": contenu})
    return messages


def _extraire_texte(contenu: list[Any]) -> str:
    """Concatène les blocs texte d'une réponse Anthropic."""
    morceaux: list[str] = []
    for bloc in contenu:
        if getattr(bloc, "type", None) == "text":
            morceaux.append(bloc.text)
    return "\n".join(morceaux).strip()


def poser_question(
    jeu: JeuDonnees,
    question: str,
    historique: list[dict[str, str]] | None = None,
    *,
    modele: str | None = None,
    max_tours: int = MAX_TOURS,
) -> ReponseAgent:
    """Envoie une question à l'agent, avec boucle d'appels d'outils.

    Lève AgentIndisponible si l'API ne peut pas être utilisée ; l'appelant peut
    alors basculer sur `reponse_hors_ligne`.
    """
    if not question.strip():
        raise ValueError("La question est vide.")

    client = _client_anthropic()
    modele = modele or MODELE_DEFAUT
    contexte = ContexteOutils(jeu=jeu)
    messages = _messages_pour_api(historique or [])
    messages.append({"role": "user", "content": question.strip()})
    systeme = construire_prompt_systeme(jeu)
    outils_utilises: list[dict[str, Any]] = []

    for _ in range(max_tours):
        try:
            reponse = client.messages.create(
                model=modele,
                max_tokens=1500,
                system=systeme,
                tools=OUTILS,
                messages=list(messages),
            )
        except Exception as exc:  # erreurs réseau, quota, modèle inconnu
            raise AgentIndisponible(f"Appel à l'API impossible : {exc}") from exc

        messages.append({"role": "assistant", "content": reponse.content})

        if reponse.stop_reason != "tool_use":
            texte = _extraire_texte(reponse.content)
            if not texte:
                texte = (
                    "Je n'ai pas pu formuler de réponse à partir des données. "
                    "Reformulez la question ou vérifiez les fichiers importés."
                )
            return ReponseAgent(texte=texte, outils_utilises=outils_utilises, mode="api")

        resultats: list[dict[str, Any]] = []
        for bloc in reponse.content:
            if getattr(bloc, "type", None) != "tool_use":
                continue
            arguments = bloc.input if isinstance(bloc.input, dict) else {}
            sortie = executer_outil(contexte, bloc.name, arguments)
            outils_utilises.append(
                {
                    "outil": bloc.name,
                    "arguments": arguments,
                    "sortie": json.loads(sortie),
                }
            )
            resultats.append(
                {
                    "type": "tool_result",
                    "tool_use_id": bloc.id,
                    "content": sortie,
                }
            )
        messages.append({"role": "user", "content": resultats})

    raise AgentIndisponible(
        "L'agent a dépassé le nombre d'appels d'outils autorisé. "
        "Essayez une question plus précise."
    )


# ---------------------------------------------------------------------------
# Mode hors ligne : mêmes calculs, texte de gabarit
# ---------------------------------------------------------------------------

def _question_sur(question: str, mots: tuple[str, ...]) -> bool:
    texte = question.lower()
    return any(mot in texte for mot in mots)


def reponse_hors_ligne(jeu: JeuDonnees, question: str) -> ReponseAgent:
    """Réponse de secours sans LLM.

    Elle utilise exactement les mêmes fonctions que l'agent. Le texte est un
    gabarit : il ne prétend pas être une réponse du modèle.
    """
    outils_utilises: list[dict[str, Any]] = []
    question_min = question.lower().strip()

    def appeler(nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        contexte = ContexteOutils(jeu=jeu)
        resultat = contexte.executer(nom, arguments)
        outils_utilises.append({"outil": nom, "arguments": arguments, "sortie": resultat})
        return resultat

    if _question_sur(question_min, ("trésorerie", "tresorerie", "solde", "baisse")):
        try:
            prevision = appeler("prevoir_tresorerie", {})
        except ValueError as exc:
            return ReponseAgent(
                texte=(
                    "Je ne peux pas prévoir la trésorerie : " + str(exc) +
                    "\n\nAjoutez le solde de trésorerie dans les paramètres, puis relancez la question."
                ),
                outils_utilises=outils_utilises,
                mode="hors_ligne",
                erreur=str(exc),
            )
        kpi = appeler("analyser_ventes_depenses", {})
        entrees_mensuelles = (
            prevision["ventes_comptant_moyenne_journaliere_mad"] * prevision["hypotheses"]["jours_par_mois"]
        )
        lignes = [
            f"Votre trésorerie de départ est de {montant_mad(prevision['solde_initial_mad'])}.",
            (f"Chaque mois, vous encaissez environ {montant_mad(entrees_mensuelles)} de ventes au comptant "
            f"et vous dépensez {montant_mad(prevision['depenses_mensuelles_estimees_mad'])}."),
        ]
        if prevision["depenses_mensuelles_estimees_mad"] > entrees_mensuelles:
            ecart = prevision["depenses_mensuelles_estimees_mad"] - entrees_mensuelles
            if prevision["alerte_negative"]:
                lignes.append(
                    f"Le problème vient de là : les dépenses dépassent les ventes de "
                    f"{montant_mad(ecart)} par mois, hors encaissement de factures."
                )
            else:
                lignes.append(
                    f"Les dépenses dépassent les ventes de {montant_mad(ecart)} par mois. "
                    "Le solde tient pour l'instant grâce aux factures encaissées."
                )
        lignes.append(
            f"Le solde projeté dans {prevision['horizon_mois']} mois est de "
            f"{montant_mad(prevision['solde_final_mad'])}."
        )
        if prevision["alerte_negative"]:
            lignes.insert(
                0,
                f"Attention : la trésorerie deviendrait négative en "
                f"{prevision['premier_mois_negatif']} (point bas "
                f"{montant_mad(prevision['deficit_max_mad'])}).",
            )
        if kpi["evolution"]["variation_ca_pct"] is not None:
            variation = kpi["evolution"]["variation_ca_pct"]
            mois_recent = next(
                (m["libelle"] for m in kpi["mensuel"] if m["mois"] == kpi["evolution"]["mois_recent"]),
                "dernier mois complet",
            )
            lignes.append(
                f"Le chiffre d'affaires de {mois_recent} a varié de "
                + f"{variation:+.1f}".replace(".", ",")
                + " % par rapport au mois précédent."
            )
        lignes.append(
            "Ces montants sont des estimations calculées à partir de votre historique."
        )
        return ReponseAgent(
            texte="\n".join(f"- {ligne}" for ligne in lignes),
            outils_utilises=outils_utilises,
            mode="hors_ligne",
        )

    if _question_sur(question_min, ("impayé", "impaye", "facture", "client", "créance", "creance", "retard")):
        creances = appeler("analyser_creances", {})
        if creances["nombre_factures_impayees"] == 0:
            texte = "Aucune facture client n'est impayée dans les données importées."
        else:
            lignes = [
                (f"{creances['nombre_factures_impayees']} facture(s) restent à encaisser, "
                f"pour {montant_mad(creances['total_creances_mad'])}."),
                (f"{creances['nombre_factures_en_retard']} facture(s) sont en retard, "
                f"pour {montant_mad(creances['total_en_retard_mad'])}."),
            ]
            if creances["top_debiteurs"]:
                premier = creances["top_debiteurs"][0]
                lignes.append(
                    f"Le premier débiteur est {premier['client']} avec "
                    f"{montant_mad(premier['solde_mad'])}."
                )
            texte = "\n".join(f"- {ligne}" for ligne in lignes)
        return ReponseAgent(texte=texte, outils_utilises=outils_utilises, mode="hors_ligne")

    if _question_sur(question_min, ("que faire", "action", "conseil", "recommand", "améliorer", "ameliorer")):
        resultat = appeler("generer_recommandations", {})
        lignes = []
        for index, action in enumerate(resultat["recommandations"], start=1):
            lignes.append(f"{index}. **{action['titre']}** — {action['action']}")
            lignes.append(f"   Pourquoi : {action['justification']}")
        return ReponseAgent(
            texte="\n".join(lignes),
            outils_utilises=outils_utilises,
            mode="hors_ligne",
        )

    # Question générale : vue d'ensemble.
    resume = appeler("resume_donnees", {})
    kpi = appeler("analyser_ventes_depenses", {})
    creances = appeler("analyser_creances", {})
    lignes = [
        f"Entreprise : {resume['entreprise']} ({resume['nombre_lignes_total']} lignes de données).",
        f"Chiffre d'affaires : {montant_mad(kpi['chiffre_affaires_mad'])}.",
        f"Dépenses : {montant_mad(kpi['depenses_mad'])}.",
    ]
    if kpi["marge_disponible"]:
        lignes.append(
            f"Marge brute : {montant_mad(kpi['marge_brute_mad'])} "
            f"({pourcentage(kpi['taux_marge_pct'])})."
        )
    lignes.append(f"Créances clients : {montant_mad(creances['total_creances_mad'])}.")
    return ReponseAgent(
        texte="\n".join(f"- {ligne}" for ligne in lignes),
        outils_utilises=outils_utilises,
        mode="hors_ligne",
    )


def repondre(
    jeu: JeuDonnees,
    question: str,
    historique: list[dict[str, str]] | None = None,
    *,
    forcer_hors_ligne: bool = False,
    modele: str | None = None,
) -> ReponseAgent:
    """Répond avec l'API si possible, sinon en mode hors ligne."""
    if forcer_hors_ligne or not cle_api_disponible():
        return reponse_hors_ligne(jeu, question)
    try:
        return poser_question(jeu, question, historique, modele=modele)
    except AgentIndisponible as exc:
        reponse = reponse_hors_ligne(jeu, question)
        reponse.erreur = str(exc)
        reponse.texte = (
            "L'agent IA n'a pas pu être joint. Voici les chiffres calculés localement.\n\n"
            + reponse.texte
        )
        return reponse
