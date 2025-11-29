#!/usr/bin/env python3

import os
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator
from typing import Literal
import datetime
import subprocess
from pathlib import Path
import sys
import ujson as json
from signal_processors.tradingview_processor import TradingViewProcessor


class TradingViewSignal(BaseModel):
    """TradingView webhook signal payload."""
    # Required fields
    symbol: str = Field(..., example="SOLUSDT", description="Trading pair symbol")
    direction: str = Field(..., example="long", description="Position direction: long, short, or flat")
    action: str = Field(..., example="buy", description="Trade action: buy or sell")
    size: str = Field(..., example="14.08/100", description="Position size as fraction (e.g. '14.08/100' for long, '-14.08/100' for short, '0/100' for exits)")
    # Optional fields (still accepted but hidden from docs)
    leverage: str = Field(None, description="Leverage multiplier (empty string or omit for exits)")
    priority: str = Field(None, json_schema_extra={"hidden": True})
    takeprofit: str = Field(None, json_schema_extra={"hidden": True})
    trailstop: str = Field(None, json_schema_extra={"hidden": True})
    price: str = Field(None, description="Signal price at time of alert")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ("long", "short", "flat"):
            raise ValueError("direction must be 'long', 'short', or 'flat'")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("action must be 'buy' or 'sell'")
        return v

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: str) -> str:
        v = v.strip()
        if v.lower().startswith("exit"):
            return v
        if "/" not in v:
            raise ValueError("size must be in format 'X/100' or 'Exit @ price'")
        try:
            num, denom = v.split("/")
            float(num)
            float(denom)
        except ValueError:
            raise ValueError("size must be numeric fraction like '14.08/100'")
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "1. Open Long",
                    "description": "Initial long entry at 14.08% of portfolio",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "long",
                        "action": "buy",
                        "size": "14.08/100",
                        "leverage": "3"
                    }
                },
                {
                    "summary": "2. Add to Long",
                    "description": "Increase long position to 33.78% of portfolio",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "long",
                        "action": "buy",
                        "size": "33.78/100",
                        "leverage": "3"
                    }
                },
                {
                    "summary": "3. Close Long",
                    "description": "Exit long position",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "flat",
                        "action": "sell",
                        "size": "0/100"
                    }
                },
                {
                    "summary": "4. Open Short",
                    "description": "Initial short entry at 14.08% of portfolio (negative size)",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "short",
                        "action": "sell",
                        "size": "-14.08/100",
                        "leverage": "3"
                    }
                },
                {
                    "summary": "5. Add to Short",
                    "description": "Increase short position to 33.78% of portfolio",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "short",
                        "action": "sell",
                        "size": "-33.78/100",
                        "leverage": "3"
                    }
                },
                {
                    "summary": "6. Close Short",
                    "description": "Exit short position",
                    "value": {
                        "symbol": "SOLUSDT",
                        "direction": "flat",
                        "action": "buy",
                        "size": "0/100"
                    }
                }
            ]
        }
    }


class WebhookResponse(BaseModel):
    """Response returned after successful webhook processing."""
    status: Literal["ok"] = Field(..., example="ok", description="Status of the webhook processing")


