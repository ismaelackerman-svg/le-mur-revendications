// Tout le texte venant des étudiants passe par textContent : jamais de HTML
// injecté, donc impossible d'y glisser du code.
const $ = (id) => document.getElementById(id);

let donnees = { revendications: [], restantes: 0 };
let tri = "popu"; // "popu" = les plus soutenues, "recent" = les plus récentes
let minuteur = null;
let pret = false; // vrai quand la liste a été chargée

function message(texte, type) {
  const m = $("message");
  m.textContent = texte || "";
  m.className = type || "";
  clearTimeout(minuteur);
  if (texte && type === "ok") minuteur = setTimeout(() => message(""), 3500);
}

async function appel(url, options) {
  const rep = await fetch(url, options);
  let corps = {};
  try { corps = await rep.json(); } catch (e) { /* pas de JSON */ }
  if (!rep.ok) {
    const err = new Error(corps.erreur || "Erreur inattendue.");
    err.statut = rep.status;
    throw err;
  }
  return corps;
}

function jourLisible(iso) {
  const [a, m, j] = (iso || "").split("-");
  return j && m ? j + "/" + m : "";
}

function boutonVote(symbole, actif, contre, titre, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = symbole;
  b.title = titre;
  b.setAttribute("aria-label", titre);
  b.setAttribute("aria-pressed", actif ? "true" : "false");
  if (actif) b.classList.add("actif");
  if (actif && contre) b.classList.add("contre");
  b.addEventListener("click", onclick);
  return b;
}

async function voter(id, valeur) {
  try {
    await appel("/api/voter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, valeur }),
    });
    await charger();
  } catch (e) { message(e.message, "erreur"); }
}

function carte(r, rang) {
  const li = document.createElement("li");
  li.className = "carte" + (tri === "popu" && rang < 3 && r.score > 0 ? " top" : "");

  const votes = document.createElement("div");
  votes.className = "votes";
  // Recliquer sur son vote le retire (valeur 0).
  votes.appendChild(boutonVote("▲", r.mon_vote === 1, false, "Pour",
    () => voter(r.id, r.mon_vote === 1 ? 0 : 1)));
  const score = document.createElement("strong");
  score.textContent = r.score;
  score.title = r.pour + " pour, " + r.contre + " contre";
  votes.appendChild(score);
  votes.appendChild(boutonVote("▼", r.mon_vote === -1, true, "Contre",
    () => voter(r.id, r.mon_vote === -1 ? 0 : -1)));

  const corps = document.createElement("div");
  corps.className = "corps";
  const p = document.createElement("p");
  p.textContent = r.texte;
  corps.appendChild(p);

  const meta = document.createElement("div");
  meta.className = "meta";
  if (tri === "popu" && rang < 3 && r.score > 0) {
    const b = document.createElement("span");
    b.className = "badge";
    b.textContent = "#" + (rang + 1);
    meta.appendChild(b);
  }
  const detail = document.createElement("span");
  detail.textContent = r.pour + " pour · " + r.contre + " contre";
  meta.appendChild(detail);
  const jour = jourLisible(r.jour);
  if (jour) {
    const d = document.createElement("span");
    d.textContent = "· " + jour;
    meta.appendChild(d);
  }
  if (r.a_moi) {
    const moi = document.createElement("span");
    moi.className = "badge moi";
    moi.textContent = "ta proposition";
    meta.appendChild(moi);
  }
  corps.appendChild(meta);

  li.appendChild(votes);
  li.appendChild(corps);
  return li;
}

function afficher() {
  const liste = $("liste");
  liste.replaceChildren();
  let items = donnees.revendications.slice();
  if (tri === "mes") items = items.filter((r) => r.a_moi);
  if (tri === "recent") items.sort((a, b) => b.id - a.id);

  if (!items.length) {
    const vide = document.createElement("li");
    vide.className = "vide";
    const t = document.createElement("strong");
    t.textContent = tri === "mes" ? "Tu n'as encore rien proposé" : "Le mur est vide";
    vide.appendChild(t);
    vide.appendChild(document.createTextNode("Propose une revendication avec la croix orange en bas à droite."));
    liste.appendChild(vide);
  }
  items.forEach((r, i) => liste.appendChild(carte(r, i)));

  $("total").textContent = items.length + (items.length > 1 ? " revendications" : " revendication");
  $("restantes").textContent =
    donnees.restantes > 0
      ? "Il te reste " + donnees.restantes + " proposition" + (donnees.restantes > 1 ? "s" : "")
      : "Plus de proposition disponible";
  $("envoyer").disabled = donnees.restantes <= 0;
}

async function charger() {
  try {
    donnees = await appel("/api/revendications");
    pret = true;
    $("auth").hidden = true;
    $("m-sortie").hidden = false;
    $("entete-liste").hidden = false;
    $("fab").hidden = false;
    afficher();
  } catch (e) {
    pret = false;
    $("entete-liste").hidden = true;
    $("fab").hidden = true;
    $("m-sortie").hidden = true;
    $("liste").replaceChildren();
    if (e.statut === 401) await afficherAuth();
    else message(e.message, "erreur");
  }
}

