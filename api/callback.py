import json
import base64
import os
import requests
import xmlrpc.client
from http.server import BaseHTTPRequestHandler
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

# Load environment variables configured in Vercel Dashboard
ODOO_URL = os.environ.get("ODOO_URL")
ODOO_DB = os.environ.get("ODOO_DB")
ODOO_USERNAME = os.environ.get("ODOO_USERNAME")
ODOO_API_KEY = os.environ.get("ODOO_API_KEY")

CONSUMER_KEY = os.environ.get("DARAJA_CONSUMER_KEY")
CONSUMER_SECRET = os.environ.get("DARAJA_CONSUMER_SECRET")
INITIATOR_NAME = os.environ.get("DARAJA_INITIATOR_NAME")
INITIATOR_PASSWORD = os.environ.get("DARAJA_INITIATOR_PASSWORD")
B2C_SHORTCODE = os.environ.get("DARAJA_B2C_SHORTCODE")
APP_URL = os.environ.get("VERCEL_PROJECT_URL")  # e.g., https://your-project.vercel.app

BASE_URL = "https://api.safaricom.co.ke"  # Use https://sandbox.safaricom.co.ke for testing

def get_daraja_token():
    res = requests.get(
        f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials",
        auth=(CONSUMER_KEY, CONSUMER_SECRET),
        timeout=10
    )
    return res.json().get("access_token")

def encrypt_security_credential(password):
    cert_path = os.path.join(os.path.dirname(__file__), "..", "cert.cer")
    with open(cert_path, "rb") as f:
        cert_data = f.read()
    cert = load_pem_x509_certificate(cert_data)
    encrypted = cert.public_key().encrypt(
        password.encode('utf-8'),
        padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode('utf-8')

def update_odoo(record_id, values):
    common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
    models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'x_m_pesa_b2c_transacti', 'write',
        [[record_id], values]
    )

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        data = json.loads(body.decode('utf-8'))

        record_id = data.get('record_id')
        phone = data.get('phone')
        amount = data.get('amount')
        remarks = data.get('remarks', 'Disbursement')

        try:
            token = get_daraja_token()
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload = {
                "InitiatorName": INITIATOR_NAME,
                "SecurityCredential": encrypt_security_credential(INITIATOR_PASSWORD),
                "CommandID": "BusinessPayment",
                "Amount": int(amount),
                "PartyA": B2C_SHORTCODE,
                "PartyB": str(phone),
                "Remarks": remarks,
                "QueueTimeOutURL": f"{APP_URL}/api/callback",
                "ResultURL": f"{APP_URL}/api/callback",
                "Occasion": remarks
            }

            res = requests.post(f"{BASE_URL}/mpesa/b2c/v3/paymentrequest", json=payload, headers=headers, timeout=15).json()

            if res.get("ResponseCode") == "0":
                update_odoo(record_id, {
                    'x_studio_char_3': res.get("ConversationID"),  # Conversation ID field
                })
                response_data = {"status": "success", "conversation_id": res.get("ConversationID")}
                status_code = 200
            else:
                response_data = {"status": "error", "detail": res}
                status_code = 400

        except Exception as e:
            response_data = {"status": "exception", "error": str(e)}
            status_code = 500

        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode('utf-8'))