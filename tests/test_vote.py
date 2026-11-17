"""
Tests du système de vote. Aucune dépendance : py -3.12 tests/test_vote.py
Chaque test travaille sur une base temporaire ISOLÉE.
"""
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "outils"))

import db  # noqa: E402
import generer_codes  # noqa: E402
import envoyer_mails  # noqa: E402
import verifier  # noqa: E402


def base_temp():
    """Base vide + variable d'environnement pointant dessus."""
    dossier = tempfile.mkdtemp()
    chemin = os.path.join(dossier, "vote.db")
    os.environ["VOTE_DB"] = chemin
    db.init_base(chemin)
    return dossier, chemin


def monde(n=5, reserve=0):
    """Une base avec n comptes. Renvoie (dossier, chemin, codes, empreintes)."""
    dossier, chemin = base_temp()
    principaux, de_reserve, emp = generer_codes.generer(n, reserve)
    db.importer_empreintes(emp, chemin)
    return dossier, chemin, principaux, emp


# ------------------------------------------------------------------ codes
def test_empreinte_stable_et_a_sens_unique():
    c = db.nouveau_code()
    assert db.empreinte(c) == db.empreinte(c)
    assert len(db.empreinte(c)) == 64
    assert c not in db.empreinte(c)


def test_codes_longs_et_tous_differents():
    principaux, reserve, emp = generer_codes.generer(2000, 200)
    tous = principaux + reserve
    assert len(set(tous)) == 2200
    assert all(len(c) >= 40 for c in tous)          # 256 bits, pas devinables
    assert len(emp) == 2200 and emp == sorted(emp)


def test_les_empreintes_correspondent_aux_codes():
    principaux, reserve, emp = generer_codes.generer(50, 5)
    assert set(emp) == {db.empreinte(c) for c in principaux + reserve}


# --------------------------------------------------------------- connexion
def test_code_valide_et_code_inconnu():
    _, chemin, codes, _ = monde(3)
    assert db.compte_depuis_code(codes[0], chemin) == db.empreinte(codes[0])
    assert db.compte_depuis_code("code-invente", chemin) is None
    assert db.compte_depuis_code("", chemin) is None
    assert db.compte_depuis_code(None, chemin) is None
    assert db.compte_depuis_code("x" * 500, chemin) is None


def test_la_base_ne_contient_aucun_code_en_clair():
    dossier, chemin, codes, _ = monde(20)
    h = db.empreinte(codes[0])
    db.ajouter_revendication(h, "Une revendication de test assez longue", chemin)
    db.voter(h, 1, 1, chemin)
    brut = Path(chemin).read_bytes()
    for c in codes:
        assert c.encode() not in brut, "un code en clair a fuité dans la base !"


def test_table_comptes_sans_ordre_ni_date():
    _, chemin = base_temp()
    with db.connexion(chemin) as conn:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='comptes'").fetchone()[0]
    assert "WITHOUT ROWID" in sql.upper()
    assert "date" not in sql.lower() and "jour" not in sql.lower()


def test_importer_deux_fois_ne_double_pas():
    _, chemin = base_temp()
    _, _, emp = generer_codes.generer(10, 0)
    assert db.importer_empreintes(emp, chemin) == 10
    assert db.importer_empreintes(emp, chemin) == 0


def test_empreinte_mal_formee_ignoree():
    _, chemin = base_temp()
    assert db.importer_empreintes(["abc", "", "zz" * 10], chemin) == 0


# ----------------------------------------------------------------- votes
def un_compte(n=3):
    _, chemin, codes, _ = monde(n)
    return chemin, [db.empreinte(c) for c in codes]


def test_double_vote_remplace_et_ne_s_ajoute_pas():
    chemin, (a, b, _) = un_compte()
    rid = db.ajouter_revendication(a, "Ouvrir la bibliothèque le dimanche", chemin)
    db.voter(a, rid, 1, chemin)
    db.voter(a, rid, 1, chemin)
    db.voter(a, rid, 1, chemin)
    r = db.classement(a, chemin)[0]
    assert (r["pour"], r["contre"], r["score"]) == (1, 0, 1)
    db.voter(a, rid, -1, chemin)                       # il change d'avis
    r = db.classement(a, chemin)[0]
    assert (r["pour"], r["contre"]) == (0, 1)
    db.voter(a, rid, 0, chemin)                        # il retire son vote
    assert db.classement(a, chemin)[0]["score"] == 0