// ---------- inscription (lien valable une fois) / connexion
let modeAuth = "connexion"; // "inscription" ou "connexion"

async function afficherAuth() {
  let etat = { invitation: false };
  try { etat = await appel("/api/etat"); } catch (e) { /* on affichera la connexion */ }
  modeAuth = etat.invitation ? "inscription" : "connexion";
  const insc = modeAuth === "inscription";
  $("auth-titre").textContent = insc ? "Crée ton compte" : "Connexion";
  $("auth-texte").textContent = insc
    ? "Choisis un pseudo et un mot de passe. Ils ne sont reliés ni à ton nom ni à ton mail : note-les bien, " +
      "on ne peut pas les récupérer. Ce lien ne servira qu'une fois."
    : "Entre le pseudo et le mot de passe que tu as choisis à ta première visite.";
  $("auth-bouton").textContent = insc ? "Créer mon compte" : "Me connecter";
  $("zone-confirmation").hidden = !insc;
  $("mdp").setAttribute("autocomplete", insc ? "new-password" : "current-password");
  $("auth-aide").textContent = insc
    ? ""
    : "Pas encore de compte ? Clique sur le lien personnel reçu par mail (il ne marche qu'une fois).";
  if (new URLSearchParams(location.search).get("lien") === "utilise") {
    message("Ce lien a déjà servi à créer un compte. Connecte-toi avec ton pseudo.", "erreur");
  }
  $("auth-erreur").textContent = "";
  $("auth").hidden = false;
}

$("auth-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("auth-erreur").textContent = "";
  const pseudo = $("pseudo").value;
  const mdp = $("mdp").value;
  if (modeAuth === "inscription" && mdp !== $("mdp2").value) {
    $("auth-erreur").textContent = "Les deux mots de passe ne sont pas identiques.";
    return;
  }
  try {
    await appel(modeAuth === "inscription" ? "/api/inscription" : "/api/connexion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pseudo, mdp }),
    });
    $("mdp").value = "";
    $("mdp2").value = "";
    history.replaceState(null, "", "/");   // enlève ?lien=utilise de l'adresse
    message("");
    await charger();
  } catch (e) { $("auth-erreur").textContent = e.message; }
});

$("m-sortie").addEventListener("click", async () => {
  ouvrirMenu(false);
  try { await appel("/api/deconnexion", { method: "POST" }); } catch (e) { /* tant pis */ }
  donnees = { revendications: [], restantes: 0 };
  await charger();
});

// ---------- menu (les 3 barres en haut à droite) et tri
const TITRES = { popu: "Les plus soutenues", recent: "Les plus récentes", mes: "Mes propositions" };
const ITEMS_MENU = { popu: "m-popu", recent: "m-recent", mes: "m-mes" };

function ouvrirMenu(ouvert) {
  $("menu").hidden = !ouvert;
  $("burger").setAttribute("aria-expanded", ouvert ? "true" : "false");
}

function choisirTri(nouveau) {
  tri = nouveau;
  $("titre-liste").textContent = TITRES[nouveau];
  for (const cle in ITEMS_MENU) {
    $(ITEMS_MENU[cle]).classList.toggle("courant", cle === nouveau);
  }
  if (pret) afficher();   // avant le chargement, rien à afficher (évite un « mur vide » qui clignote)
}

$("burger").addEventListener("click", () => ouvrirMenu($("menu").hidden));
for (const cle in ITEMS_MENU) {
  $(ITEMS_MENU[cle]).addEventListener("click", () => { choisirTri(cle); ouvrirMenu(false); });
}
// Un clic en dehors du menu, ou la touche Échap, le referme.
document.addEventListener("click", (e) => {
  if (!$("menu").hidden && !e.target.closest("#menu") && !e.target.closest("#burger")) ouvrirMenu(false);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") ouvrirMenu(false); });
choisirTri("popu");

// ---------- fenêtre de proposition
const dialogue = $("dialogue");

function ouvrir() {
  $("erreur-dialogue").textContent = "";
  dialogue.showModal();
  $("texte").focus();
}
function fermer() { dialogue.close(); }

$("fab").addEventListener("click", ouvrir);
$("fermer").addEventListener("click", fermer);
// Un clic sur le fond gris (en dehors de la fenêtre) la ferme.
dialogue.addEventListener("click", (e) => {
  if (e.target === dialogue) fermer();
});

$("texte").addEventListener("input", () => {
  $("compteur").textContent = $("texte").value.length + " / 400";
});

$("envoyer").addEventListener("click", async () => {
  $("erreur-dialogue").textContent = "";
  try {
    await appel("/api/revendications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texte: $("texte").value }),
    });
    $("texte").value = "";
    $("compteur").textContent = "0 / 400";
    fermer();
    choisirTri("recent"); // on voit tout de suite sa proposition en haut
    await charger();
    message("Ta revendication est sur le mur.", "ok");
  } catch (e) { $("erreur-dialogue").textContent = e.message; }
});

charger();
