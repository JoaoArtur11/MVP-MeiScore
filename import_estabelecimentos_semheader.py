import duckdb
from pathlib import Path
import sys
import time

from project_paths import DB_PATH, get_rfb_files

MAX_LINE_BYTES = 134217728  # 128MB


def make_select(file_path: str, enc: str) -> str:
    f = file_path.replace("'", "''")
    return f"""
        SELECT * FROM read_csv_auto(
            '{f}',
            sep=';',
            header=false,
            encoding='{enc}',
            union_by_name=true,
            strict_mode=false,
            all_varchar=true,
            ignore_errors=true,
            max_line_size={MAX_LINE_BYTES}
        )
    """


def try_create(first_file: str):
    for enc in ["latin-1", "utf-16", "utf-8"]:
        try:
            con = duckdb.connect(str(DB_PATH))
            con.execute("PRAGMA threads=8;")
            con.execute("DROP TABLE IF EXISTS estabelecimentos;")
            con.execute(f"CREATE TABLE estabelecimentos AS {make_select(first_file, enc)};")
            con.close()
            print(f"CREATE OK {Path(first_file).name} (enc={enc})")
            return
        except Exception as e:
            try:
                con.close()
            except Exception:
                pass
            print(f"   falhou CREATE (enc={enc}): {e}")
            time.sleep(0.2)
    raise RuntimeError("Nao consegui criar estabelecimentos.")


def try_insert(file_path: str):
    for enc in ["latin-1", "utf-16", "utf-8"]:
        try:
            con = duckdb.connect(str(DB_PATH))
            con.execute("PRAGMA threads=8;")
            con.execute(f"INSERT INTO estabelecimentos {make_select(file_path, enc)};")
            con.close()
            print(f"INSERT OK {Path(file_path).name} (enc={enc})")
            return
        except Exception as e:
            try:
                con.close()
            except Exception:
                pass
            print(f"   falhou INSERT {Path(file_path).name} (enc={enc}): {e}")
            time.sleep(0.2)
    raise RuntimeError(f"Nao consegui inserir {file_path}")


def main():
    est_files = get_rfb_files("estabelecimentos")
    if not est_files:
        raise RuntimeError("Nao encontrei arquivos de ESTABELECIMENTOS.")

    print("ESTABELE:", len(est_files), "ex:", est_files[0])

    try_create(est_files[0])
    for f in est_files[1:]:
        try_insert(f)

    con = duckdb.connect(str(DB_PATH))
    print("COUNT estabelecimentos:", con.execute("SELECT COUNT(*) FROM estabelecimentos").fetchone()[0])
    con.close()
    print("OK estabelecimentos (header=false)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERRO:", e)
        sys.exit(1)
