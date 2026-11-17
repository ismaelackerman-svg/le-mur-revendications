"""
CONTRÔLE — la base du site est-elle identique à la clé USB de référence ?

    py -3.12 outils/verifier.py --reference F:\\empreintes.txt --etudiants 5000

Détecte :
  - des comptes AJOUTÉS dans la base (faux comptes → bourrage d'urnes),
  - des comptes SUPPRIMÉS (étudiants privés de vote),
  - plus de comptes activés que d'étudiants (liens partagés ou revendus).

À lancer par plusieurs personnes, avant, pendant et après le vote.
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402


def verifier(chemin_reference, chemin_db=None, etudiants: int | None = None) -> dict:
    reference = set(Path(chemin_reference).read_text(encoding="utf-8").split())
    with db.connexion(chemin_db) as conn:
        en_base = {l["empreinte"] for l in conn.execute("SELECT empreinte FROM comptes")}
        actifs = conn.execute("SELECT COUNT(*) AS n FROM comptes WHERE active = 1").fetchone()["n"]
        votants = conn.execute("SELECT COUNT(DISTINCT compte) AS n FROM votes").fetchone()["n"]
        inconnus = conn.execute(
            "SELECT COUNT(DISTINCT compte) AS n FROM votes WHERE compte NOT IN (SELECT empreinte FROM comptes)"
        ).fetchone()["n"]
    resultat = {
        "ajoutes": sorted(en_base - reference),
        "manquants": sorted(reference - en_base),
        "total_reference": len(reference),
        "total_base": len(en_base),
        "actifs": actifs,
        "votants": votants,
        "votes_de_comptes_inconnus": inconnus,
        "depasse_etudiants": bool(etudiants is not None and actifs > etudiants),
        "empreinte_reference": hashlib.sha256(Path(chemin_reference).read_bytes()).hexdigest(),
    }
    resultat["ok"] = not (
        resultat["ajoutes"] or resultat["manquants"]
        or resultat["depasse_etudiants"] or inconnus
    )
    return resultat


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reference", required=True, help="empreintes.txt de la clé USB")
    p.add_argument("--db", default=None)
    p.add_argument("--etudiants", type=int, default=None, help="nombre officiel d'étudiants")
    a = p.parse_args()

    r = verifier(a.reference, a.db, a.etudiants)
    print(f"Comptes dans la référence : {r['total_reference']}")
    print(f"Comptes dans la base      : {r['total_base']}")
    print(f"Comptes activés           : {r['actifs']}")
    print(f"Comptes ayant voté        : {r['votants']}")
    print(f"Empreinte de la référence : {r['empreinte_reference']}")
    print("  (doit être identique à celle publiée avant le vote)")
    if r["ajoutes"]:
        print(f"\n⚠️  {len(r['ajoutes'])} compte(s) AJOUTÉ(S) hors référence → FAUX COMPTES POSSIBLES")
    if r["manquants"]:
        print(f"\n⚠️  {len(r['manquants'])} compte(s) de la référence ABSENT(S) de la base")
    if r["votes_de_comptes_inconnus"]:
        print(f"\n⚠️  des votes viennent de {r['votes_de_comptes_inconnus']} compte(s) qui n'existent pas")
    if r["depasse_etudiants"]:
        print(f"\n⚠️  {r['actifs']} comptes activés pour {a.etudiants} étudiants : liens partagés ?")
    print("\nRÉSULTAT :", "✅ tout est conforme" if r["ok"] else "❌ ANOMALIE")
    sys.exit(0 if r["ok"] else 1)


if __name__ == "__main__":
    main()
