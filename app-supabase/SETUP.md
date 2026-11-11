# HUD Study Coding on Supabase (free)

Free plan, no credit card. Limits (500 MB database, 50,000 monthly users) are far beyond this study.
One catch: a free project **pauses after about a week with no activity**. If the app stops loading,
open the Supabase dashboard and click **Restore project** (takes a minute; data is kept).

## 1. Create the project (5 min)
1. https://supabase.com -> sign in (GitHub or email) -> **New project**. Pick a name, a database password (save it), region `Southeast Asia (Singapore)`.
2. Wait for it to finish setting up.

## 2. Create the tables
SQL Editor -> New query -> paste all of `setup.sql` -> Run. (Safe to run again.)

## 3. Create the shared group account (this is your group password)
1. **Authentication -> Users -> Add user -> Create new user**.
2. Email: `group@hudstudy.com` (made up, it never receives mail). Password: the group password you choose.
3. Tick **Auto Confirm User**. Create.
4. Optional but recommended: **Authentication -> Sign In / Providers -> Email**, turn OFF "Allow new users to sign up" so nobody can create their own account.

## 4. Connect the app
1. Paste the **Project URL** (just `https://xxxx.supabase.co`, nothing after it) and the **publishable key** into `supabase-config.js`.
   (Never use the secret / service_role key.)
2. Leave `groupEmail` as `group@hudstudy.com`, or change it to match step 3.

## 5. Put it online (free)
GitHub Pages: put this folder in a repo -> Settings -> Pages -> deploy from the branch/folder with `index.html`.
Do NOT add recordings or `participant_roster.csv`.

## 6. First run
1. Open the app, type your name and the group password, click **Enter**.
2. Click **Load starter data** (top right) to load the practice clips and the dummy participants.
3. Groupmates open the same link and enter their own name plus the same password. Everyone sees the same data live.
   Use a different name per person: tags are saved under that name.
   Each person picks **Coder A** or **Coder B**.

Test on your PC first: run `python -m http.server 8000` in this folder, open http://localhost:8000.
(Opening `index.html` by double-click will not work: it needs a web address.)

## Before the real study: remove the dummy data
SQL Editor ->
`delete from docs where data->>'by' = 'sample';`
`delete from docs where collection = 'sessions' and data->>'kind' = 'study';`

## Getting data into the analysis
App -> **Data** tab -> pick a table -> **Export CSV** -> put the files in `hud-data/raw/`.

## Privacy
Anyone with the group password can read and edit everything, so share it only with your group and change it in Authentication -> Users if it leaks. Only tags, codes and anonymised transcripts go in the database. Recordings stay on each coder's computer
(use the app's "choose video file" button). Never upload `participant_roster.csv`.
