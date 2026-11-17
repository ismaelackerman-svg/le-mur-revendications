"""
Met le site en ligne ET fabrique des liens neufs, d'un seul coup.

    py -3.12 outils/demarrer_en_ligne.py --nombre 8

Ce que ça fait, dans l'ordre :
  1. lance le tunnel Cloudflare et attend que l'adresse publique soit joignable ;
  2. tire NOMBRE codes au hasard et n'enregistre dans la base que leur empreinte ;
  3. affiche les liens complets dans cette fenêtre ET les copie dans le presse-papiers.

Les codes en clair ne sont ÉCRITS NULLE PART : pas de fichier, rien à supprimer.
Ils n'existent que dans cette fenêtre et dans le presse-papiers. Ferme la fenêtre
une fois les liens collés dans le groupe.

⚠️ L'adresse change à chaque lancement : les liens d'une session précédente ne
marchent plus (leurs codes restent valables, mais on ne peut pas les réécrire).
Chaque lancement produit donc des liens neufs.
"""
import argparse
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
import db  # noqa: E402

ADRESSE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def attendre_site(port: int, delai: int = 60) -> bool:
    fin = time.time() + delai
    while time.time() < fin:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def attendre_adresse_publique(url: str, delai: int = 90) -> bool:
    fin = time.time() + delai
    while time.time() < fin:
        try:
            urllib.request.urlopen(url + "/api/etat", timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


def fabriquer(nombre: int, url: str) -> list[str]:
    """Tire des codes, enregistre leurs empreintes, renvoie les liens. Aucun fichier."""
    codes = [db.nouveau_code() for _ in range(nombre)]
    db.importer_empreintes([db.empreinte(c) for c in codes])
    return [f"{url.rstrip('/')}/entrer?code={c}" for c in codes]


def surveiller_site(port: int) -> None:
    """Fait tourner le site et le relance tout seul s'il s'arrête (plantage, fenêtre fermée)."""
    while True:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log"],
            cwd=str(RACINE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait()
        time.sleep(2)


def copier(texte: str) -> None:
    try:
        subprocess.run(["clip"], input=texte.encode("utf-16le"), check=True)
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nombre", type=int, default=8)
    p.add_argument("--port", type=int, default=8120)
    a = p.parse_args()

    if not attendre_site(a.port, 2):      # pas déjà lancé : on le lance et on le surveille
        threading.Thread(target=surveiller_site, args=(a.port,), daemon=True).start()
    print(f"Attente du site sur le port {a.port}...")
    if not attendre_site(a.port):
        sys.exit("Le site ne démarre pas.")

    tunnel = subprocess.Popen(
        ["cloudflared", "--config", str(RACINE / "tunnel-sans-config.yml"), "tunnel",
         "--no-autoupdate", "--url", f"http://127.0.0.1:{a.port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    try:
        url = None
        debut = time.time()
        for ligne in tunnel.stdout:
            m = ADRESSE.search(ligne)
            if m:
                url = m.group(0)
                break
            if time.time() - debut > 60:
                break
        if not url:
            sys.exit("Le tunnel n'a pas donné d'adresse. Relance.")
        print(f"Adresse publique : {url}\nVérification qu'elle répond...")
        if not attendre_adresse_publique(url):
            sys.exit("L'adresse ne répond pas encore. Relance dans une minute.")

        liens = fabriquer(a.nombre, url)
        texte = "\n".join(liens)
        copier(texte)
        print("\n" + "=" * 70)
        print(f"SITE EN LIGNE : {url}")
        print(f"{len(liens)} LIENS (déjà copiés dans le presse-papiers, un par ligne) :\n")
        for i, l in enumerate(liens, 1):
            print(f"{i}. {l}")
        print("\nChaque lien ne sert qu'une fois. Rien n'est écrit sur le disque.")
        print("Garde cette fenêtre OUVERTE (elle fait tourner le tunnel).")
        print("=" * 70)
        for _ in tunnel.stdout:      # garde le tunnel vivant tant que la fenêtre est ouverte
            pass
    except KeyboardInterrupt:
        pass
    finally:
        tunnel.terminate()


if __name__ == "__main__":
    main()
