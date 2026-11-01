"""Run the web UI:  PYTHONPATH=src python -m campusride.web"""
from .app import ADMIN_EMAIL, ADMIN_PASSWORD, create_app

if __name__ == "__main__":
    print(f"Demo admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print("Any institution email ending in .edu can register (for example you@pes.edu).")
    create_app({"ANY_EDU_DOMAIN": True}).run(debug=True)
