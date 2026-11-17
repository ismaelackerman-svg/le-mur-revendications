"""
ÉTAPE 3 — Envoyer un lien unique à chaque étudiant.

⚠️ CE PROGRAMME EST LANCÉ PAR LA PERSONNE NEUTRE, devant témoin — pas par
l'équipe qui a fait le site. C'est lui seul qui voit, un instant, quelle
adresse reçoit quel code. Il doit donc :
  - ne rien écrire d'autre que « adresse : OK / ÉCHEC » dans ses journaux,
  - supprimer le fichier de codes à la fin (le programme le fait tout seul).

Essai à blanc (n'envoie RIEN, n'affiche aucun code, ne supprime rien) :
    py -3.12 outils/envoyer_mails.py --emails etudiants.txt --codes sortie/codes_principaux.txt ^
        --url https://notre-site.fr --domaine univ-exemple.fr

Envoi réel (ajouter --envoyer et les réglages du serveur de mail) :
    ... --envoyer --smtp-hote smtp.univ-exemple.fr --smtp-port 587 ^
        --smtp-utilisateur compte@univ-exemple.fr --expediteur "Collectif <compte@univ-exemple.fr>"
Le mot de passe est demandé au clavier (ou lu dans la variable SMTP_MOT_DE_PASSE).
"""
import argparse
import getpass
import os
import random
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

SUJET = "Ton lien personnel pour les revendications étudiantes"
CORPS = """Bonjour,

Voici ton lien PERSONNEL pour proposer et voter les revendications étudiantes :

{lien}

- Il est unique : ne le transmets à personne.
- Garde ce mail : si tu changes de téléphone ou d'ordinateur, reclique sur ce lien.
- Ton compte est anonyme : le site ne sait pas qui tu es.

À bientôt.
"""


def lire_lignes(chemin) -> list[str]:
    return [l.strip() for l in Path(chemin).read_text(encoding="utf-8").splitlines() if l.strip()]


def lire_emails(chemin, domaine: str | None = None):
    """Adresses uniques, en minuscules. Renvoie (valides, refusées)."""
    vues, valides, refusees = set(), [], []
    for e in lire_lignes(chemin):
        e = e.lower()
        if e in vues:
            continue
        vues.add(e)
        ok = "@" in e and (not domaine or e.endswith("@" + domaine.lower()))
        (valides if ok else refusees).append(e)
    return valides, refusees


def supprimer_fichier(chemin) -> None:
    """Écrase puis supprime (au mieux : sur un SSD, l'effacement n'est jamais garanti)."""
    p = Path(chemin)
    taille = p.stat().st_size
    with open(p, "r+b") as f:
        f.write(os.urandom(taille))
        f.flush()
        os.fsync(f.fileno())
    p.unlink()


def distribuer(emails, codes, expedier, url: str, essais: int = 3):
    """
    Associe un code à chaque adresse (ordre MÉLANGÉ) et appelle expedier(adresse, lien).
    expedier lève une exception en cas d'échec : on retente avec un AUTRE code
    (le code raté n'a jamais été livré, son empreinte reste simplement inutilisée).
    Renvoie (ok, echecs, codes_restants). Ne journalise JAMAIS un code.
    """
    emails = list(emails)
    random.SystemRandom().shuffle(emails)
    pool = list(codes)
    random.SystemRandom().shuffle(pool)
    if len(pool) < len(emails):
        raise ValueError(f"Pas assez de codes : {len(pool)} codes pour {len(emails)} adresses.")
    ok, echecs = [], []
    for adresse in emails:
        livre = False
        for _ in range(essais):
            if not pool:
                break
            code = pool.pop()
            try:
                expedier(adresse, f"{url.rstrip('/')}/entrer?code={code}")
                livre = True
                break
            except Exception:
                continue
        (ok if livre else echecs).append(adresse)
        print(f"{adresse} : {'OK' if livre else 'ÉCHEC'}")
    return ok, echecs, pool


def fabriquer_expediteur(a):
    mdp = os.environ.get("SMTP_MOT_DE_PASSE") or getpass.getpass("Mot de passe du serveur de mail : ")
    contexte = ssl.create_default_context()
    serveur = smtplib.SMTP(a.smtp_hote, a.smtp_port, timeout=30)
    serveur.starttls(context=contexte)
    serveur.login(a.smtp_utilisateur, mdp)

    def expedier(adresse, lien):
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = SUJET, a.expediteur, adresse
        m.set_content(CORPS.format(lien=lien))
        serveur.send_message(m)

    return expedier, serveur


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--emails", required=True, help="fichier : une adresse par ligne")
    p.add_argument("--codes", required=True, help="fichier : un code par ligne")
    p.add_argument("--url", required=True, help="adresse du site, ex : https://notre-site.fr")
    p.add_argument("--domaine", default=None, help="n'accepter que ce domaine, ex : univ-exemple.fr")
    p.add_argument("--envoyer", action="store_true", help="envoi réel (sinon : essai à blanc)")
    p.add_argument("--smtp-hote")
    p.add_argument("--smtp-port", type=int, default=587)
    p.add_argument("--smtp-utilisateur")
    p.add_argument("--expediteur")
    a = p.parse_args()

    emails, refusees = lire_emails(a.emails, a.domaine)
    codes = lire_lignes(a.codes)
    print(f"{len(emails)} adresses valides, {len(refusees)} refusées, {len(codes)} codes disponibles.")
    for r in refusees:
        print(f"  refusée : {r}")
    if len(codes) < len(emails):
        sys.exit("Pas assez de codes pour toutes les adresses. Arrêt.")

    if not a.envoyer:
        print("\nESSAI À BLANC : rien n'est envoyé, aucun code n'est affiché, rien n'est supprimé.")
        print("Pour envoyer pour de vrai, relance avec --envoyer.")
        return

    if not (a.smtp_hote and a.smtp_utilisateur and a.expediteur):
        sys.exit("Il manque --smtp-hote, --smtp-utilisateur ou --expediteur.")
    expedier, serveur = fabriquer_expediteur(a)
    try:
        ok, echecs, _ = distribuer(emails, codes, expedier, a.url)
    finally:
        serveur.quit()

    # On n'arrive ici que si tout le monde a été traité (sinon le fichier reste).
    supprimer_fichier(a.codes)
    print(f"\nTerminé : {len(ok)} envoyés, {len(echecs)} échecs.")
    print(f"Le fichier {a.codes} a été SUPPRIMÉ.")
    if echecs:
        Path("echecs.txt").write_text("\n".join(echecs) + "\n", encoding="utf-8")
        print("Adresses en échec écrites dans echecs.txt (à relancer avec des codes de réserve).")
    print("Maintenant : supprimer aussi ce que les témoins ont vu à l'écran / les copies restantes.")


if __name__ == "__main__":
    main()
