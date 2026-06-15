# Setting up the Google Docs review mode

This is a one-time setup. It gets you a **"Claude Review"** identity that Claude
uses to post replies in your Google Docs comment threads, and the OAuth
credentials the local bridge (`gdocs_review.py`) needs to act as it.

You do this once; afterwards the loop is just "highlight text, comment, ask
Claude to do a pass."

## 1. Create the "Claude Review" Google account

Claude's replies are authored by whoever the bridge signs in as, so create a
dedicated account to keep its feedback visually distinct from yours.

- Go to <https://accounts.google.com/signup> and make a new Google account.
- Use a name like **Claude Review** (first name "Claude", last name "Review").
  That display name is what shows on every comment reply.
- A normal free Gmail account is fine.

> You *can* skip this and just authenticate as yourself — but then Claude's
> replies look like they came from you, which defeats the point.

## 2. Create a Google Cloud project + OAuth credentials

You can sign in to Google Cloud with either your own account or the Claude
Review account; the project just holds the API credentials.

1. Open <https://console.cloud.google.com/> and create a new project
   (e.g. "claude-doc-review").
2. **Enable the APIs.** APIs & Services → Library → enable both:
   - **Google Drive API** (for comments and replies)
   - **Google Docs API** (for reading/editing the doc body)
3. **Configure the OAuth consent screen.** APIs & Services → OAuth consent screen:
   - User type: **External**.
   - Fill in the required app name / support email (any values are fine).
   - **Leave it in "Testing" mode** — do *not* publish. In testing mode the app
     needs no Google verification.
   - Under **Test users**, add the **Claude Review** account's email (and your
     own, if you'll ever sign in as yourself). Only listed test users can
     authorize the app — that's the whole security boundary for a personal tool.
4. **Create the OAuth client.** APIs & Services → Credentials → Create
   credentials → **OAuth client ID** → Application type: **Desktop app**.
   - Download the JSON. Save it next to `gdocs_review.py` as:
     ```
     credentials.json
     ```
   - This file is already git-ignored. Keep it private; it's not a password but
     it identifies your app.

## 3. Sign in as Claude Review

From the project directory:

```sh
pip install -r requirements.txt
python3 gdocs_review.py auth
```

A browser opens. **Sign in as the Claude Review account** and grant the
requested Drive/Docs access. (You'll see an "unverified app" warning because the
app is in testing mode — that's expected; continue.) The token is cached in
`.review/google-token.json` (git-ignored) and refreshed automatically after that.

`auth` prints who you authenticated as, so you can confirm it says Claude Review.

## 4. Share your docs with Claude Review

For Claude to read comments and reply, the Claude Review account needs access to
the document. In each Google Doc you want reviewed:

- **Share** → add the Claude Review account's email → **Editor** (Editor is
  needed to reply to comments and, optionally, to edit text).

That's it. Now use the loop in the README under "Google Docs mode".

## Scopes & privacy note

The bridge requests the Drive and Docs scopes for the signed-in account. Unlike
the local Markdown tool, this mode necessarily sends document text and comments
to Google's API (it's your Google Doc, on Google's servers, either way). Nothing
is sent anywhere else — the bridge talks only to Google and to your local Claude.

## Troubleshooting

- **`no credentials.json found`** — you haven't saved the OAuth client JSON next
  to `gdocs_review.py` yet (step 2.4).
- **`access_denied` / 403 during sign-in** — the account you're signing in with
  isn't in the OAuth consent screen's **Test users** list (step 2.3).
- **`File not found` on a doc** — the Claude Review account hasn't been shared on
  that document (step 4), or the URL/id is wrong.
- **Replies show the wrong author** — you signed in as yourself, not Claude
  Review. Delete `.review/google-token.json` and run `auth` again.
