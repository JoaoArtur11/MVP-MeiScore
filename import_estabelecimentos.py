# import_estabelecimentos.py
import duckdb
from pathlib import Path
import sys
import time

from project_paths import DB_PATH, get_rfb_files

# max_line_size em bytes
MAX_LINE_BYTES = 134217728  # 128MB


def make_select(file_path: str, enc: str) -> str:
    f = file_path.replace("'", "''")
    return f"""
        SELECT * FROM read_csv_auto(
            '{f}',
            sep=';',
            header=true,
            encoding='{enc}',
            union_by_name=true,
            strict_mode=false,
            all_varchar=true,
            ignore_errors=true,
            max_line_size={MAX_LINE_BYTES}
        )
    """


def try_create_table(first_file: str):
    for enc in ["latin-1", "utf-16", "utf-8"]:
        try:
            con = duckdb.connect(str(DB_PATH))
            con.execute("PRAGMA threads=8;")
            con.execute("DROP TABLE IF EXISTS estabelecimentos;")
            sel = make_select(first_file, enc)
            con.execute(f"CREATE TABLE estabelecimentos AS {sel};")
            con.close()
            print(f"CREATE estabelecimentos OK com {Path(first_file).name} (enc={enc})")
            return enc
        except Exception as e:
            try:
                con.close()
            except Exception:
                pass
            print(f"   falhou CREATE (enc={enc}): {e}")
            time.sleep(0.2)
    raise RuntimeError("Nao consegui criar a tabela estabelecimentos com nenhum encoding.")


def try_insert_file(file_path: str) -> str:
    for enc in ["latin-1", "utf-16", "utf-8"]:
        try:
            con = duckdb.connect(str(DB_PATH))
            con.execute("PRAGMA threads=8;")
            sel = make_select(file_path, enc)
            con.execute(f"INSERT INTO estabelecimentos {sel};")
            con.close()
            print(f"INSERT OK {Path(file_path).name} (enc={enc})")
            return enc
        except Exception as e:
            try:
                con.close()
            except Exception:
                pass
            print(f"   falhou INSERT {Path(file_path).name} (enc={enc}): {e}")
            time.sleep(0.2)

    raise RuntimeError(f"Nao consegui inserir o arquivo {file_path} com nenhum encoding.")


def main():
    est_files = get_rfb_files("estabelecimentos")
    print("ESTABELECIMENTOS:", len(est_files))
    if not est_files:
        raise RuntimeError("Nenhum arquivo de ESTABELECIMENTOS encontrado em 'dados cnae'/'rf_cnpj_csv'.")

    print("Exemplo:", est_files[0])
    print("max_line_size(bytes):", MAX_LINE_BYTES)

    enc_used = try_create_table(est_files[0])

    used_map = {Path(est_files[0]).name: enc_used}
    for f in est_files[1:]:
        enc = try_insert_file(f)
        used_map[Path(f).name] = enc

    con = duckdb.connect(str(DB_PATH))
    cnt = con.execute("SELECT COUNT(*) FROM estabelecimentos").fetchone()[0]
    con.close()
    print("COUNT estabelecimentos:", cnt)

    print("\nEncodings usados por arquivo:")
    for k, v in used_map.items():
        print(f"  {k}: {v}")

    print("\nOK - estabelecimentos importado")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERRO:", e)
        sys.exit(1)