def test_la_cle_primaire_interdit_physiquement_le_double_vote():
    chemin, (a, _, _) = un_compte()
    rid = db.ajouter_revendication(a, "Ouvrir la bibliothèque le dimanche", chemin)
    conn = sqlite3.connect(chemin)
    conn.execute("INSERT INTO votes VALUES (?, ?, 1)", (a, rid))
    try:
        conn.execute("INSERT INTO votes VALUES (?, ?, 1)", (a, rid))
        assert False, "la base a accepté deux votes du même compte"
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def test_valeur_de_vote_invalide_refusee():
    chemin, (a, _, _) = un_compte()
    rid = db.ajouter_revendication(a, "Ouvrir la bibliothèque le dimanche", chemin)
    for mauvais in (2, -5, 100):
        try:
            db.voter(a, rid, mauvais, chemin)
            assert False
        except db.ErreurVote:
            pass


def test_voter_sur_revendication_inexistante():
    chemin, (a, _, _) = un_compte()
    try:
        db.voter(a, 999, 1, chemin)
        assert False
    except db.ErreurVote:
        pass


def test_limite_de_propositions_par_compte():
    chemin, (a, b, _) = un_compte()
    for i in range(db.MAX_PROPOSITIONS):
        db.ajouter_revendication(a, f"Revendication numéro {i} bien assez longue", chemin)
    try:
        db.ajouter_revendication(a, "Une de trop, assez longue aussi", chemin)
        assert False
    except db.ErreurVote:
        pass
    assert db.propositions_restantes(a, chemin) == 0
    db.ajouter_revendication(b, "Un autre compte peut proposer", chemin)  # b n'est pas bloqué


def test_longueur_du_texte_controlee():
    chemin, (a, _, _) = un_compte()
    for mauvais in ("", "court", "x" * (db.TEXTE_MAX + 1)):
        try:
            db.ajouter_revendication(a, mauvais, chemin)
            assert False
        except db.ErreurVote:
            pass


def test_classement_trie_par_score_et_cache_l_auteur():
    chemin, (a, b, c) = un_compte()
    r1 = db.ajouter_revendication(a, "Revendication un assez longue", chemin)
    r2 = db.ajouter_revendication(a, "Revendication deux assez longue", chemin)
    r3 = db.ajouter_revendication(b, "Revendication trois assez longue", chemin)
    db.voter(a, r2, 1, chemin); db.voter(b, r2, 1, chemin); db.voter(c, r2, 1, chemin)
    db.voter(a, r3, 1, chemin)
    db.voter(b, r1, -1, chemin)
    ordre = [x["id"] for x in db.classement(a, chemin)]
    assert ordre == [r2, r3, r1], ordre
    for x in db.classement(a, chemin):
        assert "auteur" not in x
    assert [x["a_moi"] for x in db.classement(b, chemin) if x["id"] == r3] == [True]


