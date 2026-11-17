# MailMind v3 — Deploy to Render.com (Free)

## What you'll set up
- A live website at `https://mailmind-xxxx.onrender.com`
- Free PostgreSQL database (data persists)
- Google Sign-In for any Gmail user
- No credit card needed

---

## Step 1 — Get a Google OAuth Client ID

1. Go to https://console.cloud.google.com
2. Create a new project (or use an existing one) → name it **MailMind**
3. Left sidebar → **APIs & Services** → **Library**
   - Search "Gmail API" → Enable it
4. Left sidebar → **APIs & Services** → **OAuth consent screen**
   - User Type: **External** → Create
   - App name: `MailMind`
   - User support email: your email
   - Developer contact: your email
   - Save and Continue through all steps
   - **Publishing status**: leave as "Testing" for now (you can add test users)
5. Left sidebar → **Credentials** → **+ Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: `MailMind Web`
   - Authorized redirect URIs: (leave blank for now — you'll add this after deploy)
   - Click **Create**
6. Copy the **Client ID** and **Client Secret** — you'll need them in Step 3

---

## Step 2 — Deploy to Render

1. Go to https://render.com and sign up / log in
2. Click **New** → **Web Service**
3. Connect your GitHub account if prompted
4. Upload the `mailmind3` folder to a new GitHub repo:
   - Go to https://github.com/new → create a repo named `mailmind`
   - Upload all files from the `mailmind3` folder
   - Or: install Git and run:
     ```
     cd mailmind3
     git init
     git add .
     git commit -m "Initial MailMind v3"
     git remote add origin https://github.com/YOUR_USERNAME/mailmind.git
     git push -u origin main
     ```
5. Back on Render → **New** → **Web Service** → connect the `mailmind` repo
6. Settings:
   - **Name**: `mailmind`
   - **Region**: pick nearest to you
   - **Branch**: `main`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120`
   - **Plan**: Free
7. Click **Create Web Service** — wait ~2 minutes for first deploy

---

## Step 3 — Set Environment Variables

In Render dashboard → your web service → **Environment** tab → add:

| Key | Value |
|-----|-------|
| `GOOGLE_CLIENT_ID` | Your Client ID from Step 1 |
| `GOOGLE_CLIENT_SECRET` | Your Client Secret from Step 1 |
| `FLASK_SECRET` | Any random string (e.g. `mysecretkey123abc`) |

---

## Step 4 — Add a Free Database

1. Render dashboard → **New** → **PostgreSQL**
2. Name: `mailmind-db` | Plan: **Free** → Create
3. Once created, click it → copy the **Internal Database URL**
4. Go back to your Web Service → **Environment** → add:
   - Key: `DATABASE_URL` | Value: paste the URL
5. Redeploy: Web Service → **Manual Deploy** → **Deploy latest commit**

---

## Step 5 — Add Redirect URI to Google

1. Go back to https://console.cloud.google.com → **Credentials**
2. Click your OAuth client → **Edit**
3. Under **Authorized redirect URIs** → **Add URI**:
   ```
   https://YOUR-APP-NAME.onrender.com/auth/callback
   ```
   Replace `YOUR-APP-NAME` with the actual Render subdomain (e.g. `mailmind-ab12`)
4. Save

---

## Step 6 — Test It!

1. Visit `https://YOUR-APP-NAME.onrender.com`
2. Click **Sign in with Google**
3. Grant Gmail read access
4. Click **Scan emails** → events appear!

---

## Notes

- **Free tier**: Render spins down after 15 min of inactivity. First visit may take ~30s to wake up.
- **To upgrade**: Change the web service plan to Starter ($7/mo) for always-on.
- **Share**: Anyone with the link can sign in with their own Gmail — their data is separate.
- **Adding test users**: In Google Cloud Console → OAuth consent screen → Test users → Add users (required while app is in "Testing" mode).
- **Go live**: To allow ANY Google account (not just test users), submit your app for Google verification, or stay in Testing and add users manually.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `redirect_uri_mismatch` | The URI in Google must exactly match your Render URL |
| 500 on login | Check environment variables are set correctly |
| Database error | Make sure `DATABASE_URL` is set and app was redeployed after adding it |
| Scan returns 0 events | Try a longer date range; check Gmail has emails with dates/deadlines |