def setup_domain(domain_name):
    # Install required packages for Certbot and NGINX
    subprocess.run(["sudo", "apt", "install", "-y", "nginx-full"], check=True)
    subprocess.run(["sudo", "snap", "install", "--classic", "certbot"], check=True)

    # Download and configure the acme-dns-auth script for Certbot
    acme_dns_script = "/etc/letsencrypt/acme-dns-auth.py"
    
    # Create the /etc/letsencrypt directory if it doesn't exist
    subprocess.run(["sudo", "mkdir", "-p", "/etc/letsencrypt"], check=True)
    
    if not os.path.exists(acme_dns_script):
        subprocess.run(
            [
                "wget",
                "-O",
                "/tmp/acme-dns-auth.py",
                "https://github.com/joohoi/acme-dns-certbot-joohoi/raw/master/acme-dns-auth.py",
            ],
            check=True,
        )
        subprocess.run(["chmod", "+x", "/tmp/acme-dns-auth.py"], check=True)
        
        # Replace the top line with the python3 shebang before moving
        with open("/tmp/acme-dns-auth.py", "r") as f:
            lines = f.readlines()
        lines[0] = "#!/usr/bin/env python3\n"
        with open("/tmp/acme-dns-auth.py", "w") as f:
            f.writelines(lines)
        
        # Now move the modified file
        subprocess.run(["sudo", "mv", "/tmp/acme-dns-auth.py", acme_dns_script], check=True)

    # Define NGINX config paths
    nginx_config_path = f"/etc/nginx/sites-available/{domain_name}"
    nginx_symlink_path = f"/etc/nginx/sites-enabled/{domain_name}"

    # Create NGINX configuration if it doesn't exist
    temp_file = f"/tmp/{domain_name}_nginx_config"
    with open(temp_file, "w", encoding="utf-8") as temp:
        temp.write(
            f"""
            server {{
                listen 80;
                server_name {domain_name};
                # Redirect all HTTP requests to HTTPS
                return 301 https://$host$request_uri;
            }}

            server {{
                listen 443 ssl;
                server_name {domain_name};

                ssl_certificate /etc/letsencrypt/live/{domain_name}/fullchain.pem;
                ssl_certificate_key /etc/letsencrypt/live/{domain_name}/privkey.pem;

                location / {{
                    proxy_pass http://127.0.0.1:8000;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                }}
            }}
            """
        )
    subprocess.run(["sudo", "mv", temp_file, nginx_config_path], check=True)

    # Create a symlink in sites-enabled if it doesn't exist
    if not os.path.exists(nginx_symlink_path):
        subprocess.run(["sudo", "ln", "-s", nginx_config_path, nginx_symlink_path], check=True)

    # Obtain SSL certificates using Certbot with DNS challenge
    subprocess.run(
        [
            "sudo",
            "certbot",
            "certonly",
            "--manual",
            "--manual-auth-hook",
            acme_dns_script,
            "--preferred-challenges",
            "dns",
            "--debug-challenges",
            "-d",
            f"*.{domain_name}",
            "-d",
            domain_name,
        ],
        check=True,
    )

    # Test and reload NGINX
    subprocess.run(["sudo", "nginx", "-t"], check=True)
    subprocess.run(["sudo", "nginx", "-s", "reload"], check=True)


# FastAPI app
app = FastAPI()

# Get the signal file prefix from the processor
SIGNAL_FILE_PREFIX = TradingViewProcessor.SIGNAL_FILE_PREFIX

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/", summary="TradingView Webhook", description="Receives trading signals from TradingView alerts and stores them for processing.", response_model=WebhookResponse)
async def tradingview_webhook(signal: TradingViewSignal):
    """
    Receive a TradingView webhook signal.
    
    The signal is appended to a daily log file in `raw_signals/tradingview/` 
    and processed by the TradingViewProcessor for trade execution.
    
    **Direction values:**
    - `long`: Open or add to long position
    - `short`: Open or add to short position  
    - `flat`: Close all positions (exit)
    
    **Size format:**
    - For entries: `"5.8/100"` means 5.8% of portfolio
    - For exits: `"Exit @ 3263.55"` indicates exit price
    """
    body = signal.model_dump()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    # Format the log entry as a single line
    log_entry = f'{timestamp} {json.dumps(body)}\n'

    # Store logs in a secure directory
    log_dir = Path("raw_signals", "tradingview")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / f"{SIGNAL_FILE_PREFIX}_{datetime.datetime.now().strftime('%Y-%m-%d')}.log"
    with open(log_file_path, "a") as log_file:
        log_file.write(log_entry)

    return WebhookResponse(status="ok")


if __name__ == "__main__":
    # Check if a domain argument is provided
    if len(sys.argv) > 1:
        domain_name = sys.argv[1]
        setup_domain(domain_name)
        print(f"Domain {domain_name} setup complete.")
        quit()
    else:
        print("No domain provided. Running FastAPI without domain setup.")

    # Start the FastAPI application
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
