"""
Le site. Le lien reçu par mail sert UNE SEULE FOIS : il permet de créer un
pseudo et un mot de passe. Ensuite on se connecte avec ça (chaque semaine, à
chaque vote d'AG), puis on propose et on vote.

Lancer :  py -3.12 -m uvicorn app:app --host 127.0.0.1 --port 8100 --no-access-log

⚠️ --no-access-log est IMPORTANT : le code est dans l'adresse du lien
(/entrer?code=...). Si le serveur journalise les adresses, les codes se
retrouvent dans un fichier. Le site redirige aussitôt pour que le code
ne reste pas dans la barre d'adresse.
"""
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

import db

DOSSIER = Path(__file__).resolve().parent
STATIQUE = DOSSIER / "static"
FICHIERS = {
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
INVITATION_S = 3600           # le temps de choisir son pseudo après avoir cliqué sur le lien
SESSION_S = db.SESSION_JOURS * 24 * 3600

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
def _demarrage():
    db.init_base()


# ------------------------------------------------------------ sécurité
@app.middleware("http")
async def en_tetes(request: Request, call_next):
    reponse = await call_next(request)
    reponse.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    reponse.headers["Referrer-Policy"] = "no-referrer"
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


_fenetres: dict[str, deque] = defaultdict(deque)


def trop_rapide(cle: str, maximum: int, fenetre_s: int = 60) -> bool:
    """Limiteur simple en mémoire : au plus `maximum` appels par fenêtre."""
    maintenant = time.monotonic()
    f = _fenetres[cle]
    while f and maintenant - f[0] > fenetre_s:
        f.popleft()
    if len(f) >= maximum:
        return True
    f.append(maintenant)
    return False


def ip_client(request: Request) -> str:
    """
    Derrière le tunnel Cloudflare, tout arrive depuis 127.0.0.1 : sans ça, tous
    les visiteurs partageraient la même limite d'essais. On ne croit l'en-tête
    que si la connexion vient de NOTRE machine (donc du tunnel), jamais d'un
    client quelconque qui pourrait le falsifier.
    """
    pair = request.client.host if request.client else "?"
    if pair in ("127.0.0.1", "::1"):
        vraie = request.headers.get("cf-connecting-ip")
        if vraie:
            return vraie.strip()[:64]
    return pair


def origine_ok(request: Request) -> bool:
    """Anti-CSRF : un POST doit venir de notre propre site."""
    origine = request.headers.get("origin")
    if not origine:
        return True
    return urlparse(origine).netloc == request.headers.get("host", "")


def compte_courant(request: Request):
    return db.compte_depuis_session(request.cookies.get("session"))


def invitation_courante(request: Request):
    return db.invitation_valide(request.cookies.get("invitation"))


def en_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def poser_session(reponse, request: Request, h: str) -> None:
    reponse.set_cookie(
        "session", db.creer_session(h),
        max_age=SESSION_S,
        httponly=True,        # le JavaScript du site ne peut pas le lire
        samesite="lax",
        secure=en_https(request),
    )


# ---------------------------------------------------------------- pages
@app.get("/")
def accueil():
    return FileResponse(STATIQUE / "index.html", media_type="text/html; charset=utf-8")


@app.get("/entrer")
def entrer(request: Request, code: str = ""):
    """
    Le lien reçu par mail. Il ne crée PAS de session : il ouvre seulement la page
    « choisis ton pseudo et ton mot de passe », et seulement s'il n'a pas déjà servi.
    """
    if trop_rapide("entrer:" + ip_client(request), maximum=30):
        return PlainTextResponse("Trop d'essais, réessaie dans une minute.", status_code=429)
    h = db.compte_depuis_code(code)
    if not h:
        return PlainTextResponse(
            "Lien invalide. Utilise exactement le lien reçu par mail.", status_code=403
        )
    if db.est_inscrit(h):
        return RedirectResponse("/?lien=utilise", status_code=303)
    reponse = RedirectResponse("/", status_code=303)
    reponse.set_cookie(
        "invitation", code,
        max_age=INVITATION_S,
        httponly=True,
        samesite="lax",
        secure=en_https(request),
    )
    return reponse


# ------------------------------------------------------------------ API
class PropositionIn(BaseModel):
    texte: str


class VoteIn(BaseModel):
    id: int
    valeur: int


class IdentifiantsIn(BaseModel):
    pseudo: str
    mdp: str


def non_connecte():
    return JSONResponse({"erreur": "Connecte-toi pour continuer."}, status_code=401)


@app.get("/api/etat")
def etat(request: Request):
    """Dit à la page quoi afficher : le mur, l'inscription ou la connexion."""
    return {"connecte": bool(compte_courant(request)), "invitation": bool(invitation_courante(request))}


@app.post("/api/inscription")
def inscription(request: Request, corps: IdentifiantsIn):
    if not origine_ok(request):
        return JSONResponse({"erreur": "Origine refusée."}, status_code=403)
    if trop_rapide("insc:" + ip_client(request), maximum=10):
        return JSONResponse({"erreur": "Trop d'essais, réessaie dans une minute."}, status_code=429)
    h = invitation_courante(request)
    if not h:
        return JSONResponse(
            {"erreur": "Ce lien n'est plus valable. Utilise ton lien reçu par mail, ou connecte-toi."},
            status_code=403,
        )
    try:
        db.inscrire(h, corps.pseudo, corps.mdp)
    except db.ErreurVote as e:
        return JSONResponse({"erreur": str(e)}, status_code=400)
    reponse = JSONResponse({"ok": True})
    reponse.delete_cookie("invitation")
    poser_session(reponse, request, h)
    return reponse


@app.post("/api/connexion")
def connexion(request: Request, corps: IdentifiantsIn):
    if not origine_ok(request):
        return JSONResponse({"erreur": "Origine refusée."}, status_code=403)
    pseudo = db.normaliser_pseudo(corps.pseudo)
    if trop_rapide("conn-ip:" + ip_client(request), maximum=20) or trop_rapide("conn-pseudo:" + pseudo, maximum=10):
        return JSONResponse({"erreur": "Trop d'essais, réessaie dans une minute."}, status_code=429)
    h = db.verifier_connexion(corps.pseudo, corps.mdp)
    if not h:
        # Même message que le pseudo existe ou non : on ne révèle pas quels pseudos existent.
        return JSONResponse({"erreur": "Pseudo ou mot de passe incorrect."}, status_code=401)
    reponse = JSONResponse({"ok": True})
    poser_session(reponse, request, h)
    return reponse


@app.post("/api/deconnexion")
def deconnexion(request: Request):
    if not origine_ok(request):
        return JSONResponse({"erreur": "Origine refusée."}, status_code=403)
    db.supprimer_session(request.cookies.get("session"))
    reponse = JSONResponse({"ok": True})
    reponse.delete_cookie("session")
    return reponse


@app.get("/api/revendications")
def lister(request: Request):
    h = compte_courant(request)
    if not h:
        return non_connecte()
    return {
        "revendications": db.classement(h),
        "restantes": db.propositions_restantes(h),
    }


@app.post("/api/revendications")
def proposer(request: Request, corps: PropositionIn):
    if not origine_ok(request):
        return JSONResponse({"erreur": "Origine refusée."}, status_code=403)
    h = compte_courant(request)
    if not h:
        return non_connecte()
    if trop_rapide("act:" + h, maximum=30):
        return JSONResponse({"erreur": "Doucement, réessaie dans une minute."}, status_code=429)
    try:
        db.ajouter_revendication(h, corps.texte)
    except db.ErreurVote as e:
        return JSONResponse({"erreur": str(e)}, status_code=400)
    return {"ok": True}


@app.post("/api/voter")
def voter(request: Request, corps: VoteIn):
    if not origine_ok(request):
        return JSONResponse({"erreur": "Origine refusée."}, status_code=403)
    h = compte_courant(request)
    if not h:
        return non_connecte()
    if trop_rapide("act:" + h, maximum=30):
        return JSONResponse({"erreur": "Doucement, réessaie dans une minute."}, status_code=429)
    try:
        db.voter(h, corps.id, corps.valeur)
    except db.ErreurVote as e:
        return JSONResponse({"erreur": str(e)}, status_code=400)
    return {"ok": True}


# ⚠️ En DERNIER : cette route attrape « /quelquechose », elle doit passer
# après /entrer sinon elle l'avalerait.
@app.get("/{nom}")
def statique(nom: str):
    if nom not in FICHIERS:
        return PlainTextResponse("Introuvable", status_code=404)
    return FileResponse(STATIQUE / nom, media_type=FICHIERS[nom])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8100, access_log=False)
