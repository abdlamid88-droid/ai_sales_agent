# GCP Compute Engine Deployment & Meta Webhook Configuration Guide

Target Domain: **`autoparts-ai.duckdns.org`**  
GCP Project ID: **`project-21948359-4de0-4ed8-8b7`**

---

## 1. GCP Firewall Verification

Verified Google Cloud firewall rules allowing ingress HTTP (port 80) and HTTPS (port 443) traffic:
```bash
gcloud compute firewall-rules list --project=project-21948359-4de0-4ed8-8b7
```
Active Rules:
- `allow-http`: TCP 80 (INGRESS, ALLOW)
- `allow-https`: TCP 443 (INGRESS, ALLOW)
- `allow-http-https`: TCP 80, 443 (INGRESS, ALLOW)

---

## 2. Systemd Service Setup (`autoparts-bot.service`)

1. Copy the service file to systemd directory:
   ```bash
   sudo cp deploy/autoparts-bot.service /etc/systemd/system/autoparts-bot.service
   ```
2. Enable and start Uvicorn service on port 8005:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable autoparts-bot.service
   sudo systemctl start autoparts-bot.service
   ```
3. Check status:
   ```bash
   sudo systemctl status autoparts-bot.service
   ```

---

## 3. Nginx & Certbot SSL Setup (`autoparts-ai.duckdns.org`)

1. Copy Nginx bootstrap configuration:
   ```bash
   sudo cp deploy/nginx-autoparts.conf /etc/nginx/sites-available/autoparts.conf
   sudo ln -s /etc/nginx/sites-available/autoparts.conf /etc/nginx/sites-enabled/
   ```
2. Verify configuration and reload Nginx:
   ```bash
   sudo nginx -t
   sudo systemctl reload nginx
   ```
3. Obtain Let's Encrypt SSL certificate for `autoparts-ai.duckdns.org`:
   ```bash
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d autoparts-ai.duckdns.org
   ```

---

## 4. Meta Developer Dashboard Webhook Configuration

1. Go to [Meta Developers Portal](https://developers.facebook.com/) -> App -> **WhatsApp** -> **Configuration** -> **Webhook**.
2. Click **Edit**:
   - **Callback URL**: `https://autoparts-ai.duckdns.org/webhook`
   - **Verify Token**: `my_parts_bot_2026` (matches `VERIFY_TOKEN` in `.env`)
3. Click **Verify and Save**.
4. Subscribe to **`messages`** webhook field.
