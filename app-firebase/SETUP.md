# HUD Study Coding: your own free web app (Firebase)

Everything here is on Google's free "Spark" plan. No credit card needed.
Free limits (about 50,000 reads and 20,000 writes per day) are far more than 8 participants need.

## 1. Create the Firebase project (5 min)
1. Go to https://console.firebase.google.com and sign in with Google.
2. **Create a project** (name it e.g. `hud-study`). Turn Google Analytics OFF.
3. **Build -> Firestore Database -> Create database**. Choose a location near you (e.g. `asia-southeast1`), **Production mode**.
4. **Build -> Authentication -> Get started -> Google -> Enable**, pick your email as the support email, Save.
5. **Project settings (gear) -> Your apps -> Web (`</>`)**. Register an app (skip Hosting). Copy the `firebaseConfig` values.
6. Open `firebase-config.js` and paste `apiKey`, `authDomain`, `projectId`, `appId`.

## 2. Who can get in
1. Firestore -> **Rules** tab. Paste the contents of `firestore.rules`.
2. Add every groupmate's Google email in the list (lowercase, comma between). **Publish**.
Anyone not on the list can open the page but cannot read or write anything.

## 3. Put the app online (free)
**GitHub Pages (easiest if you already use GitHub):**
1. Put this folder (`app-firebase`) in a GitHub repo (do NOT add recordings or `participant_roster.csv`).
2. Repo -> Settings -> Pages -> deploy from the branch/folder that holds `index.html`.
3. Your link is `https://<user>.github.io/<repo>/`.

**Then authorise that address for sign-in:**
Firebase -> Authentication -> Settings -> **Authorized domains -> Add domain** -> `<user>.github.io`.
(`localhost` is already allowed for testing.)

## 4. First run
1. Open the link, sign in with Google.
2. Click **Load starter data** (top right): loads the 2 practice clips and the dummy participants.
   (Real study: ask me for a version without the dummy data, or delete the sample documents in the Firebase console.)
3. Groupmates open the same link and sign in. Everyone sees the same data live.
   Each person should pick **Coder A** or **Coder B** (coder B tags about 25% of sessions for agreement).

## Test on your own PC before deploying
In this folder run `python -m http.server 8000` and open http://localhost:8000
(do not double-click index.html: sign-in does not work from a file).

## Getting the data back into the analysis
App -> **Data** tab -> pick a table -> **Export CSV**. Put the files in `hud-data/raw/`
with the names the analysis expects (the export names already match).

## Privacy
Only tags, codes and anonymised transcripts live in the database. Recordings stay on each
coder's computer (the app has a "choose video file" button). Never upload `participant_roster.csv`.
