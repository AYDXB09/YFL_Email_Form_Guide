# YFL U11 Form Guide Automation

A Playwright-based automation that logs into the **YFL LeagueHub** portal, scrapes **standings, fixtures, and weekly form** for YFL **Under 11 Divisions 1–3**, builds a rich HTML “enhanced form guide”, and emails it automatically using the **Gmail API**.

Although the default configuration targets **U11 Div 1, Div 2, Div 3**, the scraper is designed so you can adapt it to **any age group and division** by swapping tournament IDs.

---

## ⭐ Key Features

### 🔐 Login + Scraping
- Secure login to YFL LeagueHub with username + password  
- Scrapes **official league table**  
- Scrapes fixtures **week-by-week** (played, scheduled, voided)

### 📊 Enhanced Form Guide
- Full-season form guide, not just last 4 matches  
- Weekly badges:
  - **W** – Win  
  - **L** – Loss  
  - **D** – Draw  
  - **N** – Not played / scheduled  
  - **V** – Voided (striped)

### 🧮 Stats & Extras
- Cross-checks computed stats vs official table  
- Pulls club logos dynamically  
- Calculates **next fixture** for each team  
- Generates a polished HTML report

### 📧 Email Automation
- Sends **one** email containing:
  - Inline HTML for Div 3  
  - Full multi-division HTML as attachment  
- Powered by Gmail API + OAuth2 token  
- GitHub Actions–ready for weekly automation

---

## 📁 Project Structure (Conceptual)

```
scraper/
 ├── main.py             # Main script
 ├── playwright_login.py
 ├── fixtures_parser.py
 ├── form_builder.py
 ├── email_sender.py
 ├── templates/
 │     ├── inline_div3.html
 │     └── full_report.html
 └── README.md
```

---

## 📝 How the Scraper Works

1. Logs in to YFL LeagueHub  
2. For each division:
   - Scrapes official standings  
   - Scrapes all weeks of fixtures  
   - Builds full form guide  
   - Predicts next fixture  
3. Generates:
   - Inline HTML (Div 3 only)  
   - Full HTML (Div 1–3 with tabs)  
4. Sends one email with:
   - Inline HTML in body  
   - Full HTML attached  

---

## 🔧 Configuration

### Change Age Groups or Divisions
Edit the tournament list:

```python
TOURNAMENTS = [
    (90, "U11 Division 1", "panel-div1"),
    (91, "U11 Division 2", "panel-div2"),
    (92, "U11 Division 3", "panel-div3"),
]
```

### Change Inline Email Division
Switch to Div 1 or Div 2 by replacing the inline section generator.

### Change Email Recipients
Update the Gmail sender module.

---

## 🔐 Gmail API Authentication

The project uses a specially patched **InstalledAppFlow OOB mode** that works in headless / CI environments.

Steps:
1. Upload `client_secret.json`
2. Script prints OAuth URL
3. You paste the authorization code  
4. Script saves `gmail_token.json`  
5. GitHub Actions loads the token from secrets

Token automatically refreshes until revoked.

---

## 🏃 GitHub Actions (Weekly Automation)

Workflow steps:
1. Restore secrets  
2. Install Python + dependencies  
3. Install Playwright browsers  
4. Recreate Gmail OAuth token  
5. Run `python main.py`  
6. Email is delivered automatically

---

## ⚠️ Limitations

- Requires Playwright browser support  
- Gmail API must be enabled in Google Cloud  
- Tokens can expire or be revoked  
- YFL portal UI changes may require selector updates  

---

## 🔐 Security Notes

- **Never** commit secrets  
- Use GitHub Actions encrypted secrets:
  - `YFL_USERNAME`
  - `YFL_PASSWORD`
  - `GMAIL_TOKEN_JSON`
  - `CLIENT_SECRET_JSON`
- Keep OAuth scopes minimal (`gmail.send` only)

---

## 📝 License

This automation is unofficial and not affiliated with YFL or LeagueHub.  
You may reuse and modify it for personal or club use.

---

## 📬 Contact

For enhancements or configuration help, open an Issue on GitHub.
