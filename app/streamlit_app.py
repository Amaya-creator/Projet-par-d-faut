"""
Interface Streamlit de MIZAN AI.

Lancement :
    streamlit run app/streamlit_app.py

L'interface ne fait aucun calcul elle-même : elle appelle les fonctions de
`tools/` et l'agent de `agent/`. Les montants affichés viennent donc toujours
des mêmes sources que celles utilisées par le chat.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# Permet « streamlit run app/streamlit_app.py » depuis la racine du projet.
RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from agent.agent import cle_api_disponible, repondre
from agent.outils import decrire_outils_pour_affichage
from tools.creances import analyser_creances
from tools.donnees import (
    ErreurDonnees,
    charger_jeu_dossier,
    construire_jeu,
    modeles_import,
)
from tools.formatage import mois_francais, montant_court, montant_mad, pourcentage
from tools.kpi import analyser_ventes_depenses
from tools.prevision_tresorerie import prevoir_tresorerie
from tools.recommandations import generer_recommandations

st.set_page_config(
    page_title="MIZAN AI — copilote financier",
    page_icon="⚖️",
    layout="wide",
)

DEMOS = {
    "Épicerie Al Baraka (Casablanca)": "data/epicerie",
    "Coopérative Tiznit Miel (Tiznit)": "data/cooperative",
}


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def charger_demo(chemin: str) -> object:
    return charger_jeu_dossier(RACINE / chemin)


def _charger_depuis_upload(
    fichiers: dict[str, object],
    entreprise: str,
    date_reference: date,
    solde: float | None,
) -> object:
    """Construit un jeu de données à partir des trois fichiers importés."""
    return construire_jeu(
        ventes=fichiers["ventes"],
        depenses=fichiers["depenses"],
        factures=fichiers["factures"],
        entreprise=entreprise,
        date_reference=date_reference,
        solde_tresorerie_mad=solde,
        source="Fichiers importés",
    )


def barre_laterale() -> tuple[object | None, str]:
    st.sidebar.title("⚖️ MIZAN AI")
    st.sidebar.caption("Copilote financier pour petites entreprises marocaines")

    source = st.sidebar.radio(
        "Source des données",
        ["Données fictives de démonstration", "Importer mes fichiers"],
        help="Les données de démonstration sont entièrement fictives.",
    )

    if source == "Données fictives de démonstration":
        choix = st.sidebar.selectbox("Entreprise fictive", list(DEMOS))
        try:
            jeu = charger_demo(DEMOS[choix])
        except ErreurDonnees as exc:
            st.sidebar.error(str(exc))
            return None, source
        st.sidebar.warning("Données fictives : aucune entreprise réelle.")
        return jeu, source

    st.sidebar.subheader("Fichiers")
    ventes = st.sidebar.file_uploader("Ventes au comptant", type=["csv", "xlsx"])
    depenses = st.sidebar.file_uploader("Dépenses", type=["csv", "xlsx"])
    factures = st.sidebar.file_uploader("Factures clients", type=["csv", "xlsx"])

    st.sidebar.subheader("Paramètres")
    entreprise = st.sidebar.text_input("Nom de l'entreprise", "Mon entreprise")
    date_reference = st.sidebar.date_input("Date de référence", value=date.today())
    solde = st.sidebar.number_input(
        "Solde de trésorerie (MAD)",
        min_value=0.0,
        value=0.0,
        step=500.0,
        help="Le solde disponible aujourd'hui sur le compte de l'entreprise.",
    )

    with st.sidebar.expander("Télécharger les modèles CSV"):
        for nom, contenu in modeles_import().items():
            st.download_button(nom, contenu, file_name=nom, mime="text/csv", key=f"modele_{nom}")

    if not (ventes and depenses and factures):
        st.sidebar.info("Importez les trois fichiers pour lancer l'analyse.")
        return None, source

    try:
        jeu = _charger_depuis_upload(
            {"ventes": ventes, "depenses": depenses, "factures": factures},
            entreprise,
            date_reference,
            solde if solde > 0 else None,
        )
    except ErreurDonnees as exc:
        st.sidebar.error(str(exc))
        return None, source
    return jeu, source


# ---------------------------------------------------------------------------
# Composants d'affichage
# ---------------------------------------------------------------------------

def entete(jeu) -> None:
    st.title("⚖️ MIZAN AI")
    st.caption(
        "Vos chiffres, expliqués simplement. Tous les montants sont en dirhams (MAD)."
    )
    if jeu.fictif:
        st.warning(
            "**Données fictives.** " + (jeu.avertissement or "Aucune entreprise réelle.")
        )
    st.subheader(jeu.entreprise)
    details = [f"Date de référence : **{jeu.date_reference.strftime('%d/%m/%Y')}**"]
    if jeu.ville:
        details.append(jeu.ville)
    if jeu.type_entreprise:
        details.append(jeu.type_entreprise)
    st.caption(" · ".join(details))


def carte_colonnes(valeurs: list[tuple[str, str, str | None]]) -> None:
    colonnes = st.columns(len(valeurs))
    for colonne, (libelle, valeur, aide) in zip(colonnes, valeurs):
        colonne.metric(libelle, valeur, help=aide)


def afficher_alertes(alertes: list[str]) -> None:
    if not alertes:
        return
    with st.expander(f"⚠️ Points à vérifier ({len(alertes)})", expanded=False):
        for alerte in alertes:
            st.write(f"- {alerte}")


def onglet_vue_ensemble(jeu) -> None:
    kpi = analyser_ventes_depenses(jeu)
    creances = analyser_creances(jeu)
    try:
        prevision = prevoir_tresorerie(jeu)
    except ValueError as exc:
        prevision = None
        st.info(f"Prévision indisponible : {exc}")

    carte_colonnes(
        [
            ("Chiffre d'affaires", montant_court(kpi["chiffre_affaires_mad"]), "Ventes au comptant + factures émises"),
            ("Dépenses", montant_court(kpi["depenses_mad"]), "Toutes les sorties enregistrées"),
            ("Marge brute", montant_court(kpi["marge_brute_mad"]) if kpi["marge_disponible"] else "non calculable",
             "Chiffre d'affaires − coût d'achat"),
            ("Créances clients", montant_court(creances["total_creances_mad"]), "Factures non encore payées"),
        ]
    )
    if prevision:
        carte_colonnes(
            [
                ("Trésorerie aujourd'hui", montant_court(prevision["solde_initial_mad"]), "Solde de départ"),
                (f"Trésorerie dans {prevision['horizon_mois']} mois", montant_court(prevision["solde_final_mad"]), "Estimation"),
                ("Factures en retard", montant_court(creances["total_en_retard_mad"]), "À relancer en priorité"),
                ("Créances à risque", montant_court(creances["total_a_risque_mad"]), "Retard > 60 jours ou client habituellement en retard"),
            ]
        )
        if prevision["alerte_negative"]:
            st.error(
                f"**Alerte trésorerie.** Le solde deviendrait négatif en "
                f"{prevision['premier_mois_negatif']}, avec un point bas de "
                f"{montant_mad(prevision['deficit_max_mad'])}. "
                "Voir l'onglet Trésorerie et les recommandations."
            )

    st.markdown("### Ce qu'il faut retenir")
    recommandations = generer_recommandations(jeu)
    for action in recommandations["recommandations"][:3]:
        st.markdown(f"**{action['titre']}.** {action['action']}")
        st.caption(f"Pourquoi : {action['justification']}")

    afficher_alertes(
        list(dict.fromkeys(kpi["alertes_donnees"] + creances["alertes_donnees"]))
    )


def onglet_ventes(jeu) -> None:
    kpi = analyser_ventes_depenses(jeu)
    st.subheader("Ventes et dépenses")

    carte_colonnes(
        [
            ("Ventes au comptant", montant_mad(kpi["ventes_comptant_mad"]), None),
            ("Factures émises", montant_mad(kpi["factures_emises_mad"]), "Comptées dans le CA, payées ou non"),
            ("Marge brute", montant_mad(kpi["marge_brute_mad"]) if kpi["marge_disponible"] else "non calculable",
             "Après coût d'achat des marchandises"),
            ("Résultat estimé", montant_mad(kpi["resultat_estime_mad"]) if kpi["resultat_estime_mad"] is not None else "non calculable",
             "Marge − dépenses d'exploitation"),
        ]
    )

    if kpi["mensuel"]:
        st.markdown("### Évolution mois par mois")
        graphique = pd.DataFrame(
            [
                {
                    "Mois": m["libelle"],
                    "Chiffre d'affaires": m["ca_mad"],
                    "Dépenses": m["depenses_mad"],
                }
                for m in kpi["mensuel"]
            ]
        ).set_index("Mois")
        st.bar_chart(graphique, height=320)
        if any(m["partiel"] for m in kpi["mensuel"]):
            st.caption("Le dernier mois est incomplet : il est affiché mais exclu des comparaisons.")

        with st.expander("Voir le détail mensuel"):
            tableau = pd.DataFrame(kpi["mensuel"])[
                ["libelle", "ca_mad", "marge_brute_mad", "depenses_mad", "resultat_estime_mad", "partiel"]
            ].rename(
                columns={
                    "libelle": "Mois",
                    "ca_mad": "CA (MAD)",
                    "marge_brute_mad": "Marge (MAD)",
                    "depenses_mad": "Dépenses (MAD)",
                    "resultat_estime_mad": "Résultat (MAD)",
                    "partiel": "Mois incomplet",
                }
            )
            st.dataframe(tableau, use_container_width=True, hide_index=True)

    evolution = kpi["evolution"]
    if evolution["variation_ca_pct"] is not None:
        st.markdown("### Évolution")
        recent = next(
            (m["libelle"] for m in kpi["mensuel"] if m["mois"] == evolution["mois_recent"]),
            evolution["mois_recent"],
        )
        precedent = next(
            (m["libelle"] for m in kpi["mensuel"] if m["mois"] == evolution["mois_precedent"]),
            evolution["mois_precedent"],
        )
        st.write(
            f"Entre **{precedent}** et **{recent}** : "
            f"chiffre d'affaires {pourcentage(evolution['variation_ca_pct'])}, "
            f"dépenses {pourcentage(evolution['variation_depenses_pct'])}."
        )

    colonne_gauche, colonne_droite = st.columns(2)
    with colonne_gauche:
        st.markdown("#### Ventes par catégorie")
        if kpi["ventes_par_categorie"]:
            st.dataframe(
                pd.DataFrame(kpi["ventes_par_categorie"]).rename(
                    columns={
                        "categorie": "Catégorie",
                        "ca_mad": "CA (MAD)",
                        "part_ca_pct": "Part du CA (%)",
                        "marge_brute_mad": "Marge (MAD)",
                        "taux_marge_pct": "Taux de marge (%)",
                    }
                )[
                    ["Catégorie", "CA (MAD)", "Part du CA (%)", "Marge (MAD)", "Taux de marge (%)"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Aucune vente sur la période.")
    with colonne_droite:
        st.markdown("#### Dépenses par poste")
        if kpi["depenses_par_categorie"]:
            st.dataframe(
                pd.DataFrame(kpi["depenses_par_categorie"]).rename(
                    columns={
                        "categorie": "Poste",
                        "montant_mad": "Montant (MAD)",
                        "part_pct": "Part (%)",
                        "nombre_lignes": "Lignes",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Aucune dépense sur la période.")

    afficher_alertes(kpi["alertes_donnees"])
    st.caption(kpi["methodologie"])


def onglet_creances(jeu) -> None:
    creances = analyser_creances(jeu)
    st.subheader("Créances clients")
    st.caption(f"Situation au {jeu.date_reference.strftime('%d/%m/%Y')}")

    carte_colonnes(
        [
            ("Total à encaisser", montant_mad(creances["total_creances_mad"]), "Factures non soldées"),
            ("Dont en retard", montant_mad(creances["total_en_retard_mad"]), None),
            ("Dont à risque", montant_mad(creances["total_a_risque_mad"]), "Retard > 60 jours ou client habituellement en retard"),
            ("Retard maximum", f"{creances['retard_max_jours']} jours", None),
        ]
    )

    if creances["factures"]:
        st.markdown("### Factures à encaisser")
        tableau = pd.DataFrame(creances["factures"]).rename(
            columns={
                "facture_id": "Facture",
                "client": "Client",
                "date_echeance": "Échéance",
                "solde_mad": "Reste dû (MAD)",
                "jours_retard": "Retard (jours)",
                "tranche_retard": "Ancienneté",
                "statut": "Statut",
                "a_risque": "À risque",
                "motif_risque": "Pourquoi",
            }
        )[
            ["Facture", "Client", "Échéance", "Reste dû (MAD)", "Retard (jours)", "Statut", "À risque", "Pourquoi"]
        ]
        st.dataframe(tableau, use_container_width=True, hide_index=True)

        st.markdown("### Répartition par ancienneté")
        tranches = pd.DataFrame(creances["par_tranche"]).rename(
            columns={"tranche": "Tranche", "montant_mad": "Montant (MAD)", "nombre": "Factures"}
        )
        st.bar_chart(tranches.set_index("Tranche")["Montant (MAD)"], height=260)
    else:
        st.success("Aucune facture impayée. Toutes les factures sont réglées.")

    afficher_alertes(creances["alertes_donnees"])
    st.caption(creances["methodologie"])


def onglet_tresorerie(jeu) -> None:
    st.subheader("Prévision de trésorerie")
    try:
        prevision = prevoir_tresorerie(jeu)
    except ValueError as exc:
        st.warning(str(exc))
        return

    carte_colonnes(
        [
            ("Solde de départ", montant_mad(prevision["solde_initial_mad"]), None),
            ("Dépenses estimées / mois", montant_mad(prevision["depenses_mensuelles_estimees_mad"]), "Moyenne des 90 derniers jours"),
            ("Solde à la fin", montant_mad(prevision["solde_final_mad"]), "Estimation"),
            ("Réserve", mois_francais(prevision["couverture_tresorerie_mois"]), "Mois de dépenses couverts"),
        ]
    )

    if prevision["alerte_negative"]:
        st.error(
            f"**Alerte.** Trésorerie négative prévue en {prevision['premier_mois_negatif']}. "
            f"Point bas : {montant_mad(prevision['deficit_max_mad'])}."
        )
    else:
        st.success("La trésorerie reste positive sur les trois prochains mois, selon les hypothèses ci-dessous.")

    st.markdown("### Projection sur 3 mois")
    tableau = pd.DataFrame(prevision["mois"]).rename(
        columns={
            "libelle": "Période",
            "solde_debut_mad": "Solde début (MAD)",
            "ventes_comptant_prevues_mad": "Ventes comptant (MAD)",
            "recouvrement_factures_mad": "Factures encaissées (MAD)",
            "depenses_prevues_mad": "Dépenses (MAD)",
            "solde_fin_mad": "Solde fin (MAD)",
        }
    )[
        [
            "Période",
            "Solde début (MAD)",
            "Ventes comptant (MAD)",
            "Factures encaissées (MAD)",
            "Dépenses (MAD)",
            "Solde fin (MAD)",
        ]
    ]
    st.dataframe(tableau, use_container_width=True, hide_index=True)

    graphique = tableau.set_index("Période")[["Solde fin (MAD)"]]
    st.line_chart(graphique, height=260)

    with st.expander("Hypothèses utilisées"):
        hypotheses = prevision["hypotheses"]
        st.write(
            f"- Moyenne calculée sur **{hypotheses['fenetre_historique_jours']} jours** "
            f"d'historique, avec un minimum de {hypotheses['historique_minimum_jours']} jours."
        )
        st.write(
            f"- Factures en retard : **{pourcentage(hypotheses['taux_recouvrement_retard'] * 100, 0)}** "
            f"encaissées sur les mois suivants ; au-delà de 90 jours de retard : "
            f"**{pourcentage(hypotheses['taux_recouvrement_contentieux'] * 100, 0)}**."
        )
        st.write(
            "- Répartition du recouvrement : "
            + ", ".join(
                pourcentage(part * 100, 0)
                for part in hypotheses["repartition_recouvrement_retard"]
            )
            + " sur les premiers mois."
        )
        st.write(f"- Un mois = {hypotheses['jours_par_mois']} jours.")
        st.caption(
            "Ces taux sont des hypothèses de travail, pas des statistiques observées. "
            "Elles sont modifiables dans le fichier parametres.json."
        )

    if prevision["detail_recouvrement"]:
        with st.expander("Détail des encaissements de factures"):
            st.dataframe(
                pd.DataFrame(prevision["detail_recouvrement"]).rename(
                    columns={
                        "facture_id": "Facture",
                        "client": "Client",
                        "date_echeance": "Échéance",
                        "mois": "Mois prévu",
                        "solde_mad": "Reste dû (MAD)",
                        "type_recouvrement": "Type",
                        "taux_applique": "Taux appliqué",
                        "montant_attendu_mad": "Montant attendu (MAD)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    afficher_alertes(prevision["alertes_donnees"])
    st.caption(prevision["methodologie"])


def onglet_recommandations(jeu) -> None:
    st.subheader("Recommandations")
    resultat = generer_recommandations(jeu)
    st.caption(
        f"{resultat['nombre_recommandations']} actions concrètes, classées par priorité. "
        "Chaque action cite les chiffres qui la justifient."
    )
    for index, action in enumerate(resultat["recommandations"], start=1):
        with st.container(border=True):
            st.markdown(f"#### {index}. {action['titre']}")
            st.write(action["action"])
            st.markdown(f"**Pourquoi :** {action['justification']}")
            if action["chiffres"]:
                st.caption(
                    "Chiffres utilisés : "
                    + " · ".join(f"{c['libelle']} : {c['valeur']}" for c in action["chiffres"])
                )
    afficher_alertes(resultat["alertes_donnees"])
    st.caption(resultat["methodologie"])


def onglet_chat(jeu, source: str) -> None:
    st.subheader("Poser une question")
    st.caption(
        "L'agent appelle les fonctions de calcul. Il ne calcule pas les chiffres lui-même."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "derniers_outils" not in st.session_state:
        st.session_state.derniers_outils = []

    api_ok = cle_api_disponible()
    if not api_ok:
        st.info(
            "Mode hors ligne : la variable ANTHROPIC_API_KEY n'est pas définie. "
            "Les calculs sont réels, mais les réponses utilisent un gabarit et non le modèle."
        )

    exemples = [
        "Pourquoi ma trésorerie baisse ?",
        "Quelles factures sont impayées ?",
        "Que faire pour améliorer ma situation ?",
        "Quel est mon chiffre d'affaires du mois dernier ?",
    ]
    colonnes = st.columns(len(exemples))
    for colonne, exemple in zip(colonnes, exemples):
        if colonne.button(exemple, key=f"exemple_{exemple}", use_container_width=True):
            st.session_state.question_preparee = exemple

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Écrivez votre question…")
    if "question_preparee" in st.session_state:
        question = st.session_state.pop("question_preparee")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Je consulte vos chiffres…"):
                reponse = repondre(jeu, question, st.session_state.messages[:-1])
            st.markdown(reponse.texte)
            if reponse.erreur:
                st.caption(f"Note technique : {reponse.erreur}")
            if reponse.outils_utilises:
                with st.expander("Outils appelés par l'agent"):
                    for appel in reponse.outils_utilises:
                        st.markdown(f"**{appel['outil']}** — arguments : `{appel['arguments']}`")
                        with st.expander("Voir le résultat brut"):
                            st.json(appel["sortie"])

        st.session_state.messages.append({"role": "assistant", "content": reponse.texte})
        st.session_state.derniers_outils = reponse.outils_utilises

    if st.session_state.messages and st.button("Effacer la conversation"):
        st.session_state.messages = []
        st.session_state.derniers_outils = []
        st.rerun()

    with st.expander("Outils que l'agent peut appeler"):
        for outil in decrire_outils_pour_affichage():
            st.markdown(f"**{outil['nom']}** — {outil['description']}")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def main() -> None:
    jeu, source = barre_laterale()
    if jeu is None:
        st.title("⚖️ MIZAN AI")
        st.write(
            "Importez vos ventes, vos dépenses et vos factures clients pour obtenir "
            "une analyse simple de votre trésorerie."
        )
        st.markdown(
            """
            **Comment ça marche**

            1. Importez trois fichiers : ventes au comptant, dépenses, factures clients.
            2. L'application calcule votre chiffre d'affaires, votre marge et vos impayés.
            3. Elle projette votre trésorerie sur trois mois.
            4. Elle propose des actions concrètes, avec les chiffres qui les justifient.
            5. Vous pouvez poser vos questions en langage simple.

            Les montants sont en dirhams (MAD). Aucune donnée n'est envoyée à un
            serveur sans votre action : le chat utilise l'API Anthropic uniquement
            si une clé est configurée.
            """
        )
        return

    entete(jeu)
    onglets = st.tabs(
        ["Vue d'ensemble", "Ventes et dépenses", "Créances", "Trésorerie", "Recommandations", "Chat"]
    )
    with onglets[0]:
        onglet_vue_ensemble(jeu)
    with onglets[1]:
        onglet_ventes(jeu)
    with onglets[2]:
        onglet_creances(jeu)
    with onglets[3]:
        onglet_tresorerie(jeu)
    with onglets[4]:
        onglet_recommandations(jeu)
    with onglets[5]:
        onglet_chat(jeu, source)


if __name__ == "__main__":
    main()