def test_masquer_retire_du_classement_sans_supprimer():
    chemin, (a, _, _) = un_compte()
    rid = db.ajouter_revendication(a, "Revendication à masquer ici", chemin)
    assert db.masquer(rid, True, chemin)
    assert db.classement(a, chemin) == []
    with db.connexion(chemin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM revendications").fetchone()[0] == 1
    try:
        db.voter(a, rid, 1, chemin)
        assert False
    except db.ErreurVote:
        pass
    db.masquer(rid, False, chemin)
    assert len(db.classement(a, chemin)) == 1


# ------------------------------------------------------------------- site
def client_et_codes(n=3):
    from fastapi.testclient import TestClient
    _, chemin, codes, emp = monde(n)
    import app as site
    site._fenetres.clear()
    return TestClient(site.app, follow_redirects=False), codes, chemin


def test_site_refuse_sans_lien():
    c, _, _ = client_et_codes()
    assert c.get("/api/revendications").status_code == 401
    assert c.post("/api/voter", json={"id": 1, "valeur": 1}).status_code == 401
    assert c.post("/api/revendications", json={"texte": "x" * 20}).status_code == 401


def inscrire_via_site(c, code, pseudo="eleve1", mdp="motdepasse-1"):
    """Le parcours réel : clic sur le lien, puis création du pseudo + mot de passe."""
    r = c.get(f"/entrer?code={code}")
    assert r.status_code == 303 and r.headers["location"] == "/", r.status_code
    r2 = c.post("/api/inscription", json={"pseudo": pseudo, "mdp": mdp})
    assert r2.status_code == 200, r2.text
    return r2


def test_site_lien_invalide_et_lien_valide():
    c, codes, chemin = client_et_codes()
    assert c.get("/entrer?code=nimportequoi").status_code == 403
    r = c.get(f"/entrer?code={codes[0]}")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "invitation" in r.cookies and "session" not in r.cookies   # le lien seul n'ouvre PAS le mur
    assert c.get("/api/revendications").status_code == 401
    assert c.get("/api/etat").json() == {"connecte": False, "invitation": True}
    r2 = c.post("/api/inscription", json={"pseudo": "Marie_75", "mdp": "motdepasse-1"})
    assert r2.status_code == 200
    assert "httponly" in r2.headers["set-cookie"].lower()
    assert c.get("/api/revendications").status_code == 200
    assert c.get("/api/etat").json() == {"connecte": True, "invitation": False}
    with db.connexion(chemin) as conn:
        ligne = conn.execute("SELECT active, pseudo FROM comptes WHERE empreinte=?",
                             (db.empreinte(codes[0]),)).fetchone()
    assert ligne["active"] == 1 and ligne["pseudo"] == "marie_75"       # pseudo normalisé en minuscules


def test_le_lien_ne_sert_qu_une_seule_fois():
    from fastapi.testclient import TestClient
    import app as site
    c1, codes, _ = client_et_codes()
    inscrire_via_site(c1, codes[0], "premier", "motdepasse-1")
    c2 = TestClient(site.app, follow_redirects=False)                    # un autre appareil, même lien
    r = c2.get(f"/entrer?code={codes[0]}")
    assert r.status_code == 303 and r.headers["location"] == "/?lien=utilise"
    assert "invitation" not in r.cookies
    r2 = c2.post("/api/inscription", json={"pseudo": "usurpateur", "mdp": "motdepasse-2"})
    assert r2.status_code == 403                                         # pas d'invitation valide


def test_inscription_impossible_sans_avoir_clique_sur_le_lien():
    c, _, _ = client_et_codes()
    assert c.post("/api/inscription", json={"pseudo": "intrus", "mdp": "motdepasse-1"}).status_code == 403


def test_inscription_pseudo_et_mot_de_passe_controles():
    c, codes, _ = client_et_codes()
    c.get(f"/entrer?code={codes[0]}")
    for pseudo, mdp in (("ab", "motdepasse-1"), ("a b c", "motdepasse-1"), ("<script>", "motdepasse-1"),
                        ("valide", "court"), ("x" * 25, "motdepasse-1")):
        r = c.post("/api/inscription", json={"pseudo": pseudo, "mdp": mdp})
        assert r.status_code == 400, (pseudo, mdp)
    # les refus n'ont pas « brûlé » le lien : on peut encore s'inscrire correctement
    assert c.post("/api/inscription", json={"pseudo": "valide", "mdp": "motdepasse-1"}).status_code == 200


def test_pseudo_deja_pris_ne_brule_pas_le_lien():
    from fastapi.testclient import TestClient
    import app as site
    c1, codes, _ = client_et_codes()
    inscrire_via_site(c1, codes[0], "alex", "motdepasse-1")
    c2 = TestClient(site.app, follow_redirects=False)
    c2.get(f"/entrer?code={codes[1]}")
    assert c2.post("/api/inscription", json={"pseudo": "ALEX", "mdp": "motdepasse-2"}).status_code == 400
    assert c2.post("/api/inscription", json={"pseudo": "alex2", "mdp": "motdepasse-2"}).status_code == 200


def test_connexion_deconnexion_et_reconnexion():
    from fastapi.testclient import TestClient
    import app as site
    c, codes, _ = client_et_codes()
    inscrire_via_site(c, codes[0], "lea", "motdepasse-1")
    c.post("/api/revendications", json={"texte": "Proposition faite avant de partir"})
    assert c.post("/api/deconnexion").status_code == 200
    assert c.get("/api/revendications").status_code == 401                # vraiment déconnecté
    autre = TestClient(site.app, follow_redirects=False)                  # une semaine plus tard, autre appareil
    assert autre.post("/api/connexion", json={"pseudo": "LEA", "mdp": "motdepasse-1"}).status_code == 200
    r = autre.get("/api/revendications").json()
    assert r["revendications"][0]["a_moi"] is True                        # il retrouve SON compte


def test_connexion_mauvais_identifiants_message_identique():
    from fastapi.testclient import TestClient
    import app as site
    c, codes, _ = client_et_codes()
    inscrire_via_site(c, codes[0], "lea", "motdepasse-1")
    visiteur = TestClient(site.app, follow_redirects=False)
    r1 = visiteur.post("/api/connexion", json={"pseudo": "lea", "mdp": "mauvais-mdp"})
    r2 = visiteur.post("/api/connexion", json={"pseudo": "inconnu", "mdp": "motdepasse-1"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()                    # on ne révèle pas quels pseudos existent


def test_connexion_limite_les_essais_sur_un_pseudo():
    from fastapi.testclient import TestClient
    import app as site
    c, codes, _ = client_et_codes()
    inscrire_via_site(c, codes[0], "cible", "motdepasse-1")
    v = TestClient(site.app, follow_redirects=False)
    statuts = [v.post("/api/connexion", json={"pseudo": "cible", "mdp": f"essai-{i}"}).status_code
               for i in range(15)]
    assert 429 in statuts
    # même avec le BON mot de passe, la limite tient (sinon on pourrait deviner à l'infini)
    assert v.post("/api/connexion", json={"pseudo": "cible", "mdp": "motdepasse-1"}).status_code == 429


def test_le_mot_de_passe_n_est_jamais_stocke_en_clair():
    c, codes, chemin = client_et_codes()
    inscrire_via_site(c, codes[0], "lea", "un-mot-de-passe-secret")
    brut = Path(chemin).read_bytes()
    assert b"un-mot-de-passe-secret" not in brut
    with db.connexion(chemin) as conn:
        stocke = conn.execute("SELECT mdp FROM comptes WHERE pseudo='lea'").fetchone()[0]
    assert stocke.startswith("scrypt$")


def test_une_session_expiree_ne_donne_plus_acces():
    c, codes, chemin = client_et_codes()
    inscrire_via_site(c, codes[0])
    with db.connexion(chemin) as conn:
        conn.execute("UPDATE sessions SET expire = 1")
    assert c.get("/api/revendications").status_code == 401


def test_la_session_ne_contient_pas_le_code_du_lien():
    c, codes, chemin = client_et_codes()
    inscrire_via_site(c, codes[0])
    cookie = c.cookies.get("session")
    assert cookie and cookie != codes[0]
    brut = Path(chemin).read_bytes()
    assert cookie.encode() not in brut                 # la base ne garde que l'empreinte de la session


def test_site_parcours_complet_proposer_et_voter():
    c, codes, _ = client_et_codes()
    inscrire_via_site(c, codes[0])
    assert c.post("/api/revendications", json={"texte": "Repas à 1 euro pour tous"}).status_code == 200
    liste = c.get("/api/revendications").json()
    rid = liste["revendications"][0]["id"]
    assert liste["restantes"] == db.MAX_PROPOSITIONS - 1
    assert c.post("/api/voter", json={"id": rid, "valeur": 1}).status_code == 200
    assert c.get("/api/revendications").json()["revendications"][0]["score"] == 1
    assert c.post("/api/voter", json={"id": rid, "valeur": 9}).status_code == 400


def test_site_deux_etudiants_deux_comptes_distincts():
    from fastapi.testclient import TestClient
    import app as site
    c1, codes, _ = client_et_codes()
    c2 = TestClient(site.app, follow_redirects=False)
    inscrire_via_site(c1, codes[0], "alice", "motdepasse-1")
    inscrire_via_site(c2, codes[1], "bob", "motdepasse-2")
    c1.post("/api/revendications", json={"texte": "Proposition du premier étudiant"})
    rid = c1.get("/api/revendications").json()["revendications"][0]["id"]
    c1.post("/api/voter", json={"id": rid, "valeur": 1})
    c2.post("/api/voter", json={"id": rid, "valeur": 1})
    r = c2.get("/api/revendications").json()["revendications"][0]
    assert r["score"] == 2 and r["mon_vote"] == 1 and r["a_moi"] is False


def test_site_refuse_une_origine_etrangere():
    c, codes, _ = client_et_codes()
    inscrire_via_site(c, codes[0])
    pirate = {"Origin": "https://site-pirate.example"}
    assert c.post("/api/voter", json={"id": 1, "valeur": 1}, headers=pirate).status_code == 403
    assert c.post("/api/connexion", json={"pseudo": "eleve1", "mdp": "motdepasse-1"}, headers=pirate).status_code == 403
    assert c.post("/api/deconnexion", headers=pirate).status_code == 403


def test_site_entetes_de_securite_et_pas_de_docs():
    c, _, _ = client_et_codes()
    r = c.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404
    assert c.get("/vote.db").status_code == 404      # la base n'est JAMAIS servie
    assert c.get("/db.py").status_code == 404        # ni le code
    assert c.get("/app.js").status_code == 200


def test_site_limite_les_essais_de_codes():
    c, _, _ = client_et_codes()
    codes_http = [c.get(f"/entrer?code=faux{i}").status_code for i in range(40)]
    assert 429 in codes_http


def faux_request(pair, en_tetes=None):
    from starlette.requests import Request
    h = [(k.lower().encode(), v.encode()) for k, v in (en_tetes or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": h,
                    "query_string": b"", "client": (pair, 5000)})


def test_derriere_le_tunnel_chaque_visiteur_a_sa_propre_ip():
    import app as site
    a = faux_request("127.0.0.1", {"CF-Connecting-IP": "1.1.1.1"})   # connexion venue du tunnel
    b = faux_request("127.0.0.1", {"CF-Connecting-IP": "2.2.2.2"})
    assert site.ip_client(a) == "1.1.1.1" and site.ip_client(b) == "2.2.2.2"
    assert site.ip_client(faux_request("127.0.0.1")) == "127.0.0.1"  # sans en-tête : le pair


def test_en_tete_ip_ignore_si_la_connexion_ne_vient_pas_du_tunnel():
    import app as site
    pirate = faux_request("203.0.113.9", {"CF-Connecting-IP": "9.9.9.9"})
    assert site.ip_client(pirate) == "203.0.113.9"   # on ne se laisse pas tromper


def test_le_texte_html_n_est_pas_interprete_cote_page():
    js = (RACINE / "static" / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js            # tout passe par textContent


# ----------------------------------------------------------- envoi de mails
def test_envoi_un_code_distinct_par_adresse_et_jamais_affiche():
    emails = [f"etudiant{i}@univ.fr" for i in range(30)]
    codes = [db.nouveau_code() for _ in range(40)]
    recus = {}
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        ok, echecs, restants = envoyer_mails.distribuer(
            emails, codes, lambda adr, lien: recus.__setitem__(adr, lien), "https://site.fr")
    assert len(ok) == 30 and echecs == [] and len(restants) == 10
    liens = list(recus.values())
    assert len(set(liens)) == 30
    assert all(l.startswith("https://site.fr/entrer?code=") for l in liens)
    for c in codes:
        assert c not in sortie.getvalue(), "un code a été affiché dans la sortie !"


def test_envoi_ordre_melange():
    emails = [f"e{i}@u.fr" for i in range(40)]
    ordre = []
    with contextlib.redirect_stdout(io.StringIO()):
        envoyer_mails.distribuer(emails, [db.nouveau_code() for _ in range(40)],
                                 lambda adr, lien: ordre.append(adr), "https://s.fr")
    assert ordre != emails


def test_envoi_echec_retente_avec_un_autre_code():
    codes = [db.nouveau_code() for _ in range(10)]
    essais = {"n": 0}

    def capricieux(adr, lien):
        essais["n"] += 1
        if essais["n"] == 1:
            raise OSError("panne passagère")

    with contextlib.redirect_stdout(io.StringIO()):
        ok, echecs, restants = envoyer_mails.distribuer(["a@u.fr"], codes, capricieux, "https://s.fr")
    assert ok == ["a@u.fr"] and echecs == []
    assert len(restants) == 8            # 2 codes consommés (1 raté jamais livré, 1 livré)


def test_envoi_refuse_si_pas_assez_de_codes():
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            envoyer_mails.distribuer(["a@u.fr", "b@u.fr"], ["seul-code"], lambda a, l: None, "https://s.fr")
        assert False
    except ValueError:
        pass


def test_lecture_des_adresses_filtre_domaine_et_doublons():
    dossier = tempfile.mkdtemp()
    f = Path(dossier) / "e.txt"
    f.write_text("A@univ.fr\na@univ.fr\nb@univ.fr\npirate@gmail.com\nn_importe_quoi\n\n", encoding="utf-8")
    valides, refusees = envoyer_mails.lire_emails(f, "univ.fr")
    assert valides == ["a@univ.fr", "b@univ.fr"]
    assert set(refusees) == {"pirate@gmail.com", "n_importe_quoi"}


def test_suppression_du_fichier_de_codes():
    f = Path(tempfile.mkdtemp()) / "codes.txt"
    f.write_text("secret-1\nsecret-2\n", encoding="utf-8")
    envoyer_mails.supprimer_fichier(f)
    assert not f.exists()


# ------------------------------------------------------------- vérification
def test_verifier_conforme_puis_detecte_un_faux_compte():
    dossier, chemin, codes, emp = monde(10)
    ref = Path(dossier) / "reference.txt"
    ref.write_text("\n".join(emp) + "\n", encoding="utf-8")
    assert verifier.verifier(ref, chemin, etudiants=10)["ok"] is True

    intrus = db.empreinte(db.nouveau_code())
    db.importer_empreintes([intrus], chemin)               # un admin triche
    r = verifier.verifier(ref, chemin, etudiants=10)
    assert r["ok"] is False and r["ajoutes"] == [intrus]


def test_verifier_detecte_un_compte_supprime():
    dossier, chemin, codes, emp = monde(10)
    ref = Path(dossier) / "reference.txt"
    ref.write_text("\n".join(emp) + "\n", encoding="utf-8")
    with db.connexion(chemin) as conn:
        conn.execute("DELETE FROM comptes WHERE empreinte = ?", (emp[0],))
    r = verifier.verifier(ref, chemin)
    assert r["ok"] is False and r["manquants"] == [emp[0]]


def test_verifier_detecte_plus_d_actifs_que_d_etudiants():
    dossier, chemin, codes, emp = monde(10)
    ref = Path(dossier) / "reference.txt"
    ref.write_text("\n".join(emp) + "\n", encoding="utf-8")
    for c in codes:
        db.marquer_active(db.empreinte(c), chemin)
    assert verifier.verifier(ref, chemin, etudiants=10)["ok"] is True
    assert verifier.verifier(ref, chemin, etudiants=8)["depasse_etudiants"] is True


def test_verifier_detecte_des_votes_de_comptes_inconnus():
    dossier, chemin, codes, emp = monde(5)
    ref = Path(dossier) / "reference.txt"
    ref.write_text("\n".join(emp) + "\n", encoding="utf-8")
    a = db.empreinte(codes[0])
    rid = db.ajouter_revendication(a, "Une revendication assez longue ici", chemin)
    with db.connexion(chemin) as conn:                    # vote injecté directement
        conn.execute("INSERT INTO votes VALUES (?, ?, 1)", ("f" * 64, rid))
    assert verifier.verifier(ref, chemin)["votes_de_comptes_inconnus"] == 1


# ------------------------------------------------------------------ lanceur
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    echecs = 0
    for nom, f in tests:
        try:
            f()
            print(f"  ok   {nom}")
        except Exception as e:  # noqa: BLE001
            echecs += 1
            print(f"  ECHEC {nom} : {type(e).__name__}: {e}")
    print(f"\n{len(tests) - echecs}/{len(tests)} tests passent.")
    sys.exit(1 if echecs else 0)
