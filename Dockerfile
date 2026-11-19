FROM python:3.11-slim

WORKDIR /app

# Installation des utilitaires système nécessaires
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Ports exposés : 8888 (Jupyter Notebook) et 8866 (Voilà Dashboard)
EXPOSE 8888 8866

# Commande par défaut : Jupyter Notebook sans mot de passe local
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''", "--NotebookApp.password=''"]
