import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm
from project_paths import DADOS_CNAE_DIR

BASE_DIR_URL = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; data-pipeline/1.0)"})

def get_html(url: str) -> str:
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    return r.text

def latest_month_folder(base_url: str) -> str:
    """
    Encontra a pasta mais recente no formato YYYY-MM/ no index HTML.
    Ignora 'temp/'.
    """
    html = get_html(base_url)
    soup = BeautifulSoup(html, "html.parser")
    folders = []
    for a in soup.select("a"):
        href = a.get("href", "")
        if re.fullmatch(r"\d{4}-\d{2}/", href):
            folders.append(href)
    if not folders:
        raise RuntimeError("Nenhuma pasta YYYY-MM/ encontrada no índice.")
    folders.sort()  # ordenação lexicográfica funciona para YYYY-MM
    return folders[-1]

def list_zip_links(folder_url: str) -> list[tuple[str, str]]:
    """
    Retorna lista (nome_arquivo, url_absoluta) para todos os .zip na pasta.
    """
    html = get_html(folder_url)
    soup = BeautifulSoup(html, "html.parser")
    zips = []
    for a in soup.select("a"):
        href = a.get("href", "")
        if href.lower().endswith(".zip"):
            zips.append((href, urljoin(folder_url, href)))
    return zips

def download_file(url: str, out_path: str, max_retries: int = 5):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # suporte a resume
    temp_path = out_path + ".part"
    downloaded = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0

    for attempt in range(1, max_retries + 1):
        try:
            headers = {}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            with SESSION.get(url, stream=True, timeout=120, headers=headers) as r:
                if r.status_code not in (200, 206):
                    r.raise_for_status()

                total = r.headers.get("Content-Length")
                total = int(total) + downloaded if total and r.status_code == 206 else int(total) if total else None

                mode = "ab" if downloaded > 0 else "wb"
                with open(temp_path, mode) as f, tqdm(
                    total=total, initial=downloaded, unit="B", unit_scale=True, desc=os.path.basename(out_path)
                ) as pbar:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            os.replace(temp_path, out_path)
            return

        except Exception as e:
            print(f"[tentativa {attempt}/{max_retries}] falha ao baixar {url}: {e}")
            time.sleep(2 * attempt)

    raise RuntimeError(f"Falhou após {max_retries} tentativas: {url}")

def main(out_dir=str(DADOS_CNAE_DIR), only_needed=True):
    folder = latest_month_folder(BASE_DIR_URL)
    month_url = urljoin(BASE_DIR_URL, folder)
    print("Pasta mais recente:", month_url)

    zips = list_zip_links(month_url)
    print("Total de zips na pasta:", len(zips))

    if only_needed:
        # ajuste fino: baixe apenas o essencial p/ MEI
        patterns = [
            r"^Empresas\d+\.zip$",
            r"^Estabelecimentos\d+\.zip$",
            r"^Simples.*\.zip$",      # pode variar o nome
            r"^Cnaes.*\.zip$",        # auxiliares, se existir
            r"^Municipios.*\.zip$",
            r"^Naturezas.*\.zip$",
        ]
        def wanted(name: str) -> bool:
            return any(re.match(p, name, flags=re.IGNORECASE) for p in patterns)

        zips = [(n,u) for (n,u) in zips if wanted(n)]
        print("Zips selecionados (MEI):", len(zips))

    for name, url in zips:
        out_path = os.path.join(out_dir, folder.strip("/"), name)
        if os.path.exists(out_path):
            continue
        download_file(url, out_path)

if __name__ == "__main__":
    main()
