"""
Génération d'actions concrètes, fondées sur les calculs des autres modules.

Chaque recommandation contient :
- une action courte et réalisable ;
- une justification qui reprend des chiffres calculés ;
- la liste des chiffres utilisés.

Le moteur est déterministe : aucune action ne dépend d'une statistique
extérieure ou inventée. L'agent IA peut reformuler ces actions, mais ne doit
pas modifier les montants.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tools.creances import analyser_creances
from tools.donnees import JeuDonnees
from tools.formatage import mois_francais, montant_mad, pourcentage
from tools.kpi import analyser_ventes_depenses
from tools.prevision_tresorerie import prevoir_tresorerie

SEUIL_MARGE_FAIBLE_PCT = 15.0
SEUIL_BAISSE_MARGE_POINTS = 2.0
SEUIL_HAUSSE_DEPENSES_PCT = 10.0
SEUIL_BAISSE_CA_PCT = 5.0
SEUIL_CONCENTRATION_CLIENT_PCT = 40.0
SEUIL_COUVERTURE_MOIS = 1.5


def _mad(valeur: float | None) -> str:
    return montant_mad(valeur)


def _pct(valeur: float | None) -> str:
    return pourcentage(valeur)


def _variation(valeur: float | None, decimales: int = 1) -> str:
    """Variation signée, sans le symbole pourcentage doublé."""
    if valeur is None:
        return "non disponible"
    return f"{valeur:+.{decimales}f}".replace(".", ",")


def _chiffre(libelle: str, valeur: str, montant_mad: float | None = None) -> dict[str, Any]:
    return {"libelle": libelle, "valeur": valeur, "montant_mad": montant_mad}


def _mois_par_identifiant(mensuel: list[dict[str, Any]], identifiant: str | None) -> dict[str, Any] | None:
    if identifiant is None:
        return None
    return next((m for m in mensuel if m["mois"] == identifiant), None)


def generer_recommandations(
    jeu: JeuDonnees,
    date_reference: date | str | None = None,
) -> dict[str, Any]:
    """Construit entre 3 et 5 recommandations justifiées par les chiffres."""
    kpi = analyser_ventes_depenses(jeu)
    creances = analyser_creances(jeu, date_reference)
    alertes: list[str] = []
    try:
        tresorerie: dict[str, Any] | None = prevoir_tresorerie(jeu, date_reference)
    except ValueError as exc:
        tresorerie = None
        alertes.append(f"Prévision de trésorerie indisponible : {exc}")

    actions: list[dict[str, Any]] = []
    identifiants: set[str] = set()

    def ajouter(
        identifiant: str,
        priorite: int,
        titre: str,
        action: str,
        justification: str,
        chiffres: list[dict[str, Any]],
        source: str,
        montant_concerne_mad: float | None = None,
    ) -> None:
        if identifiant in identifiants:
            return
        identifiants.add(identifiant)
        actions.append(
            {
                "id": identifiant,
                "priorite": priorite,
                "titre": titre,
                "action": action,
                "justification": justification,
                "chiffres": [c for c in chiffres if c["valeur"]],
                "montant_concerne_mad": montant_concerne_mad,
                "source": source,
            }
        )

    # 1. Trésorerie négative : action la plus urgente.
    if tresorerie and tresorerie["alerte_negative"]:
        deficit = float(tresorerie["deficit_max_mad"])
        retard = float(creances["total_en_retard_mad"])
        couverture = (
            "couvrirait le déficit" if retard >= deficit else "ne couvrirait pas tout le déficit"
        )
        ajouter(
            "tresorerie_negative",
            1,
            f"Agir avant {tresorerie['premier_mois_negatif']}",
            "Relancer sans attendre les factures en retard et demander un échelonnement "
            "des charges aux fournisseurs concernés.",
            f"La trésorerie deviendrait négative en {tresorerie['premier_mois_negatif']}, "
            f"avec un point bas de {_mad(deficit)}. Les factures en retard représentent "
            f"{_mad(retard)} : leur encaissement {couverture}.",
            [
                _chiffre("Déficit maximal prévu", _mad(deficit), deficit),
                _chiffre("Créances déjà en retard", _mad(retard), retard),
                _chiffre("Dépenses mensuelles estimées", _mad(tresorerie["depenses_mensuelles_estimees_mad"]), tresorerie["depenses_mensuelles_estimees_mad"]),
            ],
            "prevision_tresorerie",
            deficit,
        )

    # 2. Créances en retard.
    total_retard = float(creances["total_en_retard_mad"])
    if total_retard > 0:
        premier = next(
            (f for f in creances["factures"] if f["jours_retard"] > 0),
            creances["factures"][0] if creances["factures"] else None,
        )
        risque_inclus = (
            creances["total_a_risque_mad"] > 0
            and creances["total_a_risque_mad"] >= total_retard - 0.01
        )
        details = ""
        if premier:
            details = (
                f" Commencez par {premier['client']} : {_mad(premier['solde_mad'])}, "
                f"en retard de {premier['jours_retard']} jours."
            )
        action = "Relancer les factures en retard par téléphone, puis envoyer une relance écrite avec la date d'échéance."
        if risque_inclus:
            action += " Proposer un échéancier écrit pour les créances les plus anciennes."
        ajouter(
            "relance_creances",
            2,
            "Relancer les factures en retard",
            action,
            f"{creances['nombre_factures_en_retard']} facture(s) sont en retard, pour "
            f"{_mad(total_retard)}, soit {_pct(creances['part_creances_retard_pct'])} "
            f"des créances. Le retard le plus long est de {creances['retard_max_jours']} jours."
            + details,
            [
                _chiffre("Créances en retard", _mad(total_retard), total_retard),
                _chiffre("Nombre de factures en retard", str(creances["nombre_factures_en_retard"])),
                _chiffre("Retard maximal", f"{creances['retard_max_jours']} jours"),
            ],
            "creances",
            total_retard,
        )

    # 3. Créances à risque non déjà couvertes par la relance.
    total_risque = float(creances["total_a_risque_mad"])
    if total_risque > 0 and total_risque < total_retard - 0.01:
        clients_risque = [d for d in creances["top_debiteurs"] if d["a_risque_mad"] > 0][:2]
        noms = ", ".join(f"{d['client']} ({_mad(d['a_risque_mad'])})" for d in clients_risque)
        ajouter(
            "creances_a_risque",
            3,
            "Sécuriser les créances les plus anciennes",
            "Proposer un échéancier écrit et suspendre les nouvelles livraisons à crédit "
            "pour les clients concernés.",
            f"{creances['nombre_factures_a_risque']} facture(s) sont à risque pour "
            f"{_mad(total_risque)}. Clients concernés : {noms}.",
            [
                _chiffre("Créances à risque", _mad(total_risque), total_risque),
                _chiffre("Factures à risque", str(creances["nombre_factures_a_risque"])),
            ],
            "creances",
            total_risque,
        )

    # 4. Marge absente : d'abord compléter les données.
    if not kpi["marge_disponible"] and kpi["couts_manquants_nombre"] > 0:
        ajouter(
            "completer_couts",
            2,
            "Compléter le coût d'achat",
            "Ajouter le coût d'achat dans le fichier des ventes pour chaque ligne concernée.",
            f"Le coût d'achat manque sur {kpi['couts_manquants_nombre']} ligne(s). "
            "Sans ce chiffre, la marge et le résultat ne peuvent pas être calculés.",
            [
                _chiffre("Lignes sans coût d'achat", str(kpi["couts_manquants_nombre"])),
                _chiffre("Chiffre d'affaires concerné", _mad(kpi["chiffre_affaires_mad"]), kpi["chiffre_affaires_mad"]),
            ],
            "kpi",
        )

    # 5. Marge faible ou en baisse.
    marge = kpi["marge_brute_mad"]
    taux_marge = kpi["taux_marge_pct"]
    variation_marge = kpi["evolution"]["variation_marge_points"]
    marge_fragile = bool(
        marge is not None
        and taux_marge is not None
        and (
            taux_marge < SEUIL_MARGE_FAIBLE_PCT
            or (marge < 0)
            or (variation_marge is not None and variation_marge <= -SEUIL_BAISSE_MARGE_POINTS)
        )
    )
    if marge_fragile:
        categories = [
            c for c in kpi["ventes_par_categorie"]
            if c["marge_disponible"] and c["taux_marge_pct"] is not None and (c["part_ca_pct"] or 0) >= 10
        ]
        faible = min(categories, key=lambda c: c["taux_marge_pct"]) if categories else None
        justification = (
            f"La marge brute est de {_pct(taux_marge)} ({_mad(marge)} sur "
            f"{_mad(kpi['chiffre_affaires_mad'])} de chiffre d'affaires)."
        )
        if variation_marge is not None:
            justification += (
                f" Elle a varié de {_variation(variation_marge)} point(s) par rapport au mois précédent."
            )
        chiffres = [
            _chiffre("Taux de marge brute", _pct(taux_marge)),
            _chiffre("Marge brute", _mad(marge), marge),
        ]
        if faible:
            justification += (
                f" La catégorie {faible['categorie']} a la marge la plus faible : "
                f"{_pct(faible['taux_marge_pct'])}."
            )
            chiffres.append(
                _chiffre(
                    f"Marge {faible['categorie']}",
                    _pct(faible["taux_marge_pct"]),
                    faible["marge_brute_mad"],
                )
            )
        ajouter(
            "marge_fragile",
            3,
            "Vérifier les prix et les coûts d'achat",
            "Comparer le prix de vente et le coût d'achat des produits les plus vendus, "
            "puis ajuster le prix ou changer de fournisseur.",
            justification,
            chiffres,
            "kpi",
        )

    # 6. Dépenses en hausse.
    evolution = kpi["evolution"]
    if (
        evolution["variation_depenses_pct"] is not None
        and evolution["variation_depenses_pct"] > SEUIL_HAUSSE_DEPENSES_PCT
    ):
        recent = _mois_par_identifiant(kpi["mensuel"], evolution["mois_recent"])
        precedent = _mois_par_identifiant(kpi["mensuel"], evolution["mois_precedent"])
        if recent and precedent and recent["depenses_mad"] >= 500:
            principale = kpi["depenses_par_categorie"][0] if kpi["depenses_par_categorie"] else None
            justification = (
                f"Les dépenses de {recent['libelle']} atteignent {_mad(recent['depenses_mad'])}, "
                f"en hausse de {_pct(evolution['variation_depenses_pct'])} par rapport à "
                f"{precedent['libelle']} ({_mad(precedent['depenses_mad'])})."
            )
            chiffres = [
                _chiffre("Dépenses du dernier mois complet", _mad(recent["depenses_mad"]), recent["depenses_mad"]),
                _chiffre("Augmentation", _pct(evolution["variation_depenses_pct"])),
            ]
            if principale:
                justification += (
                    f" Le poste {principale['categorie']} pèse {_mad(principale['montant_mad'])}."
                )
                chiffres.append(
                    _chiffre(
                        f"Poste {principale['categorie']}",
                        _mad(principale["montant_mad"]),
                        principale["montant_mad"],
                    )
                )
            ajouter(
                "depenses_en_hausse",
                3,
                "Revoir le poste de dépense qui augmente",
                "Demander au moins deux devis pour le poste principal et supprimer "
                "les dépenses qui ne servent pas directement aux ventes.",
                justification,
                chiffres,
                "kpi",
            )

    # 7. Chiffre d'affaires en baisse.
    if evolution["variation_ca_pct"] is not None and evolution["variation_ca_pct"] < -SEUIL_BAISSE_CA_PCT:
        recent = _mois_par_identifiant(kpi["mensuel"], evolution["mois_recent"])
        precedent = _mois_par_identifiant(kpi["mensuel"], evolution["mois_precedent"])
        if recent and precedent:
            baisse = recent["ca_mad"] - precedent["ca_mad"]
            # « Clients de passage » n'est pas un client unique : l'utiliser
            # pour parler de dépendance serait trompeur.
            top_client = next(
                (c for c in kpi["top_clients"] if c["client"] != "Clients de passage"),
                None,
            )
            justification = (
                f"Le chiffre d'affaires de {recent['libelle']} est de {_mad(recent['ca_mad'])}, "
                f"en baisse de {_mad(abs(baisse))} par rapport à {precedent['libelle']}."
            )
            chiffres = [
                _chiffre("Baisse du chiffre d'affaires", _mad(abs(baisse)), abs(baisse)),
                _chiffre("Variation", _pct(evolution["variation_ca_pct"])),
            ]
            if top_client:
                justification += (
                    f" Le premier client représente {_pct(top_client['part_ca_pct'])} du chiffre d'affaires."
                )
                chiffres.append(
                    _chiffre(
                        f"Client {top_client['client']}",
                        _mad(top_client["ca_mad"]),
                        top_client["ca_mad"],
                    )
                )
            ajouter(
                "ca_en_baisse",
                4,
                "Relancer les ventes",
                "Appeler les meilleurs clients et proposer une offre limitée dans le temps "
                "sur les produits qui se vendent le moins.",
                justification,
                chiffres,
                "kpi",
            )

    # 8. Réserve de trésorerie insuffisante.
    if tresorerie and not tresorerie["alerte_negative"] and tresorerie["couverture_tresorerie_mois"] is not None:
        couverture = float(tresorerie["couverture_tresorerie_mois"])
        if 0 < couverture < SEUIL_COUVERTURE_MOIS:
            mensuel = float(tresorerie["depenses_mensuelles_estimees_mad"])
            manque = max(0.0, mensuel - float(tresorerie["solde_initial_mad"]))
            ajouter(
                "reserve_tresorerie",
                4,
                "Constituer une réserve de trésorerie",
                f"Mettre de côté {_mad(manque)} pour atteindre un mois de dépenses d'avance.",
                f"La trésorerie de départ couvre {mois_francais(couverture)} de dépenses. "
                f"Les dépenses mensuelles estimées sont de {_mad(mensuel)}.",
                [
                    _chiffre("Couverture actuelle", mois_francais(couverture)),
                    _chiffre("Dépenses mensuelles", _mad(mensuel), mensuel),
                    _chiffre("Réserve à constituer", _mad(manque), manque),
                ],
                "prevision_tresorerie",
                manque,
            )

    # 9. Dépendance à un client.
    client_concentre = next(
        (
            c for c in kpi["top_clients"]
            if c["client"] != "Clients de passage"
            and (c["part_ca_pct"] or 0) >= SEUIL_CONCENTRATION_CLIENT_PCT
        ),
        None,
    )
    if client_concentre:
        ajouter(
            "concentration_client",
            5,
            "Réduire la dépendance à un client",
            "Démarcher au moins trois nouveaux clients professionnels ce mois-ci.",
            f"{client_concentre['client']} représente {_pct(client_concentre['part_ca_pct'])} "
            f"du chiffre d'affaires, soit {_mad(client_concentre['ca_mad'])}.",
            [
                _chiffre("Part du premier client", _pct(client_concentre["part_ca_pct"])),
                _chiffre("Chiffre d'affaires du client", _mad(client_concentre["ca_mad"]), client_concentre["ca_mad"]),
            ],
            "kpi",
        )

    # 10. Poids d'un poste de dépense.
    if kpi["depenses_par_categorie"]:
        principale = kpi["depenses_par_categorie"][0]
        # Les achats de marchandises sont un coût variable lié aux ventes :
        # demander un devis concurrent n'a pas le même sens que pour un loyer.
        if (principale["part_pct"] or 0) >= 30 and principale["categorie"] != "Achats de marchandises":
            ajouter(
                "poste_depense_principal",
                5,
                "Négocier le poste de dépense principal",
                f"Demander un devis concurrent pour {principale['categorie']} avant le prochain achat.",
                f"Le poste {principale['categorie']} représente {_mad(principale['montant_mad'])}, "
                f"soit {_pct(principale['part_pct'])} des dépenses.",
                [
                    _chiffre(f"Dépenses {principale['categorie']}", _mad(principale["montant_mad"]), principale["montant_mad"]),
                    _chiffre("Part des dépenses", _pct(principale["part_pct"])),
                ],
                "kpi",
                principale["montant_mad"],
            )

    # 11. Part des ventes à crédit.
    if kpi["chiffre_affaires_mad"] > 0:
        part_credit = 100.0 * kpi["factures_emises_mad"] / kpi["chiffre_affaires_mad"]
        if part_credit >= 50:
            ajouter(
                "ventes_a_credit",
                5,
                "Encadrer les ventes à crédit",
                "Demander un acompte à la commande et fixer une date d'échéance écrite "
                "pour chaque nouvelle facture.",
                f"{_pct(part_credit)} du chiffre d'affaires est facturé à crédit "
                f"({_mad(kpi['factures_emises_mad'])}), contre "
                f"{_mad(kpi['ventes_comptant_mad'])} encaissés au comptant.",
                [
                    _chiffre("Ventes à crédit", _mad(kpi["factures_emises_mad"]), kpi["factures_emises_mad"]),
                    _chiffre("Part du chiffre d'affaires", _pct(part_credit)),
                ],
                "kpi",
                kpi["factures_emises_mad"],
            )

    # --- Actions de repli, toujours adossées à un chiffre --------------------
    def completer_actions() -> None:
        if tresorerie:
            solde = float(tresorerie["solde_initial_mad"])
            mensuel = float(tresorerie["depenses_mensuelles_estimees_mad"])
            ajouter(
                "suivi_hebdomadaire",
                6,
                "Suivre la trésorerie chaque semaine",
                "Noter le solde de trésorerie chaque vendredi et le comparer au solde de départ.",
                f"Le solde de départ est de {_mad(solde)}. Les dépenses mensuelles "
                f"estimées sont de {_mad(mensuel)}.",
                [
                    _chiffre("Solde de départ", _mad(solde), solde),
                    _chiffre("Dépenses mensuelles", _mad(mensuel), mensuel),
                ],
                "prevision_tresorerie",
            )
        if kpi["chiffre_affaires_mad"] > 0:
            ajouter(
                "suivi_mensuel",
                6,
                "Refaire ce point chaque mois",
                "Comparer chaque mois le chiffre d'affaires, les dépenses et les impayés.",
                f"Sur la période analysée, le chiffre d'affaires est de "
                f"{_mad(kpi['chiffre_affaires_mad'])} et les dépenses de "
                f"{_mad(kpi['depenses_mad'])}.",
                [
                    _chiffre("Chiffre d'affaires", _mad(kpi["chiffre_affaires_mad"]), kpi["chiffre_affaires_mad"]),
                    _chiffre("Dépenses", _mad(kpi["depenses_mad"]), kpi["depenses_mad"]),
                ],
                "kpi",
            )
        if creances["total_creances_mad"] > 0:
            ajouter(
                "facturation_rapide",
                6,
                "Facturer dès la livraison",
                "Envoyer la facture le jour de la livraison et vérifier chaque semaine les impayés.",
                f"Il reste {_mad(creances['total_creances_mad'])} à encaisser sur "
                f"{creances['nombre_factures_impayees']} facture(s).",
                [
                    _chiffre("Créances totales", _mad(creances["total_creances_mad"]), creances["total_creances_mad"]),
                    _chiffre("Factures impayées", str(creances["nombre_factures_impayees"])),
                ],
                "creances",
            )
        if kpi["marge_disponible"]:
            ajouter(
                "prix_fournisseurs",
                6,
                "Comparer les prix fournisseurs",
                "Demander un prix ferme à un second fournisseur pour les deux produits "
                "les plus vendus.",
                f"La marge brute est de {_mad(kpi['marge_brute_mad'])}, soit "
                f"{_pct(kpi['taux_marge_pct'])} du chiffre d'affaires.",
                [
                    _chiffre("Marge brute", _mad(kpi["marge_brute_mad"]), kpi["marge_brute_mad"]),
                    _chiffre("Taux de marge", _pct(kpi["taux_marge_pct"])),
                ],
                "kpi",
            )
        if kpi["depenses_mad"] > 0:
            principale = next(
                (c for c in kpi["depenses_par_categorie"] if c["categorie"] != "Achats de marchandises"),
                kpi["depenses_par_categorie"][0] if kpi["depenses_par_categorie"] else None,
            )
            chiffres = [
                _chiffre("Dépenses totales", _mad(kpi["depenses_mad"]), kpi["depenses_mad"]),
            ]
            justification = f"Les dépenses enregistrées totalisent {_mad(kpi['depenses_mad'])}."
            if kpi["achats_marchandises_mad"] > 0:
                justification += (
                    f" Les achats de marchandises en représentent "
                    f"{_mad(kpi['achats_marchandises_mad'])} ; le reste correspond aux charges fixes."
                )
                chiffres.append(
                    _chiffre(
                        "Achats de marchandises",
                        _mad(kpi["achats_marchandises_mad"]),
                        kpi["achats_marchandises_mad"],
                    )
                )
            if principale:
                justification += (
                    f" Le premier poste de charges est {principale['categorie']} avec "
                    f"{_mad(principale['montant_mad'])}."
                )
                chiffres.append(
                    _chiffre(
                        f"Poste {principale['categorie']}",
                        _mad(principale["montant_mad"]),
                        principale["montant_mad"],
                    )
                )
            ajouter(
                "classer_depenses",
                6,
                "Classer les dépenses par poste",
                "Séparer les dépenses fixes des achats variables pour repérer "
                "rapidement ce qui peut être réduit.",
                justification,
                chiffres,
                "kpi",
            )
        if kpi["chiffre_affaires_mad"] == 0 and kpi["depenses_mad"] > 0:
            ajouter(
                "suivi_depenses",
                6,
                "Comparer les dépenses chaque mois",
                "Noter le total des dépenses à la fin de chaque mois et le comparer au mois précédent.",
                f"Le total des dépenses enregistrées est de {_mad(kpi['depenses_mad'])}. "
                "Aucune vente n'est enregistrée sur la période : le lien avec le chiffre "
                "d'affaires ne peut pas être calculé.",
                [
                    _chiffre("Dépenses totales", _mad(kpi["depenses_mad"]), kpi["depenses_mad"]),
                ],
                "kpi",
            )
        if creances["total_creances_mad"] > 0:
            prochaine = min(
                creances["factures"],
                key=lambda f: f["date_echeance"],
                default=None,
            )
            chiffres = [
                _chiffre("Créances totales", _mad(creances["total_creances_mad"]), creances["total_creances_mad"]),
            ]
            justification = (
                f"{_mad(creances['total_creances_mad'])} restent à encaisser sur "
                f"{creances['nombre_factures_impayees']} facture(s)."
            )
            if prochaine:
                justification += f" La prochaine échéance est le {prochaine['date_echeance']}."
                chiffres.append(_chiffre("Prochaine échéance", prochaine["date_echeance"]))
            ajouter(
                "planifier_encaissements",
                6,
                "Planifier les encaissements",
                "Inscrire chaque échéance dans un calendrier et vérifier le paiement deux jours avant.",
                justification,
                chiffres,
                "creances",
            )

    completer_actions()

    # On garde les 5 actions les plus prioritaires, avec un minimum de 3.
    actions.sort(key=lambda item: (item["priorite"], item["id"]))
    selection = actions[:5]
    if len(selection) < 3:
        raise RuntimeError("Données trop pauvres pour produire trois recommandations chiffrées.")

    return {
        "entreprise": jeu.entreprise,
        "devise": jeu.devise,
        "date_reference": (creances["date_reference"]),
        "nombre_recommandations": len(selection),
        "recommandations": selection,
        "synthese": {
            "chiffre_affaires_mad": kpi["chiffre_affaires_mad"],
            "marge_brute_mad": kpi["marge_brute_mad"],
            "depenses_mad": kpi["depenses_mad"],
            "creances_total_mad": creances["total_creances_mad"],
            "creances_retard_mad": creances["total_en_retard_mad"],
            "tresorerie_negative_prevue": bool(tresorerie and tresorerie["alerte_negative"]),
        },
        "alertes_donnees": list(dict.fromkeys(
            alertes + kpi["alertes_donnees"] + creances["alertes_donnees"]
            + (tresorerie["alertes_donnees"] if tresorerie else [])
        )),
        "methodologie": (
            "Actions générées par des règles déterministes à partir des KPI, des "
            "créances et de la prévision de trésorerie. Chaque action cite les "
            "chiffres qui la déclenchent. Les seuils servent uniquement à classer "
            "les actions : ils ne sont pas des statistiques du secteur."
        ),
    }
