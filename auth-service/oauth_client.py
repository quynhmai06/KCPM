import os
from authlib.integrations.flask_client import OAuth

oauth = OAuth()

def register_providers(app):
    oauth.init_app(app)

    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        access_token_url="https://oauth2.googleapis.com/token",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        api_base_url="https://www.googleapis.com/oauth2/v2/",
        client_kwargs={"scope": "openid email profile"},
    )

    oauth.register(
        name="facebook",
        client_id=os.getenv("FACEBOOK_CLIENT_ID"),
        client_secret=os.getenv("FACEBOOK_CLIENT_SECRET"),
        access_token_url="https://graph.facebook.com/v18.0/oauth/access_token",
        authorize_url="https://www.facebook.com/v18.0/dialog/oauth",
        api_base_url="https://graph.facebook.com/v18.0/",
        client_kwargs={"scope": "email"},
    )
